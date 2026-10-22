"""Visual candidate selection and bounded structural comparison."""

from __future__ import annotations

import itertools
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from skimage.metrics import structural_similarity

from duplicate_lab.hashing import oriented_phashes
from duplicate_lab.models import PairResult, PhotoRecord

LOGGER = logging.getLogger(__name__)
ROTATIONS = (0, 90, 180, 270)


def _normalized_array(path: Path, rotation: int, side: int) -> np.ndarray:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L")
        if rotation:
            image = image.rotate(rotation, expand=True)
        # A direct common-size resize preserves the full frame. Cropping here would make
        # equivalent 4:3 and 16:9 exports look structurally unrelated.
        image = image.resize((side, side), resample=Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.float32) / 255.0


def structural_metrics(
    left: Path, right: Path, rotation: int, side: int = 512
) -> tuple[float, float]:
    first = _normalized_array(left, 0, side)
    second = _normalized_array(right, rotation, side)
    return float(structural_similarity(first, second, data_range=1.0)), float(
        np.mean(np.abs(first - second))
    )


def classify_visual(ssim: float, mae: float) -> str:
    # Evidence, not proof: thresholds are deliberately conservative.
    return "similar_image" if ssim >= 0.80 and mae <= 0.10 else "visual_candidate"


def compare_visual_pairs(
    records: tuple[PhotoRecord, ...],
    exact_groups: tuple,
    phash_threshold: int = 8,
    comparison_side: int = 512,
) -> tuple[PairResult, ...]:
    compatible = [item for item in records if item.compatible]
    exact_pairs = {
        frozenset((left, right))
        for group in exact_groups
        for left, right in itertools.combinations(group.paths, 2)
    }
    hashes = {item.path: oriented_phashes(item.path) for item in compatible}
    results: list[PairResult] = []
    for left, right in itertools.combinations(compatible, 2):
        if frozenset((left.path, right.path)) in exact_pairs:
            results.append(PairResult(left.path, right.path, 0, 0, 1.0, 0.0, "exact_duplicate"))
            continue
        distances = [int(hashes[left.path][0] - candidate) for candidate in hashes[right.path]]
        distance = min(distances)
        if distance > phash_threshold:
            continue
        rotation = ROTATIONS[distances.index(distance)]
        try:
            ssim, mae = structural_metrics(left.path, right.path, rotation, comparison_side)
            classification = classify_visual(ssim, mae)
            results.append(
                PairResult(left.path, right.path, distance, rotation, ssim, mae, classification)
            )
        except (OSError, ValueError) as exc:
            LOGGER.warning(
                "comparison_failed left=%s right=%s error=%s", left.path, right.path, exc
            )
            results.append(
                PairResult(
                    left.path, right.path, distance, rotation, None, None, "unclassified", str(exc)
                )
            )
    return tuple(results)
