"""Benchmark 02: Copydays Strong, controlled distractors, and negative queries."""

from __future__ import annotations

import csv
import html
import json
import resource
import time
import tracemalloc
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from duplicate_lab.benchmark_copydays import GROUND_TRUTH_SOURCE, _display_path, _jpgs
from duplicate_lab.hashing import oriented_phashes, sha256_file
from duplicate_lab.similarity import ROTATIONS, classify_visual, structural_metrics

STRONG_URL = "https://dl.fbaipublicfiles.com/vissl/datasets/copydays_strong.tar.gz"
STRONG_SHA256 = "7852c64aa4a37e8329ce08159fc947c16f09c66737db0a2479a90fc9ae40760c"
DEFAULT_PHASH_THRESHOLD = 8
ANALYSIS_PHASH_THRESHOLDS = (0, 4, 8, 12, 16)


@dataclass(frozen=True)
class StrongEntry:
    query: Path
    original: Path
    capture_id: str


def build_strong_manifest(dataset_root: Path) -> tuple[StrongEntry, ...]:
    """Apply the four-character rule used by the public DINO and SSCD evaluators."""
    root = dataset_root.resolve()
    originals = _jpgs(root / "original")
    strong = _jpgs(root / "strong")
    if len(originals) != 157 or len(strong) != 229:
        raise ValueError(
            f"Copydays incompleto: originals={len(originals)} (esperado 157), "
            f"strong={len(strong)} (esperado 229)"
        )
    by_prefix: dict[str, list[Path]] = {}
    for original in originals:
        by_prefix.setdefault(original.name[:4], []).append(original)
    entries = []
    for query in strong:
        matches = by_prefix.get(query.name[:4], [])
        if len(matches) != 1:
            raise ValueError(
                f"Ground truth Strong ambíguo para {query.name}: {len(matches)} originais"
            )
        entries.append(StrongEntry(query, matches[0], query.name[:4]))
    return tuple(entries)


def generate_controlled_negatives(
    destination: Path, *, count: int, namespace: str, side: int = 192
) -> tuple[Path, ...]:
    """Create deterministic non-photographic images with disjoint named namespaces."""
    destination.mkdir(parents=True, exist_ok=True)
    expected = {f"{namespace}-{index:04d}.png" for index in range(count)}
    existing = {path.name for path in destination.glob("*.png")}
    if existing and existing != expected:
        raise ValueError(f"Conjunto sintético inesperado em {destination}")
    for index in range(count):
        target = destination / f"{namespace}-{index:04d}.png"
        if target.exists():
            continue
        seed = index + sum((i + 1) * ord(c) for i, c in enumerate(namespace))
        image = Image.new("RGB", (side, side), _color(seed, 0))
        draw = ImageDraw.Draw(image)
        bands = max(2, min(12, (side - 12) // 14))
        for band in range(bands):
            inset = 3 + band * 7
            color = _color(seed, band + 1)
            if (seed + band) % 3 == 0:
                draw.rectangle(
                    (inset, inset, side - inset - 1, side - inset - 1), outline=color, width=3
                )
            elif (seed + band) % 3 == 1:
                draw.ellipse(
                    (inset, inset, side - inset - 1, side - inset - 1), outline=color, width=3
                )
            else:
                draw.line((inset, side - inset, side - inset, inset), fill=color, width=4)
        draw.polygon(
            [
                (side // 2, 10 + seed % 25),
                (side - 15 - seed % 31, side - 20),
                (12 + seed % 37, side - 25 - seed % 17),
            ],
            outline=_color(seed, 31),
            width=5,
        )
        image.save(target, format="PNG", optimize=False)
    return tuple(sorted(destination.glob("*.png"), key=lambda path: path.name))


def _color(seed: int, channel: int) -> tuple[int, int, int]:
    value = (seed * 1103515245 + channel * 2654435761 + 12345) & 0xFFFFFFFF
    return (32 + value % 192, 32 + (value >> 8) % 192, 32 + (value >> 16) % 192)


def validate_negative_sets(
    copydays: Iterable[Path], distractors: Iterable[Path], negative_queries: Iterable[Path]
) -> dict[str, Any]:
    groups = {
        "copydays": tuple(copydays),
        "distractors": tuple(distractors),
        "negative_queries": tuple(negative_queries),
    }
    hashes = {name: {sha256_file(path): path for path in paths} for name, paths in groups.items()}
    collisions = []
    for left, right in (
        ("copydays", "distractors"),
        ("copydays", "negative_queries"),
        ("distractors", "negative_queries"),
    ):
        for digest in sorted(hashes[left].keys() & hashes[right].keys()):
            collisions.append([str(hashes[left][digest]), str(hashes[right][digest])])
    if collisions:
        raise ValueError(f"Colisões exatas entre conjuntos negativos: {collisions[:3]}")
    return {
        "classification": "verified",
        "basis": (
            "locally generated deterministic non-photographic images; disjoint namespaces; "
            "no SHA-256 collision with Copydays originals/Strong or between negative sets"
        ),
        "counts": {name: len(paths) for name, paths in groups.items()},
        "exact_collisions": 0,
        "presumed_negatives": 0,
        "ambiguous": 0,
    }


def _rss_bytes() -> int:
    # Linux ru_maxrss is KiB; this benchmark targets the declared Linux environment.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _evaluate(
    *,
    name: str,
    queries: tuple[Path, ...],
    database: tuple[Path, ...],
    expected: dict[Path, Path],
    root: Path,
    comparison_side: int,
    analysis_limit: int = max(ANALYSIS_PHASH_THRESHOLDS),
) -> dict[str, Any]:
    started = time.perf_counter()
    rss_before = _rss_bytes()
    tracemalloc.start()
    hashing_seconds = 0.0
    comparison_seconds = 0.0
    structural_seconds = 0.0
    hash_started = time.perf_counter()
    database_hashes = {path: oriented_phashes(path) for path in database}
    hashing_seconds += time.perf_counter() - hash_started
    rows: list[dict[str, Any]] = []
    for query in queries:
        hash_started = time.perf_counter()
        query_hash = oriented_phashes(query)[0]
        hashing_seconds += time.perf_counter() - hash_started
        comparison_started = time.perf_counter()
        ranked = []
        for candidate, hashes in database_hashes.items():
            distances = [int(query_hash - value) for value in hashes]
            distance = min(distances)
            ranked.append((distance, candidate.name, candidate, distances.index(distance)))
        ranked.sort(key=lambda item: (item[0], item[1], str(item[2])))
        comparison_seconds += time.perf_counter() - comparison_started
        truth = expected.get(query)
        row: dict[str, Any] = {
            "scenario": name,
            "query": _display_path(query, root),
            "expected_original": _display_path(truth, root) if truth else None,
            "expected_rank": None,
            "top_1": _display_path(ranked[0][2], root),
            "top_1_distance": ranked[0][0],
            "expected_distance": None,
            "expected_is_candidate": False,
            "expected_is_confirmed": False,
            "candidate_count": 0,
            "confirmed_count": 0,
            "incorrect_confirmed": [],
            "pairs_within_analysis_limit": [],
            "error": None,
        }
        for rank, (distance, _, candidate, rotation_index) in enumerate(ranked, 1):
            if candidate == truth:
                row["expected_rank"] = rank
                row["expected_distance"] = distance
            if distance > analysis_limit:
                continue
            structural_started = time.perf_counter()
            try:
                ssim, mae = structural_metrics(
                    query, candidate, ROTATIONS[rotation_index], comparison_side
                )
            except (OSError, ValueError) as exc:
                row["error"] = str(exc)
                continue
            structural_seconds += time.perf_counter() - structural_started
            pair = {
                "path": _display_path(candidate, root),
                "distance": distance,
                "is_expected": candidate == truth,
                "ssim": ssim,
                "mae": mae,
                "default_confirmed": classify_visual(ssim, mae) == "similar_image",
            }
            row["pairs_within_analysis_limit"].append(pair)
            if distance <= DEFAULT_PHASH_THRESHOLD:
                row["candidate_count"] += 1
                row["expected_is_candidate"] |= candidate == truth
                if pair["default_confirmed"]:
                    row["confirmed_count"] += 1
                    row["expected_is_confirmed"] |= candidate == truth
                    if candidate != truth:
                        row["incorrect_confirmed"].append(pair["path"])
        rows.append(row)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    total = time.perf_counter() - started
    return {
        "name": name,
        "queries": rows,
        "counts": {
            "database": len(database),
            "queries": len(queries),
            "comparisons": len(database) * len(queries),
            "structural_comparisons": sum(len(row["pairs_within_analysis_limit"]) for row in rows),
        },
        "timing": {
            "hashing_seconds": hashing_seconds,
            "phash_comparison_seconds": comparison_seconds,
            "structural_seconds": structural_seconds,
            "total_seconds": total,
            "mean_seconds_per_query": total / len(queries) if queries else None,
        },
        "memory": {
            "rss_peak_bytes": _rss_bytes(),
            "rss_before_bytes": rss_before,
            "python_current_bytes": current,
            "python_peak_bytes": peak,
            "rss_scope": (
                "process ru_maxrss, including native allocations; lifetime high-water mark"
            ),
            "python_scope": "tracemalloc Python allocations during this scenario",
        },
        "metrics": scenario_metrics(rows),
    }


def scenario_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row["expected_original"] and not row["error"]]
    negatives = [row for row in rows if not row["expected_original"] and not row["error"]]
    predicted_pairs = sum(row["confirmed_count"] for row in rows)
    true_pairs = sum(row["expected_is_confirmed"] for row in positives)
    false_pairs = predicted_pairs - true_pairs
    metrics: dict[str, Any] = {
        "positive_queries": len(positives),
        "negative_queries": len(negatives),
        "confirmed_pairs": predicted_pairs,
        "true_confirmed_pairs": true_pairs,
        "false_confirmed_pairs": false_pairs,
        "pair_precision": true_pairs / predicted_pairs if predicted_pairs else None,
        "pair_recall": true_pairs / len(positives) if positives else None,
        "false_negatives": len(positives) - true_pairs,
        "decode_failures": sum(bool(row["error"]) for row in rows),
    }
    if positives:
        metrics.update(
            {
                f"recall_at_{k}": sum(
                    row["expected_rank"] is not None and row["expected_rank"] <= k
                    for row in positives
                )
                / len(positives)
                for k in (1, 5, 10)
            }
        )
        metrics["mrr"] = sum(
            1 / row["expected_rank"] for row in positives if row["expected_rank"]
        ) / len(positives)
        metrics["candidate_recall"] = sum(row["expected_is_candidate"] for row in positives) / len(
            positives
        )
    if negatives:
        accepted = sum(row["confirmed_count"] > 0 for row in negatives)
        metrics.update(
            {
                "negative_queries_with_false_confirmation": accepted,
                "false_match_rate": accepted / len(negatives),
                "false_positive_rate": accepted / len(negatives),
                "false_acceptance_rate": accepted / len(negatives),
                "definition": (
                    "query-level: a negative query is accepted if any database pair is confirmed"
                ),
            }
        )
    return metrics


def threshold_tradeoffs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for threshold in ANALYSIS_PHASH_THRESHOLDS:
        tp = fp = 0
        positives = sum(bool(row["expected_original"]) for row in rows)
        negative_queries = [row for row in rows if not row["expected_original"]]
        negative_accepts = 0
        for row in rows:
            accepted = False
            for pair in row["pairs_within_analysis_limit"]:
                confirmed = pair["distance"] <= threshold and pair["default_confirmed"]
                tp += bool(confirmed and pair["is_expected"])
                fp += bool(confirmed and not pair["is_expected"])
                accepted |= bool(confirmed and not row["expected_original"])
            negative_accepts += accepted
        result.append(
            {
                "phash_threshold": threshold,
                "ssim_threshold": 0.80,
                "mae_threshold": 0.10,
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": positives - tp,
                "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / positives if positives else None,
                "false_negative_rate": (positives - tp) / positives if positives else None,
                "false_positive_rate": negative_accepts / len(negative_queries)
                if negative_queries
                else None,
            }
        )
    return result


def confirmation_tradeoffs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe confirmation sensitivity while keeping the production pHash cutoff fixed."""
    result = []
    positives = sum(bool(row["expected_original"]) for row in rows)
    negative_queries = [row for row in rows if not row["expected_original"]]
    for ssim_threshold, mae_threshold in ((0.75, 0.15), (0.80, 0.10), (0.85, 0.05)):
        tp = fp = negative_accepts = 0
        for row in rows:
            accepted = False
            for pair in row["pairs_within_analysis_limit"]:
                confirmed = (
                    pair["distance"] <= DEFAULT_PHASH_THRESHOLD
                    and pair["ssim"] >= ssim_threshold
                    and pair["mae"] <= mae_threshold
                )
                tp += bool(confirmed and pair["is_expected"])
                fp += bool(confirmed and not pair["is_expected"])
                accepted |= bool(confirmed and not row["expected_original"])
            negative_accepts += accepted
        result.append(
            {
                "phash_threshold": DEFAULT_PHASH_THRESHOLD,
                "ssim_threshold": ssim_threshold,
                "mae_threshold": mae_threshold,
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": positives - tp,
                "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / positives if positives else None,
                "false_negative_rate": (positives - tp) / positives if positives else None,
                "false_positive_rate": negative_accepts / len(negative_queries)
                if negative_queries
                else None,
            }
        )
    return result


def run_strong_benchmark(
    dataset_root: Path,
    distractor_root: Path,
    *,
    baseline_path: Path | None = None,
    comparison_side: int = 512,
    max_queries: int | None = None,
) -> dict[str, Any]:
    root = dataset_root.resolve()
    manifest = build_strong_manifest(root)
    if max_queries is not None:
        manifest = manifest[:max_queries]
    distractors = tuple(sorted((distractor_root / "database").glob("*.png")))
    negatives = tuple(sorted((distractor_root / "queries").glob("*.png")))
    originals = _jpgs(root / "original")
    strong = tuple(entry.query for entry in manifest)
    expected = {entry.query: entry.original for entry in manifest}
    validation = validate_negative_sets((*originals, *strong), distractors, negatives)
    scenario_a = _evaluate(
        name="A",
        queries=strong,
        database=originals,
        expected=expected,
        root=root,
        comparison_side=comparison_side,
    )
    scenario_b = _evaluate(
        name="B",
        queries=strong,
        database=(*originals, *distractors),
        expected=expected,
        root=root,
        comparison_side=comparison_side,
    )
    scenario_c = _evaluate(
        name="C",
        queries=negatives,
        database=originals,
        expected={},
        root=root,
        comparison_side=comparison_side,
    )
    all_rows = scenario_b["queries"] + scenario_c["queries"]
    baseline = None
    if baseline_path and baseline_path.exists():
        prior = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline = {
            "counts": prior["counts"],
            "metrics": prior["metrics"],
            "timing": prior["timing"],
        }
    represented = len({entry.original for entry in manifest})
    return {
        "schema_version": 2,
        "dataset": {
            "strong_url": STRONG_URL,
            "strong_archive_size_bytes": 62884651,
            "strong_sha256": STRONG_SHA256,
            "originals": len(originals),
            "strong_queries": len(strong),
            "represented_originals": represented,
            "distractors": len(distractors),
            "negative_queries": len(negatives),
        },
        "ground_truth": {
            "rule": (
                "unique original whose first four filename characters equal the Strong query prefix"
            ),
            "source": GROUND_TRUTH_SOURCE,
            "references": [
                "https://github.com/facebookresearch/dino/blob/main/eval_copy_detection.py",
                "https://github.com/facebookresearch/sscd-copy-detection/blob/main/sscd/datasets/copydays.py",
            ],
            "ambiguous_rejected": True,
        },
        "negative_validation": validation,
        "configuration": {
            "production_defaults_unchanged": True,
            "phash_threshold": DEFAULT_PHASH_THRESHOLD,
            "ssim_threshold": 0.80,
            "mae_threshold": 0.10,
            "comparison_side": comparison_side,
            "max_queries": max_queries,
        },
        "scenarios": {"A": scenario_a, "B": scenario_b, "C": scenario_c},
        "threshold_analysis": {
            "kind": (
                "offline sensitivity analysis; no threshold selected or production value changed"
            ),
            "evaluation_rows": "Scenario B positives plus disjoint Scenario C negative queries",
            "identity_leakage": (
                "no calibration performed; therefore no calibration/evaluation reuse"
            ),
            "phash_tradeoffs": threshold_tradeoffs(all_rows),
            "confirmation_tradeoffs": confirmation_tradeoffs(all_rows),
        },
        "benchmark_01": baseline,
        "limitations": [
            "Strong geometric/photometric transformations are materially harder than Scale+JPEG.",
            (
                "Controlled negatives are synthetic geometric images, not representative "
                "natural-photo distractors."
            ),
            (
                "Verified-negative status is by deterministic construction and exact-collision "
                "checks; semantic exhaustiveness is impossible."
            ),
            (
                "ru_maxrss is a process-lifetime high-water mark and can include allocations "
                "before each scenario."
            ),
            (
                "Threshold analysis is descriptive only; an independent natural-image "
                "calibration set is required before changing defaults."
            ),
        ],
    }


def _number(value: Any) -> str:
    return "—" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)


def _render_html(result: dict[str, Any], example_limit: int = 10) -> str:
    scenarios = result["scenarios"]
    metrics_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(_number(value))}</td>"
            for value in (
                name,
                data["counts"]["database"],
                data["counts"]["queries"],
                data["metrics"].get("recall_at_1"),
                data["metrics"].get("recall_at_5"),
                data["metrics"].get("mrr"),
                data["metrics"].get("pair_precision"),
                data["metrics"].get("pair_recall"),
                data["metrics"].get("false_positive_rate"),
            )
        )
        + "</tr>"
        for name, data in scenarios.items()
    )
    trade_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(_number(row[key]))}</td>"
            for key in (
                "phash_threshold",
                "precision",
                "recall",
                "false_positive_rate",
                "false_negative_rate",
            )
        )
        + "</tr>"
        for row in (
            result["threshold_analysis"]["phash_tradeoffs"]
            + result["threshold_analysis"]["confirmation_tradeoffs"]
        )
    )

    def samples(predicate: Any) -> str:
        rows = [
            row for scenario in scenarios.values() for row in scenario["queries"] if predicate(row)
        ]
        return (
            "".join(
                "<tr>"
                f"<td>{html.escape(row['scenario'])}</td>"
                f"<td>{html.escape(row['query'])}</td>"
                f"<td>{html.escape(str(row['top_1']))}</td>"
                f"<td>{html.escape(str(row['expected_rank']))}</td>"
                "</tr>"
                for row in sorted(rows, key=lambda row: (row["scenario"], row["query"]))[
                    :example_limit
                ]
            )
            or "<tr><td colspan='4'>Nenhum caso.</td></tr>"
        )

    baseline = result.get("benchmark_01")
    baseline_text = (
        html.escape(json.dumps(baseline, indent=2, ensure_ascii=False))
        if baseline
        else "Indisponível"
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in result["limitations"])
    hits = samples(lambda row: row["expected_rank"] == 1 and row["expected_is_confirmed"])
    false_positives = samples(lambda row: bool(row["incorrect_confirmed"]))
    false_negatives = samples(
        lambda row: bool(row["expected_original"]) and not row["expected_is_confirmed"]
    )
    return (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<title>Copydays Strong benchmark</title><style>"
        "body{font:15px system-ui;max-width:1200px;margin:auto;padding:2rem}"
        "table{width:100%;border-collapse:collapse;margin:1rem 0}"
        "th,td{border:1px solid #bbb;padding:.45rem;text-align:left;overflow-wrap:anywhere}"
        "pre{background:#f5f5f3;padding:1rem;overflow:auto}</style></head><body>"
        "<h1>PlayMemories Duplicate Lab — Benchmark 02</h1>"
        "<p>Copydays Strong, distractores controlados e consultas negativas. "
        "Sem imagens incorporadas.</p><h2>Métricas por cenário</h2><table>"
        "<tr><th>Cenário</th><th>Base</th><th>Consultas</th><th>R@1</th>"
        "<th>R@5</th><th>MRR</th><th>Precisão confirmação</th>"
        "<th>Recall confirmação</th><th>FPR</th></tr>"
        f"{metrics_rows}</table><h2>Benchmark 01 (Scale+JPEG)</h2>"
        "<p>A comparação é contextual: Scale+JPEG contém compressão/escala; "
        "Strong inclui transformações muito mais agressivas.</p>"
        f"<pre>{baseline_text}</pre><h2>Trade-offs offline</h2><table>"
        "<tr><th>pHash</th><th>Precisão</th><th>Recall</th><th>FPR</th>"
        f"<th>FNR</th></tr>{trade_rows}</table><h2>Amostra de acertos</h2>"
        f"<table>{hits}</table><h2>Amostra de falsos positivos</h2>"
        f"<table>{false_positives}</table><h2>Amostra de falsos negativos</h2>"
        f"<table>{false_negatives}</table><h2>Limitações</h2>"
        f"<ul>{limitations}</ul></body></html>"
    )


def write_strong_reports(
    result: dict[str, Any], output_dir: Path, *, overwrite: bool = False
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = (
        output_dir / "benchmark-02.json",
        output_dir / "benchmark-02-queries.csv",
        output_dir / "benchmark-02-summary.html",
    )
    if not overwrite and any(path.exists() for path in targets):
        raise FileExistsError("Relatório Benchmark 02 já existe")
    mode = "w" if overwrite else "x"
    targets[0].write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = [row for scenario in result["scenarios"].values() for row in scenario["queries"]]
    fields = [
        key for key in rows[0] if key not in {"incorrect_confirmed", "pairs_within_analysis_limit"}
    ]
    fields.extend(("incorrect_confirmed", "pairs_within_analysis_limit"))
    with targets[1].open(mode, encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "incorrect_confirmed": ";".join(row["incorrect_confirmed"]),
                    "pairs_within_analysis_limit": json.dumps(
                        row["pairs_within_analysis_limit"], separators=(",", ":")
                    ),
                }
            )
    targets[2].write_text(_render_html(result), encoding="utf-8")
    return targets
