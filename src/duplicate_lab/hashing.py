"""Cryptographic and perceptual hashing."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

import imagehash
from PIL import Image, ImageOps

from duplicate_lab.inventory import file_identity
from duplicate_lab.models import ExactGroup, FileIdentity, PhotoRecord


def sha256_file(
    path: Path,
    chunk_size: int = 1024 * 1024,
    *,
    expected_identity: FileIdentity | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = file_identity(os.fstat(stream.fileno()))
        if expected_identity is not None and before != expected_identity:
            raise OSError(f"Arquivo alterado desde o inventário: {path}")
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
        after = file_identity(os.fstat(stream.fileno()))
    if after != before or file_identity(path.stat()) != after:
        raise OSError(f"Arquivo alterado durante o hashing: {path}")
    return digest.hexdigest()


def find_exact_groups(records: tuple[PhotoRecord, ...]) -> tuple[ExactGroup, ...]:
    by_size: dict[int, list[PhotoRecord]] = defaultdict(list)
    for record in records:
        if not record.compatible:
            continue
        if record.identity is not None and file_identity(record.path.stat()) != record.identity:
            raise OSError(f"Arquivo alterado desde o inventário: {record.path}")
        by_size[record.size_bytes].append(record)

    groups: dict[str, list[PhotoRecord]] = defaultdict(list)
    for size in sorted(by_size):
        candidates = by_size[size]
        if len(candidates) < 2:
            continue
        for record in candidates:
            groups[
                sha256_file(record.path, expected_identity=record.identity)
            ].append(record)
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
