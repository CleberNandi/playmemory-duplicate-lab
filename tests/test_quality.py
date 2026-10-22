import json
from pathlib import Path

import pytest
from conftest import save_jpeg
from PIL import Image, ImageEnhance, ImageFilter

from duplicate_lab.quality import (
    QualityIndicators,
    analyze_quality,
    build_quality_report,
    compare_quality_indicators,
)
from duplicate_lab.scanner import scan


def _manifest(path: Path, groups: list[dict]) -> Path:
    path.write_text(json.dumps({"version": 1, "groups": groups}), encoding="utf-8")
    return path


def test_resolution_uses_exif_oriented_dimensions(tmp_path: Path, patterned_image):
    exif = Image.Exif()
    exif[274] = 6
    path = save_jpeg(patterned_image, tmp_path / "oriented.jpg", exif=exif)

    indicators = analyze_quality(path)

    assert (indicators.oriented_width, indicators.oriented_height) == (64, 96)
    assert indicators.total_pixels == 96 * 64
    assert indicators.aspect_ratio == pytest.approx(2 / 3)


def test_exact_copies_are_technical_tie(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    first = save_jpeg(patterned_image, source / "first.jpg")
    (source / "copy.jpg").write_bytes(first.read_bytes())

    report = build_quality_report(scan(source), source)

    assert report.groups[0].conclusion == "tie"
    assert {member.recommendation for member in report.groups[0].members} == {"tie"}


def test_relative_indicators_detect_blur_brightness_and_jpeg_quantization(
    tmp_path: Path, patterned_image
):
    sharp = save_jpeg(patterned_image.resize((384, 256)), tmp_path / "sharp.jpg", quality=95)
    blurred = save_jpeg(
        patterned_image.resize((384, 256)).filter(ImageFilter.GaussianBlur(5)),
        tmp_path / "blurred.jpg",
        quality=95,
    )
    dark = save_jpeg(ImageEnhance.Brightness(patterned_image).enhance(0.4), tmp_path / "dark.jpg")
    bright = save_jpeg(
        ImageEnhance.Brightness(patterned_image).enhance(1.8), tmp_path / "bright.jpg"
    )
    compressed = save_jpeg(patterned_image, tmp_path / "compressed.jpg", quality=20)
    reference = save_jpeg(patterned_image, tmp_path / "reference.jpg", quality=95)

    assert analyze_quality(sharp).sharpness > analyze_quality(blurred).sharpness
    assert analyze_quality(bright).mean_luminance > analyze_quality(dark).mean_luminance
    assert (
        analyze_quality(reference).jpeg_quantization_mean
        < analyze_quality(compressed).jpeg_quantization_mean
    )


def test_ground_truth_compares_different_resolutions_conservatively(
    tmp_path: Path, patterned_image
):
    source = tmp_path / "photos"
    source.mkdir()
    large = patterned_image.resize((384, 256))
    save_jpeg(large, source / "large.jpg", quality=95)
    save_jpeg(large.resize((96, 64)), source / "small.jpg", quality=95)
    manifest = _manifest(
        tmp_path / "ground-truth.json",
        [{"id": "known-capture", "members": ["large.jpg", "small.jpg"]}],
    )

    report = build_quality_report(scan(source), source, manifest)
    group = report.groups[0]

    indicators = {item.path.name: item for item in report.indicators}
    assert indicators["large.jpg"].total_pixels > indicators["small.jpg"].total_pixels
    assert group.conclusion == "preferred"
    assert len(group.members[0].reasons) >= 2


def test_ground_truth_can_prefer_less_compressed_sharper_version(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    image = patterned_image.resize((384, 256))
    save_jpeg(image, source / "reference.jpg", quality=95)
    save_jpeg(image, source / "compressed.jpg", quality=10)
    manifest = _manifest(
        tmp_path / "ground-truth.json",
        [{"id": "compression", "members": ["reference.jpg", "compressed.jpg"]}],
    )

    group = build_quality_report(scan(source), source, manifest).groups[0]

    assert group.conclusion == "preferred"
    assert group.members[0].path.name == "reference.jpg"
    assert "quantização JPEG relativamente menos agressiva" in group.members[0].reasons


def test_artificial_upscale_does_not_win_on_pixels_alone(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    original = save_jpeg(patterned_image, source / "original.jpg", quality=95)
    with Image.open(original) as decoded:
        upscaled = decoded.resize((384, 256), Image.Resampling.BICUBIC)
        save_jpeg(upscaled, source / "upscaled.jpg", quality=95)
    manifest = _manifest(
        tmp_path / "ground-truth.json",
        [{"id": "upscale", "members": ["original.jpg", "upscaled.jpg"]}],
    )

    group = build_quality_report(scan(source), source, manifest).groups[0]

    assert group.conclusion == "incomparable"
    assert all(member.recommendation == "incomparable" for member in group.members)


def test_visual_similarity_never_creates_substitution_group(tmp_path: Path, noisy_images):
    source = tmp_path / "photos"
    source.mkdir()
    first, second = noisy_images
    save_jpeg(first, source / "dog-one.jpg")
    save_jpeg(second, source / "dog-two.jpg")

    result = scan(source, phash_threshold=64)
    report = build_quality_report(result, source)

    assert result.pairs
    assert report.groups == ()


def test_manifest_rejects_source_location_overlap_and_unknown_files(
    tmp_path: Path, patterned_image
):
    source = tmp_path / "photos"
    source.mkdir()
    save_jpeg(patterned_image, source / "known.jpg")
    result = scan(source)
    inside = _manifest(
        source / "ground-truth.json",
        [{"id": "bad", "members": ["known.jpg", "missing.jpg"]}],
    )

    with pytest.raises(ValueError, match="fora do acervo"):
        build_quality_report(result, source, inside)

    outside = _manifest(
        tmp_path / "ground-truth.json",
        [{"id": "bad", "members": ["known.jpg", "missing.jpg"]}],
    )
    with pytest.raises(ValueError, match="desconhecido"):
        build_quality_report(result, source, outside)


def test_decode_error_and_memory_limit_are_inconclusive(tmp_path: Path, monkeypatch):
    source = tmp_path / "photos"
    source.mkdir()
    invalid = source / "invalid.jpg"
    invalid.write_bytes(b"not an image")
    assert analyze_quality(invalid).error

    valid = source / "valid.jpg"
    Image.new("RGB", (20, 20), "white").save(valid, "JPEG")
    manifest = _manifest(
        tmp_path / "ground-truth.json",
        [{"id": "decode-error", "members": ["invalid.jpg", "valid.jpg"]}],
    )
    group = build_quality_report(scan(source), source, manifest).groups[0]
    assert group.conclusion == "inconclusive"

    image = Image.new("RGB", (100, 100), "white")
    path = source / "limited.jpg"
    image.save(path, "JPEG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    assert analyze_quality(path).error


def _indicators(
    name: str,
    *,
    pixels: int | None = 100,
    ratio: float | None = 1.5,
    sharpness: float | None = 1.0,
    quantization: float | None = 10.0,
    blockiness: float | None = 0.01,
) -> QualityIndicators:
    return QualityIndicators(
        Path(name),
        15 if pixels else None,
        10 if pixels else None,
        pixels,
        ratio,
        sharpness,
        0.5,
        0.0,
        0.0,
        quantization,
        blockiness,
        False,
    )


def test_pairwise_dominance_tie_conflict_and_missing_indicators():
    superior = _indicators("superior.jpg", pixels=200, sharpness=1.2, quantization=8)
    inferior = _indicators("inferior.jpg", pixels=100, sharpness=1.0, quantization=12)
    equal = _indicators("equal.jpg", pixels=200, sharpness=1.2, quantization=8)
    cleaner = _indicators(
        "cleaner.jpg", pixels=100, sharpness=1.0, quantization=5, blockiness=0.001
    )
    missing = _indicators(
        "missing.jpg", pixels=None, ratio=None, sharpness=None, quantization=None, blockiness=None
    )

    dominance = compare_quality_indicators(superior, inferior)
    conflict = compare_quality_indicators(superior, cleaner)

    assert dominance.relation == "dominates" and dominance.preferred == superior.path
    assert compare_quality_indicators(superior, equal).relation == "tie"
    assert conflict.relation == "incomparable"
    assert compare_quality_indicators(missing, missing).relation == "inconclusive"


def test_aspect_ratio_difference_is_incomparable():
    wide = _indicators("wide.jpg", pixels=200, sharpness=1.2, ratio=16 / 9)
    square = _indicators("square.jpg", pixels=100, sharpness=1.0, ratio=1.0)

    comparison = compare_quality_indicators(wide, square)

    assert comparison.relation == "incomparable"
    assert "proporções" in comparison.evidence[0]


def test_ranking_is_deterministic_and_exposes_pairwise_evidence(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    image = patterned_image.resize((384, 256))
    save_jpeg(image, source / "z-reference.jpg", quality=95)
    save_jpeg(image, source / "a-compressed.jpg", quality=10)
    manifest = _manifest(
        tmp_path / "ground-truth.json",
        [{"id": "ranked", "members": ["z-reference.jpg", "a-compressed.jpg"]}],
    )

    first_report = build_quality_report(scan(source), source, manifest)
    second = build_quality_report(scan(source), source, manifest).groups[0]
    first = first_report.groups[0]

    assert first == second
    assert first.conclusion == "preferred"
    assert first.members[0].rank == 1
    assert first.members[1].rank == 2
    assert first.comparisons[0].evidence
    assert all(not item.exif_available for item in first_report.indicators)
