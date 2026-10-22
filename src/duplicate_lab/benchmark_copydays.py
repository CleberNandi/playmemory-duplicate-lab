"""Reproducible, read-only evaluation of the detector on INRIA Copydays."""

from __future__ import annotations

import csv
import html
import json
import tarfile
import time
import tracemalloc
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from duplicate_lab.hashing import oriented_phashes
from duplicate_lab.similarity import ROTATIONS, classify_visual, structural_metrics

JPEG_LEVELS = (3, 5, 8, 10, 15, 20, 30, 50, 75)
GROUND_TRUTH_SOURCE = (
    "INRIA layout and the reference Copydays evaluation implemented by DINO/SSCD: "
    "1:1 correspondence for jpegqual blocks; four-character capture prefix for strong"
)
DATASET_PROVENANCE = {
    "official_description": "https://thoth.inrialpes.fr/~jegou/data.php.html#copydays",
    "archives": [
        {
            "family": "original",
            "url": "https://dl.fbaipublicfiles.com/vissl/datasets/copydays_original.tar.gz",
            "size_bytes": 217895397,
            "sha256": "8b85b7914fd0145bc258bde3440f6a622243ca91ee085fe2025ce7bdeb0bfb8e",
        },
        {
            "family": "scale_jpeg",
            "url": (
                "https://web.archive.org/web/20181015092553if_/"
                "http://pascal.inrialpes.fr/data/holidays/copydays_jpeg.tar.gz"
            ),
            "size_bytes": 79726618,
            "sha256": "7abbf87c97b6d8a8044194ea5c34e98d76c6f37381d69ef9c2fbfa0ffaabc8bd",
        },
    ],
}


@dataclass(frozen=True)
class ManifestEntry:
    capture_id: str
    original: Path
    query: Path
    family: str
    parameter: str | None
    ground_truth_source: str = GROUND_TRUTH_SOURCE

    def to_dict(self, root: Path | None = None) -> dict[str, Any]:
        data = asdict(self)
        data["original"] = _display_path(self.original, root)
        data["query"] = _display_path(self.query, root)
        return data


def _display_path(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            pass
    return str(path)


def validate_tar_members(archive: Path) -> tuple[tarfile.TarInfo, ...]:
    """Reject absolute/traversing paths and all links before extraction."""
    with tarfile.open(archive, "r:gz") as bundle:
        members = tuple(bundle.getmembers())
    if not members:
        raise ValueError(f"Arquivo TAR vazio: {archive}")
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise ValueError(f"Caminho TAR inseguro: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError(f"Entrada TAR insegura: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"Tipo TAR não suportado: {member.name}")
    return members


def safe_extract_archive(archive: Path, destination: Path) -> None:
    """Extract a validated archive into a new, empty destination."""
    members = validate_tar_members(archive)
    if destination.exists():
        raise FileExistsError(f"Destino de extração já existe: {destination}")
    destination.mkdir(parents=True)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(destination, members=members, filter="data")
    except Exception:
        # Leave evidence in place rather than deleting or overwriting user data.
        raise


def _jpgs(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            (path.resolve() for path in directory.iterdir() if path.suffix.lower() == ".jpg"),
            key=lambda path: path.name,
        )
    )


def build_manifest(
    dataset_root: Path, *, include_strong: bool = False
) -> tuple[ManifestEntry, ...]:
    root = dataset_root.resolve()
    originals = _jpgs(root / "original")
    if not originals:
        raise ValueError(f"Nenhum original JPEG em {root / 'original'}")
    original_names = {path.name: path for path in originals}
    if len(original_names) != len(originals):
        raise ValueError("Nomes de originais duplicados")
    entries: list[ManifestEntry] = []
    seen_queries: set[Path] = set()
    jpeg_root = root / "jpegqual"
    if not jpeg_root.is_dir():
        jpeg_root = root / "scale-jpeg" / "jpegqual"
    present_levels = (
        {int(path.name) for path in jpeg_root.iterdir() if path.is_dir() and path.name.isdigit()}
        if jpeg_root.is_dir()
        else set()
    )
    if present_levels != set(JPEG_LEVELS):
        raise ValueError(
            f"Níveis jpegqual incompletos; esperados={list(JPEG_LEVELS)} "
            f"encontrados={sorted(present_levels)}"
        )
    for quality in JPEG_LEVELS:
        queries = _jpgs(jpeg_root / str(quality))
        query_names = {path.name for path in queries}
        if query_names != original_names.keys():
            missing = sorted(original_names.keys() - query_names)
            extra = sorted(query_names - original_names.keys())
            raise ValueError(
                f"Bloco jpegqual/{quality} incompleto; missing={missing[:3]} extra={extra[:3]}"
            )
        for query in queries:
            entries.append(
                ManifestEntry(
                    query.stem, original_names[query.name], query, "scale_jpeg", str(quality)
                )
            )
            seen_queries.add(query)
    if include_strong:
        by_prefix: dict[str, list[Path]] = defaultdict(list)
        for original in originals:
            by_prefix[original.name[:4]].append(original)
        for query in _jpgs(root / "strong"):
            matches = by_prefix[query.name[:4]]
            if len(matches) != 1:
                raise ValueError(
                    f"Ground truth Strong ambíguo para {query.name}: {len(matches)} originais"
                )
            entries.append(ManifestEntry(query.name[:4], matches[0], query, "strong", None))
            seen_queries.add(query)
    if len(seen_queries) != len(entries):
        raise ValueError("Uma consulta aparece mais de uma vez no manifesto")
    return tuple(entries)


def calculate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable = [row for row in rows if row["expected_original"] and not row["error"]]
    denominator = len(evaluable)

    def recall_at(k: int) -> float | None:
        return (
            sum(row["expected_rank"] is not None and row["expected_rank"] <= k for row in evaluable)
            / denominator
            if denominator
            else None
        )

    candidate_tp = sum(row["expected_is_candidate"] for row in evaluable)
    predicted = sum(row["confirmed_count"] for row in evaluable)
    pair_tp = sum(row["expected_is_confirmed"] for row in evaluable)
    pair_fp = predicted - pair_tp
    pair_fn = denominator - pair_tp
    return {
        "denominator": denominator,
        "recall_at_1": recall_at(1),
        "recall_at_5": recall_at(5),
        "recall_at_10": recall_at(10),
        "mrr": (
            sum(1 / row["expected_rank"] for row in evaluable if row["expected_rank"]) / denominator
            if denominator
            else None
        ),
        "candidate_recall": candidate_tp / denominator if denominator else None,
        "pair_precision": pair_tp / predicted if predicted else None,
        "pair_recall": pair_tp / denominator if denominator else None,
        "false_positives": pair_fp,
        "false_negatives": pair_fn,
        "decode_failures": sum(bool(row["error"]) for row in rows),
        "decode_failure_rate": sum(bool(row["error"]) for row in rows) / len(rows)
        if rows
        else None,
    }


def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = f"{row['family']}:{row['parameter'] or 'all'}"
        groups[key].append(row)
    return {key: calculate_metrics(value) for key, value in sorted(groups.items())}


def run_benchmark(
    dataset_root: Path,
    *,
    include_strong: bool = False,
    phash_threshold: int = 8,
    comparison_side: int = 512,
    max_queries: int | None = None,
) -> dict[str, Any]:
    root = dataset_root.resolve()
    manifest = build_manifest(root, include_strong=include_strong)
    if max_queries is not None:
        manifest = manifest[:max_queries]
    originals = tuple(sorted({entry.original for entry in manifest}, key=lambda path: path.name))
    started = time.perf_counter()
    tracemalloc.start()
    hash_started = time.perf_counter()
    original_hashes: dict[Path, tuple] = {}
    original_errors: dict[Path, str] = {}
    for original in originals:
        try:
            original_hashes[original] = oriented_phashes(original)
        except (OSError, ValueError) as exc:
            original_errors[original] = str(exc)
    rows: list[dict[str, Any]] = []
    hash_seconds = time.perf_counter() - hash_started
    structural_seconds = 0.0
    comparisons = 0
    structural_comparisons = 0
    for entry in manifest:
        row: dict[str, Any] = {
            **entry.to_dict(root),
            "expected_original": _display_path(entry.original, root),
            "expected_rank": None,
            "top_1": None,
            "top_1_distance": None,
            "expected_distance": None,
            "expected_is_candidate": False,
            "expected_is_confirmed": False,
            "candidate_count": 0,
            "confirmed_count": 0,
            "incorrect_confirmed": [],
            "error": None,
        }
        if entry.original in original_errors:
            row["error"] = f"original: {original_errors[entry.original]}"
            rows.append(row)
            continue
        query_hash_started = time.perf_counter()
        try:
            query_hash = oriented_phashes(entry.query)[0]
        except (OSError, ValueError) as exc:
            row["error"] = f"query: {exc}"
            rows.append(row)
            continue
        finally:
            hash_seconds += time.perf_counter() - query_hash_started
        ranked = []
        for original, hashes in original_hashes.items():
            distances = [int(query_hash - candidate) for candidate in hashes]
            ranked.append(
                (min(distances), original.name, original, distances.index(min(distances)))
            )
            comparisons += 1
        ranked.sort(key=lambda item: (item[0], item[1]))
        row["top_1"] = _display_path(ranked[0][2], root)
        row["top_1_distance"] = ranked[0][0]
        for rank, (distance, _, original, rotation_index) in enumerate(ranked, 1):
            if original == entry.original:
                row["expected_rank"] = rank
                row["expected_distance"] = distance
            if distance > phash_threshold:
                continue
            row["candidate_count"] += 1
            if original == entry.original:
                row["expected_is_candidate"] = True
            structural_started = time.perf_counter()
            try:
                ssim, mae = structural_metrics(
                    entry.query, original, ROTATIONS[rotation_index], comparison_side
                )
                confirmed = classify_visual(ssim, mae) == "similar_image"
            except (OSError, ValueError):
                confirmed = False
            structural_seconds += time.perf_counter() - structural_started
            structural_comparisons += 1
            if confirmed:
                row["confirmed_count"] += 1
                if original == entry.original:
                    row["expected_is_confirmed"] = True
                else:
                    row["incorrect_confirmed"].append(_display_path(original, root))
        rows.append(row)
    current_memory, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = time.perf_counter() - started
    metrics = calculate_metrics(rows)
    return {
        "schema_version": 1,
        "dataset_root": str(root),
        "dataset_provenance": DATASET_PROVENANCE,
        "configuration": {
            "phash_threshold": phash_threshold,
            "comparison_side": comparison_side,
            "include_strong": include_strong,
            "max_queries": max_queries,
        },
        "ground_truth": {
            "source": GROUND_TRUTH_SOURCE,
            "entries": len(manifest),
            "unknown_excluded": 0,
        },
        "counts": {
            "originals": len(originals),
            "queries": len(manifest),
            "comparisons": comparisons,
            "structural_comparisons": structural_comparisons,
        },
        "timing": {
            "total_seconds": elapsed,
            "hashing_seconds": hash_seconds,
            "structural_seconds": structural_seconds,
            "mean_seconds_per_query": elapsed / len(manifest) if manifest else None,
        },
        "memory": {
            "tracemalloc_current_bytes": current_memory,
            "tracemalloc_peak_bytes": peak_memory,
            "scope": "Python allocations only; excludes native decoder/NumPy allocations",
        },
        "metric_rules": {
            "retrieval": "rank by minimum four-rotation pHash distance; ties by original filename",
            "candidate": f"pHash distance <= {phash_threshold}",
            "confirmed_pair": "existing classify_visual result: SSIM >= 0.80 and MAE <= 0.10",
            "pair_universe": (
                "every evaluated query x every eligible original; one positive original per query"
            ),
        },
        "metrics": metrics,
        "metrics_by_transformation": _group_metrics(rows),
        "queries": rows,
        "manifest": [entry.to_dict(root) for entry in manifest],
    }


def _render_html(result: dict[str, Any], example_limit: int = 12) -> str:
    rows = result["queries"]
    categories = {
        "acertos": [
            row for row in rows if row["expected_rank"] == 1 and row["expected_is_confirmed"]
        ],
        "falsos positivos": [row for row in rows if row["incorrect_confirmed"]],
        "falsos negativos": [
            row for row in rows if not row["expected_is_confirmed"] and not row["error"]
        ],
        "inconclusivos": [row for row in rows if row["error"]],
    }

    def table(items: list[dict[str, Any]]) -> str:
        chosen = sorted(items, key=lambda row: row["query"])[:example_limit]
        body = "".join(
            f"<tr><td>{html.escape(row['query'])}</td><td>{html.escape(str(row['top_1']))}</td><td>{html.escape(str(row['expected_rank']))}</td><td>{html.escape(str(row['expected_distance']))}</td></tr>"
            for row in chosen
        )
        return (
            f"<p>Amostra determinística: primeiros {len(chosen)} por caminho, "
            f"de {len(items)}.</p><table><tr><th>Consulta</th><th>Top-1</th>"
            f"<th>Rank esperado</th><th>pHash esperado</th></tr>{body}</table>"
        )

    sections = "".join(
        f"<h2>{html.escape(name.title())}</h2>{table(items)}" for name, items in categories.items()
    )
    summary = html.escape(
        json.dumps(
            {
                "counts": result["counts"],
                "metrics": result["metrics"],
                "timing": result["timing"],
                "memory": result["memory"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<title>Copydays benchmark</title><style>"
        "body{font:15px system-ui;max-width:1100px;margin:auto;padding:2rem}"
        "pre,table{width:100%;background:#f5f5f3;padding:1rem}"
        "table{border-collapse:collapse}th,td{border:1px solid #bbb;padding:.45rem;"
        "text-align:left;overflow-wrap:anywhere}</style></head><body>"
        "<h1>PlayMemories Duplicate Lab — Copydays</h1>"
        "<p>Sem miniaturas incorporadas. Resultados ordenados deterministicamente.</p>"
        f"<pre>{summary}</pre>{sections}</body></html>"
    )


def write_benchmark_reports(
    result: dict[str, Any], output_dir: Path, *, overwrite: bool = False
) -> tuple[Path, ...]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = (
        output_dir / "copydays-benchmark.json",
        output_dir / "copydays-queries.csv",
        output_dir / "copydays-summary.html",
    )
    if not overwrite and any(path.exists() for path in targets):
        raise FileExistsError("Relatório de benchmark existente; use --overwrite")
    mode = "w" if overwrite else "x"
    with targets[0].open(mode, encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    fields = (
        [key for key in result["queries"][0] if key != "incorrect_confirmed"]
        if result["queries"]
        else []
    )
    fields.append("incorrect_confirmed")
    with targets[1].open(mode, encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in result["queries"]:
            writer.writerow({**row, "incorrect_confirmed": ";".join(row["incorrect_confirmed"])})
    with targets[2].open(mode, encoding="utf-8") as stream:
        stream.write(_render_html(result))
    return targets
