"""Experiment 03: pHash baseline, ORB+RANSAC, and candidate-union evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import resource
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from duplicate_lab.benchmark_copydays import _display_path, _jpgs, build_manifest
from duplicate_lab.benchmark_strong import build_strong_manifest
from duplicate_lab.experiments.local_features import (
    Features,
    ORBConfig,
    extract_features,
    match_features,
)
from duplicate_lab.hashing import oriented_phashes, sha256_file
from duplicate_lab.similarity import ROTATIONS, classify_visual, structural_metrics

SEED = 202503
CALIBRATION_FRACTION = 0.30
PHASH_THRESHOLD = 8
TOP_K_CANDIDATES = 10


def identity_partition(capture_id: str, seed: int = SEED) -> str:
    value = int.from_bytes(hashlib.sha256(f"{seed}:{capture_id}".encode()).digest()[:8], "big")
    return "calibration" if value / 2**64 < CALIBRATION_FRACTION else "test"


def retrieval_metrics(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    positives = [row for row in rows if row["expected_original"] is not None and not row["error"]]
    negatives = [row for row in rows if row["expected_original"] is None and not row["error"]]
    prefix = method + "_"
    confirmed = sum(row[prefix + "confirmed_count"] for row in rows)
    true_positive = sum(row[prefix + "expected_confirmed"] for row in positives)
    false_positive = confirmed - true_positive
    negative_accepts = sum(row[prefix + "confirmed_count"] > 0 for row in negatives)
    denominator = len(positives)
    result = {
        "positive_queries": denominator,
        "negative_queries": len(negatives),
        "true_positives": true_positive,
        "false_positives": false_positive,
        "false_negatives": denominator - true_positive,
        "precision": true_positive / confirmed if confirmed else None,
        "recall": true_positive / denominator if denominator else None,
        "candidate_recall": (
            sum(row[prefix + "expected_candidate"] for row in positives) / denominator
            if denominator
            else None
        ),
        "negative_queries_accepted": negative_accepts,
        "false_positive_rate": negative_accepts / len(negatives) if negatives else None,
        "false_positive_rate_denominator": "negative queries; accepted when >=1 pair confirms",
    }
    for k in (1, 5, 10):
        result[f"recall_at_{k}"] = (
            sum(row[prefix + "rank"] is not None and row[prefix + "rank"] <= k for row in positives)
            / denominator
            if denominator
            else None
        )
    result["mrr"] = (
        sum(1 / row[prefix + "rank"] for row in positives if row[prefix + "rank"]) / denominator
        if denominator
        else None
    )
    return result


def _rss() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _extract(paths: tuple[Path, ...], config: ORBConfig) -> tuple[dict[Path, Features], float]:
    started = time.perf_counter()
    result = {path: extract_features(path, config) for path in paths}
    return result, time.perf_counter() - started


def _evaluate(
    name: str,
    queries: tuple[Path, ...],
    database: tuple[Path, ...],
    expected: dict[Path, Path],
    capture_ids: dict[Path, str],
    root: Path,
    config: ORBConfig,
    partition: str,
) -> dict[str, Any]:
    chosen = (
        queries
        if partition == "all"
        else tuple(q for q in queries if identity_partition(capture_ids[q]) == partition)
    )
    started = time.perf_counter()
    rss_before = _rss()
    all_paths = tuple(dict.fromkeys((*database, *chosen)))
    features, extraction_seconds = _extract(all_paths, config)
    descriptor_total = sum(
        0 if item.descriptors is None else len(item.descriptors) for item in features.values()
    )
    hash_started = time.perf_counter()
    hashes = {path: oriented_phashes(path) for path in all_paths}
    hashing_seconds = time.perf_counter() - hash_started
    rows: list[dict[str, Any]] = []
    matching_seconds = ransac_seconds = structural_seconds = 0.0
    geometric_examples: list[dict[str, Any]] = []
    for query in chosen:
        truth = expected.get(query)
        query_hash = hashes[query][0]
        phash_pairs = []
        orb_pairs = []
        for candidate in database:
            distances = [int(query_hash - value) for value in hashes[candidate]]
            distance = min(distances)
            rotation = distances.index(distance)
            phash_pairs.append((distance, candidate.name, candidate, rotation))
            matched = match_features(features[query], features[candidate], config)
            matching_seconds += matched.matching_seconds
            ransac_seconds += matched.ransac_seconds
            orb_pairs.append((matched.score, candidate.name, candidate, matched))
        phash_pairs.sort(key=lambda item: (item[0], item[1], str(item[2])))
        orb_pairs.sort(key=lambda item: (item[0], item[1], str(item[2])), reverse=True)
        # Restore ascending lexical tie-break while retaining descending score.
        orb_pairs = sorted(orb_pairs, key=lambda item: item[1])
        orb_pairs = sorted(orb_pairs, key=lambda item: item[0], reverse=True)
        phash_candidates = {item[2] for item in phash_pairs if item[0] <= PHASH_THRESHOLD}
        orb_candidates = {item[2] for item in orb_pairs[:TOP_K_CANDIDATES]}
        orb_confirmed = {item[2] for item in orb_pairs if item[3].confirmed}
        baseline_confirmed: set[Path] = set()
        for distance, _, candidate, rotation in phash_pairs:
            if distance > PHASH_THRESHOLD:
                break
            structural_started = time.perf_counter()
            ssim, mae = structural_metrics(query, candidate, ROTATIONS[rotation], 512)
            structural_seconds += time.perf_counter() - structural_started
            if classify_visual(ssim, mae) == "similar_image":
                baseline_confirmed.add(candidate)
        combined_candidates = phash_candidates | orb_candidates
        combined_confirmed = baseline_confirmed | (orb_confirmed & combined_candidates)
        phash_rank = next((i for i, item in enumerate(phash_pairs, 1) if item[2] == truth), None)
        orb_rank = next((i for i, item in enumerate(orb_pairs, 1) if item[2] == truth), None)
        union_ranked = sorted(
            combined_candidates,
            key=lambda path: (
                min(i for i, item in enumerate(phash_pairs, 1) if item[2] == path),
                min(i for i, item in enumerate(orb_pairs, 1) if item[2] == path),
                path.name,
            ),
        )
        union_rank = union_ranked.index(truth) + 1 if truth in union_ranked else None
        error = features[query].error
        row = {
            "scenario": name,
            "partition": partition,
            "query": _display_path(query, root),
            "expected_original": _display_path(truth, root) if truth else None,
            "phash_rank": phash_rank,
            "phash_expected_candidate": truth in phash_candidates if truth else False,
            "phash_expected_confirmed": truth in baseline_confirmed if truth else False,
            "phash_confirmed_count": len(baseline_confirmed),
            "orb_rank": orb_rank,
            "orb_expected_candidate": truth in orb_candidates if truth else False,
            "orb_expected_confirmed": truth in orb_confirmed if truth else False,
            "orb_confirmed_count": len(orb_confirmed),
            "combined_rank": union_rank,
            "combined_expected_candidate": truth in combined_candidates if truth else False,
            "combined_expected_confirmed": truth in combined_confirmed if truth else False,
            "combined_confirmed_count": len(combined_confirmed),
            "orb_filtered_matches_expected": None,
            "orb_inliers_expected": None,
            "orb_inlier_ratio_expected": None,
            "orb_reprojection_error_expected": None,
            "error": error,
        }
        if truth:
            result = next(item[3] for item in orb_pairs if item[2] == truth)
            row.update(
                {
                    "orb_filtered_matches_expected": result.filtered_matches,
                    "orb_inliers_expected": result.inliers,
                    "orb_inlier_ratio_expected": result.inlier_ratio,
                    "orb_reprojection_error_expected": result.reprojection_error,
                }
            )
        for _, _, candidate, result in orb_pairs:
            if result.confirmed and len(geometric_examples) < 30:
                geometric_examples.append(
                    {
                        "query": _display_path(query, root),
                        "candidate": _display_path(candidate, root),
                        "is_expected": candidate == truth,
                        **asdict(result),
                    }
                )
        rows.append(row)
    return {
        "name": name,
        "partition": partition,
        "rows": rows,
        "metrics": {
            method: retrieval_metrics(rows, method) for method in ("phash", "orb", "combined")
        },
        "counts": {
            "queries": len(chosen),
            "database": len(database),
            "comparisons": len(chosen) * len(database),
            "descriptors": descriptor_total,
        },
        "timing": {
            "extraction_seconds": extraction_seconds,
            "hashing_seconds": hashing_seconds,
            "matching_seconds": matching_seconds,
            "ransac_seconds": ransac_seconds,
            "structural_seconds": structural_seconds,
            "total_seconds": time.perf_counter() - started,
        },
        "memory": {
            "rss_before_bytes": rss_before,
            "rss_peak_bytes": _rss(),
            "scope": "process-lifetime ru_maxrss; includes native OpenCV allocations",
        },
        "geometric_examples": geometric_examples,
    }


def calibration_configs() -> tuple[ORBConfig, ...]:
    return (
        ORBConfig(),
        ORBConfig(nfeatures=1800, fast_threshold=12),
        ORBConfig(nfeatures=1200, ratio_threshold=0.80, min_inlier_ratio=0.40),
    )


def run_experiment(dataset_root: Path, distractor_root: Path) -> dict[str, Any]:
    root = dataset_root.resolve()
    originals = _jpgs(root / "original")
    scale_manifest = build_manifest(root)
    strong_manifest = build_strong_manifest(root)
    distractors = tuple(sorted((distractor_root / "database").glob("*.png")))
    negatives = tuple(sorted((distractor_root / "queries").glob("*.png")))
    strong_queries = tuple(item.query for item in strong_manifest)
    strong_expected = {item.query: item.original for item in strong_manifest}
    strong_ids = {item.query: item.capture_id for item in strong_manifest}
    # Negative identities are stable and separately partitioned, with no ground truth match.
    negative_ids = {path: "negative:" + path.stem for path in negatives}
    calibration = []
    for config in calibration_configs():
        evaluated = _evaluate(
            "strong",
            strong_queries,
            originals,
            strong_expected,
            strong_ids,
            root,
            config,
            "calibration",
        )
        score = evaluated["metrics"]["orb"]["recall"] or 0.0
        calibration.append(
            {
                "config": config.to_dict(),
                "score": score,
                "metrics": evaluated["metrics"]["orb"],
                "timing": evaluated["timing"],
            }
        )
    # Selection criterion fixed before test inspection: confirmation recall, then precision,
    # then lower total cost, then configuration order.
    selected_index = max(
        range(len(calibration)),
        key=lambda i: (
            calibration[i]["score"],
            calibration[i]["metrics"]["precision"] or 0.0,
            -calibration[i]["timing"]["total_seconds"],
            -i,
        ),
    )
    selected = calibration_configs()[selected_index]
    scale_queries = tuple(item.query for item in scale_manifest)
    scale_expected = {item.query: item.original for item in scale_manifest}
    scale_ids = {item.query: item.capture_id for item in scale_manifest}
    scenarios = {
        "scale_jpeg_test": _evaluate(
            "scale_jpeg",
            scale_queries,
            originals,
            scale_expected,
            scale_ids,
            root,
            selected,
            "test",
        ),
        "strong_test": _evaluate(
            "strong", strong_queries, originals, strong_expected, strong_ids, root, selected, "test"
        ),
        "strong_distractors_test": _evaluate(
            "strong_distractors",
            strong_queries,
            (*originals, *distractors),
            strong_expected,
            strong_ids,
            root,
            selected,
            "test",
        ),
        "negative_test": _evaluate(
            "negative", negatives, originals, {}, negative_ids, root, selected, "all"
        ),
    }
    source_hashes = {
        str(path): sha256_file(path)
        for path in (*originals, *scale_queries, *strong_queries, *distractors, *negatives)
    }
    return {
        "schema_version": 1,
        "experiment": "03-local-features",
        "seed": SEED,
        "partition": {
            "unit": "original identity",
            "calibration_fraction": CALIBRATION_FRACTION,
            "rule": "SHA-256(seed:capture_id) interpreted uniformly",
        },
        "configuration": {
            "selected_index": selected_index,
            "selected": selected.to_dict(),
            "phash_threshold_unchanged": PHASH_THRESHOLD,
            "orb_candidate_top_k": TOP_K_CANDIDATES,
            "combination": "union of pHash<=8 and ORB top-10 candidates; "
            "confirmation is existing SSIM/MAE OR valid ORB/RANSAC geometry",
        },
        "calibration": calibration,
        "scenarios": scenarios,
        "source_integrity": {"algorithm": "sha256", "before": source_hashes},
        "limitations": [
            "Architecture and base configuration were informed by prior benchmark knowledge; "
            "only controlled parameter selection is isolated by identity.",
            "Synthetic geometric negatives are not natural independent photographs.",
            "A valid homography is correspondence evidence, not proof of identical capture.",
            "ORB brute-force search is evaluated on the full eligible database without an index.",
        ],
    }


def verify_source_integrity(result: dict[str, Any]) -> bool:
    return all(
        Path(path).is_file() and sha256_file(Path(path)) == digest
        for path, digest in result["source_integrity"]["before"].items()
    )


def comparison_summary(result: dict[str, Any], limit: int = 20) -> dict[str, Any]:
    rows = [row for scenario in result["scenarios"].values() for row in scenario["rows"]]
    categories = {
        "recovered_by_orb_not_phash": [
            row
            for row in rows
            if row["orb_expected_confirmed"] and not row["phash_expected_confirmed"]
        ],
        "recovered_by_phash_not_orb": [
            row
            for row in rows
            if row["phash_expected_confirmed"] and not row["orb_expected_confirmed"]
        ],
        "missed_by_both": [
            row
            for row in rows
            if row["expected_original"]
            and not row["phash_expected_confirmed"]
            and not row["orb_expected_confirmed"]
        ],
        "orb_false_positive_queries": [
            row for row in rows if row["orb_confirmed_count"] > int(row["orb_expected_confirmed"])
        ],
        "combined_false_positive_queries": [
            row
            for row in rows
            if row["combined_confirmed_count"] > int(row["combined_expected_confirmed"])
        ],
    }
    return {
        name: {
            "count": len(items),
            "examples": [
                {
                    "scenario": row["scenario"],
                    "query": row["query"],
                    "expected_original": row["expected_original"],
                    "phash_rank": row["phash_rank"],
                    "orb_rank": row["orb_rank"],
                }
                for row in sorted(items, key=lambda item: (item["scenario"], item["query"]))[:limit]
            ],
        }
        for name, items in categories.items()
    }


def write_reports(result: dict[str, Any], output: Path) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    targets = (
        output / "experiment-03.json",
        output / "experiment-03-queries.csv",
        output / "experiment-03-summary.html",
    )
    if any(path.exists() for path in targets):
        raise FileExistsError("Experiment 03 report already exists")
    targets[0].write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = [row for scenario in result["scenarios"].values() for row in scenario["rows"]]
    with targets[1].open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = html.escape(
        json.dumps(
            {
                "configuration": result["configuration"],
                "calibration": result["calibration"],
                "scenarios": {
                    name: {
                        "counts": value["counts"],
                        "metrics": value["metrics"],
                        "timing": value["timing"],
                        "memory": value["memory"],
                    }
                    for name, value in result["scenarios"].items()
                },
                "comparison": result["comparison"],
                "limitations": result["limitations"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    targets[2].write_text(
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
        "<title>Experimento 03 — ORB + RANSAC</title><style>body{font:15px system-ui;"
        "max-width:1200px;margin:auto;padding:2rem}pre{white-space:pre-wrap;background:#f4f4f4;"
        "padding:1rem}</style><h1>Experimento 03 — ORB + RANSAC</h1>"
        "<p>Recuperação de candidatos e confirmação são métricas separadas. "
        "Nenhuma imagem integral está incorporada.</p><pre>" + summary + "</pre></html>",
        encoding="utf-8",
    )
    return targets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("distractor_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run_experiment(args.dataset_root, args.distractor_root)
    result["source_integrity"]["verified_after"] = verify_source_integrity(result)
    result["comparison"] = comparison_summary(result)
    write_reports(result, args.output)


if __name__ == "__main__":
    main()
