"""Experiment 04: metric audit, false-positive analysis, and robust ORB verification."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import resource
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from duplicate_lab.benchmark_copydays import GROUND_TRUTH_SOURCE, _display_path, _jpgs
from duplicate_lab.benchmark_strong import build_strong_manifest
from duplicate_lab.experiments.benchmark_local_features import (
    PHASH_THRESHOLD,
    TOP_K_CANDIDATES,
    identity_partition,
)
from duplicate_lab.experiments.geometric_verification import (
    GeometricEvidence,
    VerificationConfig,
    analyze_pair,
    reciprocal_rank_fusion,
)
from duplicate_lab.experiments.local_features import ORBConfig, extract_features
from duplicate_lab.hashing import oriented_phashes, sha256_file

SEED = 202503
METHODS = ("current", "selective", "mutual", "conservative")
EVIDENCE_REVISION = "04.2-config-aware-homography"
RISK_POLICY = {
    "eligible_methods": ("mutual", "conservative"),
    "maximum_pair_fpr": 0.001,
    "maximum_query_fpr": 0.05,
    "objective": "maximize confirmation recall, then precision, then stable method/config order",
}


def audited_metrics(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    """Report pair and query denominators independently and explicitly."""
    positives = [row for row in rows if row["expected_original"] and not row["error"]]
    prefix = method + "_"
    tp = sum(bool(row[prefix + "expected_confirmed"]) for row in positives)
    predicted_pairs = sum(int(row[prefix + "confirmed_count"]) for row in positives)
    fp = predicted_pairs - tp
    pair_denominator = sum(int(row["database_count"]) for row in positives)
    negative_pair_denominator = pair_denominator - len(positives)
    queries_with_fp = sum(
        int(row[prefix + "confirmed_count"]) > int(row[prefix + "expected_confirmed"])
        for row in positives
    )
    result: dict[str, Any] = {
        "positive_query_denominator": len(positives),
        "evaluated_pair_denominator": pair_denominator,
        "negative_pair_denominator": negative_pair_denominator,
        "confirmed_pair_denominator": predicted_pairs,
        "true_positive_pairs": tp,
        "false_positive_pairs": fp,
        "false_negative_pairs": len(positives) - tp,
        "precision": tp / predicted_pairs if predicted_pairs else None,
        "confirmation_recall": tp / len(positives) if positives else None,
        "false_positive_rate_per_pair": fp / negative_pair_denominator
        if negative_pair_denominator
        else None,
        "queries_with_false_positive": queries_with_fp,
        "query_false_positive_rate": queries_with_fp / len(positives) if positives else None,
        "candidate_recall": sum(row[prefix + "expected_candidate"] for row in positives)
        / len(positives)
        if positives
        else None,
    }
    for k in (1, 5, 10):
        result[f"recall_at_{k}"] = (
            sum(row[prefix + "rank"] is not None and row[prefix + "rank"] <= k for row in positives)
            / len(positives)
            if positives
            else None
        )
    result["confidence_intervals_95_wilson"] = {
        "precision": wilson_interval(tp, predicted_pairs),
        "confirmation_recall": wilson_interval(tp, len(positives)),
        "false_positive_rate_per_pair": wilson_interval(fp, negative_pair_denominator),
        "query_false_positive_rate": wilson_interval(queries_with_fp, len(positives)),
    }
    return result


def natural_pair_metrics(records: list[dict[str, Any]], method: str) -> dict[str, Any]:
    accepted = sum(record[method] for record in records)
    return {
        "verified_negative_pairs": len(records),
        "false_positive_pairs": accepted,
        "false_positive_rate_per_pair": accepted / len(records) if records else None,
        "false_positive_rate_95_wilson": wilson_interval(accepted, len(records)),
        "evidence": GROUND_TRUTH_SOURCE
        + "; different Copydays original capture IDs are distinct photographs",
    }


def negative_query_metrics(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    """Measure negative queries separately from pair-level negatives."""
    negatives = [row for row in rows if row["expected_original"] is None and not row["error"]]
    accepted = sum(row[f"{method}_confirmed_count"] > 0 for row in negatives)
    return {
        "negative_query_denominator": len(negatives),
        "negative_queries_accepted": accepted,
        "negative_query_acceptance_rate": accepted / len(negatives) if negatives else None,
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    probability = successes / total
    denominator = 1 + z**2 / total
    centre = (probability + z**2 / (2 * total)) / denominator
    margin = (
        z * ((probability * (1 - probability) / total + z**2 / (4 * total**2)) ** 0.5) / denominator
    )
    return [centre - margin, centre + margin]


def _decision(evidence: GeometricEvidence, method: str, config: VerificationConfig) -> bool:
    if method == "current":
        return evidence.confirms_current()
    if method == "selective":
        return evidence.confirms_selective(config)
    if method == "mutual":
        return evidence.confirms_mutual(config)
    if method == "conservative":
        return (
            evidence.confirms_selective(config)
            and evidence.mutual_matches >= config.min_matches
            and evidence.unique_train_ratio >= 0.85
        )
    raise ValueError(method)


def _score(evidence: GeometricEvidence) -> tuple[float, ...]:
    median = evidence.median_distance if evidence.median_distance is not None else 256.0
    legacy_prefilter_passed = (
        evidence.ratio_matches >= 8
        and min(evidence.query_coverage, evidence.candidate_coverage) >= 0.02
        and not evidence.degenerate
    )
    return (
        float(evidence.inliers) if legacy_prefilter_passed else 0.0,
        evidence.inlier_ratio if legacy_prefilter_passed else 0.0,
        float(evidence.ratio_matches),
        -median,
    )


def _configs() -> tuple[VerificationConfig, ...]:
    return (
        VerificationConfig(),
        VerificationConfig(min_inliers=10, min_inlier_ratio=0.45, min_grid_cells=4),
        VerificationConfig(
            min_inliers=12,
            min_inlier_ratio=0.50,
            min_inlier_coverage=0.04,
            min_grid_cells=4,
            max_symmetric_error=3.5,
        ),
    )


def _natural_pairs(
    originals: tuple[Path, ...], partition: str, limit: int = 96
) -> tuple[tuple[Path, Path], ...]:
    """Select hard, deterministic distinct-capture pairs by nearest pHash."""
    eligible = tuple(path for path in originals if identity_partition(path.stem) == partition)
    hashes = {path: oriented_phashes(path)[0] for path in eligible}
    pairs: set[tuple[Path, Path]] = set()
    for left in eligible:
        ranked = sorted(
            (int(hashes[left] - hashes[right]), right.name, right)
            for right in eligible
            if right != left
        )
        right = ranked[0][2]
        pairs.add(tuple(sorted((left, right), key=lambda item: item.name)))
    return tuple(sorted(pairs, key=lambda pair: (pair[0].name, pair[1].name)))[:limit]


def _evaluate_pairs(
    pairs: tuple[tuple[Path, Path], ...],
    features: dict[Path, Any],
    config: VerificationConfig,
    evidence_cache: dict[tuple[Path, Path, tuple[float, float, int]], GeometricEvidence]
    | None = None,
) -> list[dict[str, Any]]:
    result = []
    for left, right in pairs:
        key = (left, right, config.evidence_fingerprint())
        evidence = evidence_cache.get(key) if evidence_cache is not None else None
        if evidence is None:
            evidence = analyze_pair(features[left], features[right], config)
            if evidence_cache is not None:
                evidence_cache[key] = evidence
        result.append(
            {
                "left": left.name,
                "right": right.name,
                **{method: _decision(evidence, method, config) for method in METHODS},
                "evidence": asdict(evidence),
            }
        )
    return result


def _evaluate_queries(
    queries: tuple[Path, ...],
    database: tuple[Path, ...],
    expected: dict[Path, Path],
    features: dict[Path, Any],
    hashes: dict[Path, Any],
    config: VerificationConfig,
    root: Path,
    collect_false_positives: bool,
    evidence_cache: dict[tuple[Path, Path, tuple[float, float, int]], GeometricEvidence]
    | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, false_positives = [], []
    for query in queries:
        truth = expected[query]
        phash_ranked = sorted(
            database,
            key=lambda candidate: (
                min(int(hashes[query][0] - value) for value in hashes[candidate]),
                candidate.name,
            ),
        )
        evidences = {}
        for candidate in database:
            key = (query, candidate, config.evidence_fingerprint())
            evidence = evidence_cache.get(key) if evidence_cache is not None else None
            if evidence is None:
                evidence = analyze_pair(features[query], features[candidate], config)
                if evidence_cache is not None:
                    evidence_cache[key] = evidence
            evidences[candidate] = evidence
        orb_ranked = sorted(
            database,
            key=lambda candidate: (_score(evidences[candidate]), candidate.name),
            reverse=True,
        )
        # Make lexical tie-breaking ascending without changing descending evidence score.
        orb_ranked = sorted(orb_ranked, key=lambda candidate: candidate.name)
        orb_ranked = sorted(
            orb_ranked, key=lambda candidate: _score(evidences[candidate]), reverse=True
        )
        rankings: dict[str, list[Path]] = {method: orb_ranked for method in METHODS}
        candidate_sets: dict[str, set[Path]] = {
            method: set(orb_ranked[:TOP_K_CANDIDATES]) for method in METHODS
        }
        row: dict[str, Any] = {
            "query": _display_path(query, root),
            "expected_original": _display_path(truth, root),
            "database_count": len(database),
            "error": features[query].error,
        }
        for method in METHODS:
            confirmed = {
                candidate
                for candidate, evidence in evidences.items()
                if _decision(evidence, method, config)
            }
            row.update(
                {
                    f"{method}_rank": rankings[method].index(truth) + 1,
                    f"{method}_expected_candidate": truth in candidate_sets[method],
                    f"{method}_expected_confirmed": truth in confirmed,
                    f"{method}_confirmed_count": len(confirmed),
                }
            )
            if collect_false_positives:
                for candidate in sorted(confirmed - {truth}, key=lambda item: item.name):
                    false_positives.append(
                        {
                            "method": method,
                            "query": query,
                            "candidate": candidate,
                            "evidence": evidences[candidate],
                        }
                    )
        phash_names = [path.name for path in phash_ranked]
        orb_names = [path.name for path in orb_ranked]
        phash_candidates = {
            candidate
            for candidate in phash_ranked
            if min(int(hashes[query][0] - value) for value in hashes[candidate]) <= PHASH_THRESHOLD
        }
        union = list(
            dict.fromkeys((*phash_ranked[:TOP_K_CANDIDATES], *orb_ranked[:TOP_K_CANDIDATES]))
        )
        legacy_union = sorted(
            union,
            key=lambda path: (phash_ranked.index(path), orb_ranked.index(path), path.name),
        )
        rrf_names = [name for name, _ in reciprocal_rank_fusion([phash_names, orb_names])]
        row.update(
            {
                "phash_rank": phash_ranked.index(truth) + 1,
                "orb_rank": orb_ranked.index(truth) + 1,
                "legacy_union_rank": legacy_union.index(truth) + 1
                if truth in legacy_union
                else None,
                "union_without_reordering_rank": union.index(truth) + 1 if truth in union else None,
                "rrf_rank": rrf_names.index(truth.name) + 1,
                "phash_candidate": truth in phash_candidates,
            }
        )
        rows.append(row)
    return rows, false_positives


def _fusion_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for field in ("phash", "orb", "legacy_union", "union_without_reordering", "rrf"):
        ranks = [row[field + "_rank"] for row in rows]
        result[field] = {
            f"recall_at_{k}": sum(rank is not None and rank <= k for rank in ranks) / len(ranks)
            for k in (1, 5, 10)
        }
    return result


def _sample_false_positives(records: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    current = [record for record in records if record["method"] == "current"]
    ordered = sorted(
        current,
        key=lambda record: hashlib.sha256(
            f"{SEED}:{record['query']}:{record['candidate']}".encode()
        ).hexdigest(),
    )[:limit]
    return [
        {
            "query": record["query"],
            "candidate": record["candidate"],
            "evidence": asdict(record["evidence"]),
            "probable_cause": _cause(record["evidence"]),
            "cause_status": "heuristic_not_human_confirmed",
        }
        for record in ordered
    ]


def _cause(evidence: GeometricEvidence) -> str:
    if evidence.unique_train_ratio < 0.85:
        return "repetitive_correspondences"
    if min(evidence.query_grid_cells, evidence.candidate_grid_cells) < 3:
        return "spatially_concentrated"
    if evidence.degenerate or not evidence.plausible:
        return "implausible_or_degenerate_homography"
    if evidence.symmetric_error is not None and evidence.symmetric_error > 5:
        return "direct_inverse_inconsistency"
    return "locally_consistent_but_distinct_scene"


def _write_contact_sheets(samples: list[dict[str, Any]], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, sample in enumerate(samples):
        canvas = Image.new("RGB", (640, 280), "white")
        for offset, key in ((0, "query"), (320, "candidate")):
            with Image.open(sample[key]) as source:
                thumb = ImageOps.exif_transpose(source).convert("RGB")
                thumb.thumbnail((300, 220), Image.Resampling.LANCZOS)
                canvas.paste(thumb, (offset + 10, 10))
        draw = ImageDraw.Draw(canvas)
        evidence = sample["evidence"]
        caption = (
            f"{sample['probable_cause']} | inliers={evidence['inliers']} "
            f"ratio={evidence['inlier_ratio']:.3f} sym={evidence['symmetric_error']}"
        )
        draw.text((10, 240), caption[:100], fill="black")
        canvas.save(directory / f"false-positive-{index:02d}.jpg", quality=78)


def _split_distractors(paths: tuple[Path, ...]) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    ordered = sorted(
        paths,
        key=lambda path: hashlib.sha256(f"{SEED}:distractor:{path.name}".encode()).digest(),
    )
    middle = len(ordered) // 2
    return tuple(ordered[:middle]), tuple(ordered[middle:])


def run_experiment(
    dataset_root: Path, distractor_root: Path, *, smoke: bool = False
) -> dict[str, Any]:
    started = time.perf_counter()
    generated_at = dt.datetime.now(dt.UTC).isoformat()
    root = dataset_root.resolve()
    originals = _jpgs(root / "original")
    distractors = tuple(sorted((distractor_root / "database").glob("*.png")))
    calibration_distractors, evaluation_distractors = _split_distractors(distractors)
    manifest = build_strong_manifest(root)
    queries = tuple(item.query for item in manifest)
    expected = {item.query: item.original for item in manifest}
    calibration_queries = tuple(
        item.query for item in manifest if identity_partition(item.capture_id) == "calibration"
    )
    evaluation_queries = tuple(
        item.query for item in manifest if identity_partition(item.capture_id) == "test"
    )
    if smoke:
        calibration_queries = calibration_queries[:6]
        evaluation_queries = evaluation_queries[:8]
        calibration_distractors = calibration_distractors[:8]
        evaluation_distractors = evaluation_distractors[:8]
    all_paths = tuple(dict.fromkeys((*originals, *distractors, *queries)))
    orb_config = ORBConfig(nfeatures=1800, fast_threshold=12)
    features = {path: extract_features(path, orb_config) for path in all_paths}
    hashes = {path: oriented_phashes(path) for path in all_paths}
    calibration_pairs = _natural_pairs(originals, "calibration")
    evaluation_pairs = _natural_pairs(originals, "test")
    calibration = []
    calibration_cache: dict[tuple[Path, Path, tuple[float, float, int]], GeometricEvidence] = {}
    for config in _configs():
        rows, _ = _evaluate_queries(
            calibration_queries,
            (*originals, *calibration_distractors),
            expected,
            features,
            hashes,
            config,
            root,
            False,
            calibration_cache,
        )
        negatives = _evaluate_pairs(calibration_pairs, features, config, calibration_cache)
        metrics = {method: audited_metrics(rows, method) for method in METHODS}
        natural = {method: natural_pair_metrics(negatives, method) for method in METHODS}
        calibration.append(
            {"config": config.to_dict(), "metrics": metrics, "natural_negatives": natural}
        )

    eligible = []
    for index, entry in enumerate(calibration):
        for method_index, method in enumerate(RISK_POLICY["eligible_methods"]):
            metric = entry["metrics"][method]
            if (
                metric["false_positive_rate_per_pair"] <= RISK_POLICY["maximum_pair_fpr"]
                and metric["query_false_positive_rate"] <= RISK_POLICY["maximum_query_fpr"]
            ):
                eligible.append(
                    (
                        metric["confirmation_recall"],
                        metric["precision"],
                        -method_index,
                        -index,
                        index,
                        method,
                    )
                )
    if not eligible:
        raise RuntimeError("No calibration candidate satisfies the predeclared risk policy")
    *_, selected_index, selected_method = max(eligible)
    selected = _configs()[selected_index]
    rows, false_positives = _evaluate_queries(
        evaluation_queries,
        (*originals, *evaluation_distractors),
        expected,
        features,
        hashes,
        selected,
        root,
        True,
    )
    natural_records = _evaluate_pairs(evaluation_pairs, features, selected)
    samples = _sample_false_positives(false_positives)
    source_paths = (*originals, *distractors, *queries)
    return {
        "schema_version": 1,
        "experiment": "04-geometric-verification",
        "mode": "smoke" if smoke else "final",
        "generated_at_utc": generated_at,
        "code_revision": EVIDENCE_REVISION,
        "code_base_commit": "b14ffe4d7eaa25dee7505508620202975711bdf9",
        "seed": SEED,
        "metric_audit": {
            "experiment_03_impact": (
                "Published precision/recall pair counts are arithmetically correct. The field "
                "named false_positive_rate measured only synthetic negative-query acceptance, "
                "so it did not describe the 4,394 incorrect positive-query pairs. Experiment 04 "
                "adds pair FPR and "
                "query-with-FP rate; Experiment 03 files remain unchanged."
            ),
            "pair_rule": (
                "one query-candidate decision; the ground-truth candidate is the sole positive"
            ),
            "precision_denominator": "all confirmed query-candidate pairs",
            "recall_denominator": "positive queries (one expected pair per query)",
            "pair_fpr_denominator": "all evaluated non-ground-truth query-candidate pairs",
            "query_fpr_denominator": (
                "positive queries; event is at least one incorrect confirmation"
            ),
            "multiple_false_confirmations": (
                "counted individually for pair precision/FPR and once for query FPR"
            ),
            "experiment_03_ranking": (
                "ORB: descending (inliers, inlier ratio, filtered matches, negative median "
                "distance), lexical path tie-break. Union: ascending pHash rank first, ORB rank "
                "second; therefore "
                "pHash dominated ordering even when it had poor Strong retrieval."
            ),
        },
        "partition": {
            "unit": "Copydays capture identity",
            "rule": "SHA-256(seed:capture_id), same as Experiment 03",
            "calibration_queries": len(calibration_queries),
            "evaluation_queries": len(evaluation_queries),
            "calibration_natural_pairs": len(calibration_pairs),
            "evaluation_natural_pairs": len(evaluation_pairs),
            "calibration_distractors": len(calibration_distractors),
            "evaluation_distractors": len(evaluation_distractors),
            "distractor_overlap": bool(set(calibration_distractors) & set(evaluation_distractors)),
            "leakage_check": not (
                {path.stem for pair in calibration_pairs for path in pair}
                & {path.stem for pair in evaluation_pairs for path in pair}
            ),
            "caveat": (
                "Strong test identities were reported in Experiment 03 and are not a "
                "prospectively unseen benchmark. They were not used to select Experiment 04 "
                "thresholds. Natural evaluation "
                "pairs and distractors are identity-disjoint from calibration. The final database "
                "contains only its held-out distractor half, so absolute results are not directly "
                "comparable to the 256-distractor Experiment 03 scenario."
            ),
        },
        "configuration": {
            "selected_index": selected_index,
            "selected_method": selected_method,
            "selected": selected.to_dict(),
            "selection_scope": "confirmation method and decision thresholds",
            "evidence_parameters_fixed": selected.evidence_fingerprint(),
            "risk_policy": RISK_POLICY,
            "evidence_reuse": (
                "Only decision thresholds reuse evidence. Cache keys include ratio threshold, "
                "RANSAC threshold, and seed; changing any of them forces recomputation."
            ),
            "evidence_parameter_semantics": {
                "requires_recomputation": [
                    "ratio_threshold",
                    "ransac_reprojection_threshold",
                    "seed",
                ],
                "decision_only_reuses_measurements": [
                    "min_matches",
                    "min_inliers",
                    "min_inlier_ratio",
                    "min_inlier_coverage",
                    "min_grid_cells",
                    "max_symmetric_error",
                    "min_corner_area_ratio",
                    "max_corner_area_ratio",
                    "max_condition",
                    "max_perspective",
                    "min_scale",
                    "max_scale",
                    "max_shear_cosine",
                ],
            },
        },
        "prior_exploratory_results": {
            "status": "obsolete_not_homologated",
            "database": "157 originals plus all 256 distractors",
            "mutual": {
                "precision": 0.9847328244274809,
                "confirmation_recall": 0.8543046357615894,
                "false_positive_pairs": 2,
            },
            "warning": (
                "Observed before configuration plumbing and calibration-distribution corrections; "
                "retained only as exploratory evidence and not used for final selection."
            ),
        },
        "calibration": calibration,
        "evaluation": {
            "metrics": {method: audited_metrics(rows, method) for method in METHODS},
            "natural_negatives": {
                method: natural_pair_metrics(natural_records, method) for method in METHODS
            },
            "fusion": _fusion_metrics(rows),
            "rows": rows,
        },
        "false_positive_analysis": {
            "total_current_false_positive_pairs": audited_metrics(rows, "current")[
                "false_positive_pairs"
            ],
            "sample_rule": "first 12 by SHA-256(seed:query:candidate)",
            "samples": [
                {
                    **sample,
                    "query": _display_path(sample["query"], root),
                    "candidate": _display_path(sample["candidate"], root),
                }
                for sample in samples
            ],
        },
        "timing": {
            "total_seconds": time.perf_counter() - started,
            "scope": "feature extraction, calibration, evaluation, diagnostics and hashing",
        },
        "memory": {
            "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
            "scope": "process-lifetime Linux ru_maxrss including native OpenCV allocations",
        },
        "limitations": [
            "A plausible homography is correspondence evidence, never proof of duplicate identity.",
            "Natural negatives use Copydays identity and nearest-pHash hard-pair selection.",
            "The held-out Strong identities were previously observed in Experiment 03 reporting.",
            "Final and calibration databases use disjoint halves of the available distractors; "
            "each is smaller than the Experiment 03 target database.",
            "Threshold search is small; Wilson intervals do not model identity clustering.",
            "ORB exhaustive matching cost is not representative of an indexed production system.",
        ],
        "source_integrity": {
            "algorithm": "sha256",
            "before": {str(path): sha256_file(path) for path in source_paths},
        },
        "review_record": {
            "implementation_review": [
                "configuration values reach homography plausibility checks",
                "mutual confirmation has one implementation",
                "evidence cache key covers all evidence-changing configuration",
                "calibration and evaluation query identities and distractors are disjoint",
                "legacy Experiment 03 baseline retained as exploratory evidence",
            ],
            "dataset_counts": {
                "originals": len(originals),
                "strong_queries_total": len(queries),
                "distractors_total": len(distractors),
            },
            "seeds": {"partition_and_opencv": SEED},
        },
        "_local_samples": samples,
    }


def verify_source_integrity(result: dict[str, Any]) -> bool:
    return all(
        Path(path).is_file() and sha256_file(Path(path)) == digest
        for path, digest in result["source_integrity"]["before"].items()
    )


def write_reports(result: dict[str, Any], output: Path) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    samples = result.pop("_local_samples")
    result["source_integrity"]["verified_after"] = verify_source_integrity(result)
    json_path = output / "experiment-04.json"
    csv_path = output / "experiment-04-queries.csv"
    html_path = output / "experiment-04-summary.html"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        rows = result["evaluation"]["rows"]
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {key: value for key, value in result.items() if key not in {"source_integrity"}}
    summary["evaluation"] = {
        key: value for key, value in result["evaluation"].items() if key != "rows"
    }
    html_path.write_text(
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
        "<title>Experimento 04 — Verificação Geométrica</title>"
        "<style>body{font:15px system-ui;max-width:1200px;margin:auto;padding:2rem}"
        "pre{white-space:pre-wrap;background:#f4f4f4;padding:1rem}</style>"
        "<h1>Experimento 04 — Verificação Geométrica</h1>"
        "<p>Relatório local resumido; nenhuma fotografia está incorporada.</p><pre>"
        + html.escape(json.dumps(summary, indent=2, ensure_ascii=False))
        + "</pre></html>",
        encoding="utf-8",
    )
    _write_contact_sheets(samples, output / "local-visualizations")
    return json_path, csv_path, html_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("distractor_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = run_experiment(args.dataset_root, args.distractor_root, smoke=args.smoke)
    write_reports(result, args.output)


if __name__ == "__main__":
    main()
