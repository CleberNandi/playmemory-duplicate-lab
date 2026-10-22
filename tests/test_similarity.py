from pathlib import Path

from conftest import save_jpeg
from PIL import Image

from duplicate_lab.scanner import scan


def _non_exact(result):
    return [pair for pair in result.pairs if pair.classification != "exact_duplicate"]


def test_resize_is_a_similar_image(tmp_path: Path, patterned_image):
    save_jpeg(patterned_image, tmp_path / "original.jpg")
    save_jpeg(patterned_image.resize((192, 128)), tmp_path / "resized.jpg")
    pair = _non_exact(scan(tmp_path))[0]
    assert pair.phash_distance <= 8
    assert pair.classification == "similar_image"


def test_jpeg_compression_is_a_candidate_with_metrics(tmp_path: Path, patterned_image):
    save_jpeg(patterned_image, tmp_path / "high.jpg", quality=95)
    save_jpeg(patterned_image, tmp_path / "low.jpg", quality=20)
    pair = _non_exact(scan(tmp_path))[0]
    assert pair.phash_distance <= 8
    assert pair.ssim is not None
    assert pair.mae is not None


def test_rotation_is_considered(tmp_path: Path, patterned_image):
    save_jpeg(patterned_image, tmp_path / "normal.jpg")
    save_jpeg(patterned_image.rotate(180, expand=True), tmp_path / "rotated.jpg")
    pair = _non_exact(scan(tmp_path))[0]
    assert pair.rotation_degrees == 180
    assert pair.classification == "similar_image"


def test_exif_orientation_is_normalized(tmp_path: Path, patterned_image):
    save_jpeg(patterned_image, tmp_path / "normal.jpg")
    rotated_pixels = patterned_image.rotate(90, expand=True)
    exif = Image.Exif()
    exif[274] = 6
    save_jpeg(rotated_pixels, tmp_path / "tagged.jpg", exif=exif)
    pair = _non_exact(scan(tmp_path))[0]
    assert pair.phash_distance <= 8
    assert pair.classification == "similar_image"


def test_visually_distinct_images_are_not_confirmed(tmp_path: Path, noisy_images):
    first, second = noisy_images
    save_jpeg(first, tmp_path / "first.jpg")
    save_jpeg(second, tmp_path / "second.jpg")
    result = scan(tmp_path, phash_threshold=64)
    pair = _non_exact(result)[0]
    assert pair.classification == "visual_candidate"
    assert pair.ssim < 0.8 or pair.mae > 0.1
