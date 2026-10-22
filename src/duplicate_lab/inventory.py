"""Read-only discovery and validation of image files."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from duplicate_lab.models import PhotoRecord

LOGGER = logging.getLogger(__name__)
DEFAULT_EXTENSIONS = frozenset({".jpg", ".jpeg"})


def normalize_extensions(extensions: Iterable[str] | None = None) -> frozenset[str]:
    values = extensions or DEFAULT_EXTENSIONS
    return frozenset((value if value.startswith(".") else f".{value}").lower() for value in values)


def discover_files(directory: Path, extensions: Iterable[str] | None = None) -> list[Path]:
    """Discover regular files recursively without following directory symlinks."""
    allowed = normalize_extensions(extensions)
    return sorted(
        path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in allowed
    )


def inspect_file(path: Path) -> PhotoRecord:
    size = path.stat().st_size
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format
            orientation = image.getexif().get(274)
        return PhotoRecord(
            path=path.resolve(),
            size_bytes=size,
            width=width,
            height=height,
            format=image_format,
            exif_orientation=orientation,
            compatible=image_format in {"JPEG"},
            error=None if image_format == "JPEG" else f"unsupported real format: {image_format}",
        )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        LOGGER.warning("image_validation_failed path=%s error=%s", path, exc)
        return PhotoRecord(path=path.resolve(), size_bytes=size, error=str(exc))


def build_inventory(
    directory: Path, extensions: Iterable[str] | None = None
) -> tuple[PhotoRecord, ...]:
    if not directory.is_dir():
        raise NotADirectoryError(f"Diretorio inexistente ou invalido: {directory}")
    return tuple(inspect_file(path) for path in discover_files(directory, extensions))
