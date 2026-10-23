from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from duplicate_lab.experiments.benchmark_local_features import (
    identity_partition,
    retrieval_metrics,
    verify_source_integrity,
)
from duplicate_lab.experiments.local_features import (
    Features,
    ORBConfig,
    extract_features,
    load_grayscale,
    match_features,
)
from duplicate_lab.hashing import sha256_file


def _pattern(path: Path, *, size: tuple[int, int] = (320, 240), quality: int = 95) -> None:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for index in range(12):
        x = 10 + (index * 47) % (size[0] - 30)
        y = 10 + (index * 71) % (size[1] - 30)
        draw.rectangle((x, y, x + 18, y + 18), fill=(index * 19, 30, 220 - index * 11))
        draw.line((0, y, size[0] - 1, (y * 3) % size[1]), fill="black", width=2)
    image.save(path, quality=quality)


def test_extraction_and_descriptor_count(tmp_path: Path) -> None:
    path = tmp_path / "pattern.jpg"
    _pattern(path)
    result = extract_features(path, ORBConfig())
    assert result.error is None
    assert result.keypoint_count > 20
    assert result.descriptors is not None
    assert len(result.descriptors) == result.keypoint_count


def test_blank_image_has_no_descriptors(tmp_path: Path) -> None:
    path = tmp_path / "blank.png"
    Image.new("L", (100, 80), 128).save(path)
    result = extract_features(path, ORBConfig())
    assert result.descriptors is None
    assert match_features(result, result, ORBConfig()).status == "no_descriptors"


def test_resize_preserves_aspect_ratio(tmp_path: Path) -> None:
    path = tmp_path / "wide.png"
    Image.new("L", (400, 100)).save(path)
    assert load_grayscale(path, 200).shape == (50, 200)


@pytest.mark.parametrize("operation", ["rotate", "crop", "jpeg", "perspective"])
def test_geometric_and_compression_matching(tmp_path: Path, operation: str) -> None:
    original = tmp_path / "original.jpg"
    transformed = tmp_path / f"{operation}.jpg"
    _pattern(original)
    image = cv2.imread(str(original))
    if operation == "rotate":
        output = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif operation == "crop":
        output = image[15:-15, 20:-20]
    elif operation == "perspective":
        height, width = image.shape[:2]
        source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        target = np.float32([[10, 8], [width - 15, 4], [width - 5, height - 12], [18, height - 2]])
        output = cv2.warpPerspective(
            image, cv2.getPerspectiveTransform(source, target), (width, height)
        )
    else:
        output = image
    cv2.imwrite(str(transformed), output, [cv2.IMWRITE_JPEG_QUALITY, 35])
    config = ORBConfig(min_inliers=5, min_filtered_matches=5, min_spatial_coverage=0.005)
    result = match_features(
        extract_features(transformed, config), extract_features(original, config), config
    )
    assert result.confirmed, result
    assert result.inliers >= 5


def test_unrelated_images_are_not_confirmed(tmp_path: Path) -> None:
    left, right = tmp_path / "left.jpg", tmp_path / "right.jpg"
    _pattern(left)
    Image.new("RGB", (320, 240), "gray").save(right)
    result = match_features(
        extract_features(left, ORBConfig()), extract_features(right, ORBConfig()), ORBConfig()
    )
    assert not result.confirmed


def _features(points: list[tuple[float, float]], descriptors: np.ndarray) -> Features:
    return Features(Path("x"), (100, 100), np.asarray(points, dtype=np.float32), descriptors, 0.0)


def test_insufficient_matches_are_inconclusive() -> None:
    descriptors = np.arange(32 * 3, dtype=np.uint8).reshape(3, 32)
    result = match_features(
        _features([(1, 1), (20, 20), (40, 40)], descriptors),
        _features([(2, 2), (21, 21), (41, 41)], descriptors),
        ORBConfig(),
    )
    assert not result.confirmed
    assert result.status in {"insufficient_matches", "concentrated_matches"}


def test_degenerate_homography_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    descriptors = np.tile(np.arange(32, dtype=np.uint8), (10, 1))
    descriptors[:, 0] = np.arange(10)
    points = [(float(i * 8), float(i * 7)) for i in range(10)]
    monkeypatch.setattr(
        cv2, "findHomography", lambda *args: (np.zeros((3, 3)), np.ones((10, 1), dtype=np.uint8))
    )
    result = match_features(
        _features(points, descriptors),
        _features(points, descriptors),
        ORBConfig(ratio_threshold=1.1, min_spatial_coverage=0.0),
    )
    assert result.status == "degenerate_homography"
    assert not result.confirmed


def test_metrics_use_pair_and_negative_query_denominators() -> None:
    base = {
        "error": None,
        "orb_rank": None,
        "orb_expected_candidate": False,
        "orb_expected_confirmed": False,
        "orb_confirmed_count": 0,
    }
    rows = [
        {
            **base,
            "expected_original": "a",
            "orb_rank": 1,
            "orb_expected_candidate": True,
            "orb_expected_confirmed": True,
            "orb_confirmed_count": 2,
        },
        {**base, "expected_original": "b"},
        {**base, "expected_original": None, "orb_confirmed_count": 1},
        {**base, "expected_original": None},
    ]
    metrics = retrieval_metrics(rows, "orb")
    assert metrics["precision"] == pytest.approx(1 / 3)
    assert metrics["recall"] == 0.5
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["false_positive_rate_denominator"].startswith("negative queries")


def test_partition_and_feature_extraction_are_reproducible(tmp_path: Path) -> None:
    path = tmp_path / "image.jpg"
    _pattern(path)
    config = ORBConfig(seed=42)
    first, second = extract_features(path, config), extract_features(path, config)
    assert identity_partition("0001", 42) == identity_partition("0001", 42)
    assert np.array_equal(first.keypoints, second.keypoints)
    assert np.array_equal(first.descriptors, second.descriptors)


def test_integrity_check_detects_but_does_not_modify(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    result = {"source_integrity": {"before": {str(path): sha256_file(path)}}}
    before = path.read_bytes()
    assert verify_source_integrity(result)
    assert path.read_bytes() == before
    path.write_bytes(b"changed")
    assert not verify_source_integrity(result)


def test_exif_orientation_is_respected(tmp_path: Path) -> None:
    path = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (80, 40))
    exif = image.getexif()
    exif[274] = 6
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    path.write_bytes(stream.getvalue())
    assert load_grayscale(path, 100).shape == (80, 40)
