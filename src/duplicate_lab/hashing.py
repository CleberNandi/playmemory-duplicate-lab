"""Cryptographic and perceptual hashing."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

import imagehash
from PIL import Image, ImageOps

from duplicate_lab.models import ExactGroup, PhotoRecord


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_exact_groups(records: tuple[PhotoRecord, ...]) -> tuple[ExactGroup, ...]:
    groups: dict[str, list[PhotoRecord]] = defaultdict(list)
    for record in records:
        if record.compatible:
            groups[sha256_file(record.path)].append(record)
    result = []
    for digest, members in sorted(groups.items()):
        if len(members) > 1:
            ordered = tuple(sorted((item.path for item in members), key=str))
            result.append(
                ExactGroup(
                    digest, ordered, len(ordered) - 1, members[0].size_bytes * (len(ordered) - 1)
                )
            )
    return tuple(result)


def oriented_phashes(path: Path) -> tuple[imagehash.ImageHash, ...]:
    """Return pHash for EXIF-normalized image at four right-angle rotations."""
    with Image.open(path) as source:
        normalized = ImageOps.exif_transpose(source).convert("RGB")
        return tuple(
            imagehash.phash(normalized.rotate(angle, expand=True)) for angle in (0, 90, 180, 270)
        )
