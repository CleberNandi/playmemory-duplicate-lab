from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw


@pytest.fixture
def patterned_image() -> Image.Image:
    image = Image.new("RGB", (96, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 5, 38, 54), fill=(220, 20, 30))
    draw.ellipse((48, 8, 88, 48), fill=(10, 90, 210))
    draw.line((3, 60, 90, 2), fill=(20, 150, 40), width=4)
    return image


def save_jpeg(image: Image.Image, path: Path, quality: int = 95, exif=None) -> Path:
    options = {"quality": quality}
    if exif is not None:
        options["exif"] = exif
    image.save(path, "JPEG", **options)
    return path


@pytest.fixture
def noisy_images() -> tuple[Image.Image, Image.Image]:
    rng = np.random.default_rng(42)
    first = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    second = first.copy()
    second[20:44, 20:44] = 255 - second[20:44, 20:44]
    return Image.fromarray(first), Image.fromarray(second)
