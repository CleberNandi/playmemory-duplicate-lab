"""Pipeline orchestration."""

from collections.abc import Iterable
from pathlib import Path

from duplicate_lab.hashing import find_exact_groups
from duplicate_lab.inventory import build_inventory
from duplicate_lab.models import ScanResult
from duplicate_lab.similarity import compare_visual_pairs


def scan(
    directory: Path,
    extensions: Iterable[str] | None = None,
    phash_threshold: int = 8,
    comparison_side: int = 512,
) -> ScanResult:
    inventory = build_inventory(directory, extensions)
    exact_groups = find_exact_groups(inventory)
    pairs = compare_visual_pairs(inventory, exact_groups, phash_threshold, comparison_side)
    return ScanResult(inventory, exact_groups, pairs)
