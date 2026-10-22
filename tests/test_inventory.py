from pathlib import Path

from conftest import save_jpeg
from PIL import Image

from duplicate_lab.inventory import build_inventory


def test_inventory_validates_real_format_and_invalid_file(tmp_path: Path, patterned_image):
    valid = save_jpeg(patterned_image, tmp_path / "valid.jpg")
    png_disguised = tmp_path / "wrong.jpeg"
    patterned_image.save(png_disguised, "PNG")
    invalid = tmp_path / "broken.jpg"
    invalid.write_bytes(b"not an image")

    records = {item.path.name: item for item in build_inventory(tmp_path)}

    assert records[valid.name].compatible
    assert records[valid.name].format == "JPEG"
    assert not records[png_disguised.name].compatible
    assert records[png_disguised.name].format == "PNG"
    assert not records[invalid.name].compatible
    assert records[invalid.name].error


def test_inventory_reads_exif_orientation(tmp_path: Path, patterned_image):
    exif = Image.Exif()
    exif[274] = 6
    path = save_jpeg(patterned_image, tmp_path / "oriented.jpg", exif=exif)
    record = build_inventory(tmp_path)[0]
    assert record.path == path.resolve()
    assert record.exif_orientation == 6
