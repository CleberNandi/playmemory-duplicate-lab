"""Reproducible synthetic benchmark for exact-duplicate size prefiltering."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from duplicate_lab.hashing import find_exact_groups
from duplicate_lab.inventory import file_identity
from duplicate_lab.models import PhotoRecord


def _records(root: Path, unique_count: int, payload_size: int) -> tuple[PhotoRecord, ...]:
    payloads = [b"duplicate-a", b"duplicate-a", b"duplicate-b", b"duplicate-b"]
    payloads.extend(
        hashlib.sha256(f"unique-{index}".encode()).digest() for index in range(unique_count)
    )
    records = []
    for index, seed in enumerate(payloads):
        path = root / f"image-{index:04d}.jpg"
        target_size = payload_size if index < 4 else payload_size + index
        repetitions = (target_size + len(seed) - 1) // len(seed)
        path.write_bytes((seed * repetitions)[:target_size])
        identity = file_identity(path.stat())
        records.append(
            PhotoRecord(path, identity.size, compatible=True, identity=identity)
        )
    return tuple(records)


def _legacy(records: tuple[PhotoRecord, ...]):
    groups = defaultdict(list)
    for record in records:
        with record.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        groups[digest].append(record.path)
    return tuple(
        (digest, tuple(sorted(paths, key=str)))
        for digest, paths in sorted(groups.items())
        if len(paths) > 1
    )


def _optimized(records: tuple[PhotoRecord, ...]):
    return tuple((group.sha256, group.paths) for group in find_exact_groups(records))


def _measure(function, records, repetitions: int):
    timings = []
    result = None
    for _ in range(repetitions):
        started = time.perf_counter()
        result = function(records)
        timings.append(time.perf_counter() - started)
    return result, statistics.median(timings), timings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unique-count", type=int, default=100)
    parser.add_argument("--payload-size", type=int, default=64 * 1024)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="duplicate-lab-exact-") as directory:
        records = _records(Path(directory), args.unique_count, args.payload_size)
        before, before_median, before_runs = _measure(_legacy, records, args.repetitions)
        after, after_median, after_runs = _measure(_optimized, records, args.repetitions)
        if before != after:
            raise RuntimeError("Resultados exatos divergentes")
        size_counts = defaultdict(int)
        for record in records:
            size_counts[record.size_bytes] += 1
        candidates = tuple(record for record in records if size_counts[record.size_bytes] > 1)
        pairs = sum(len(paths) * (len(paths) - 1) // 2 for _, paths in before)
        payload = {
            "fixture": "synthetic-temporary-files",
            "before": {
                "inventoried_files": len(records),
                "hashed_files": len(records),
                "hashed_bytes": sum(record.size_bytes for record in records),
                "exact_groups": len(before),
                "exact_pairs": pairs,
                "seconds_median": before_median,
                "seconds_runs": before_runs,
            },
            "after": {
                "inventoried_files": len(records),
                "hashed_files": len(candidates),
                "hashed_bytes": sum(record.size_bytes for record in candidates),
                "exact_groups": len(after),
                "exact_pairs": pairs,
                "seconds_median": after_median,
                "seconds_runs": after_runs,
            },
        }
        payload["reduction_percent"] = {
            "hashed_files": 100 * (1 - len(candidates) / len(records)),
            "hashed_bytes": 100
            * (1 - sum(record.size_bytes for record in candidates) / sum(
                record.size_bytes for record in records
            )),
        }
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
