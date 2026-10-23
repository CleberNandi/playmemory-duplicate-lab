"""Typed domain models used by inventory, scanning, and reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Classification = Literal["exact_duplicate", "visual_candidate", "similar_image", "unclassified"]


@dataclass(frozen=True)
class FileIdentity:
    """Metadata snapshot used to detect observable changes during a scan."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class PhotoRecord:
    path: Path
    size_bytes: int
    width: int | None = None
    height: int | None = None
    format: str | None = None
    exif_orientation: int | None = None
    compatible: bool = False
    error: str | None = None
    identity: FileIdentity | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("identity")
        data["path"] = str(self.path)
        return data


@dataclass(frozen=True)
class ExactGroup:
    sha256: str
    paths: tuple[Path, ...]
    redundant_files: int
    redundant_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "paths": [str(path) for path in self.paths],
            "redundant_files": self.redundant_files,
            "redundant_bytes": self.redundant_bytes,
        }


@dataclass(frozen=True)
class PairResult:
    left: Path
    right: Path
    phash_distance: int | None
    rotation_degrees: int | None
    ssim: float | None
    mae: float | None
    classification: Classification
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["left"] = str(self.left)
        data["right"] = str(self.right)
        return data


@dataclass(frozen=True)
class ScanResult:
    inventory: tuple[PhotoRecord, ...]
    exact_groups: tuple[ExactGroup, ...]
    pairs: tuple[PairResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "files": len(self.inventory),
                "compatible": sum(item.compatible for item in self.inventory),
                "incompatible": sum(not item.compatible for item in self.inventory),
                "exact_groups": len(self.exact_groups),
                "exact_redundant_files": sum(g.redundant_files for g in self.exact_groups),
                "exact_redundant_bytes": sum(g.redundant_bytes for g in self.exact_groups),
                "evaluated_pairs": len(self.pairs),
            },
            "inventory": [item.to_dict() for item in self.inventory],
            "exact_groups": [group.to_dict() for group in self.exact_groups],
            "pairs": [pair.to_dict() for pair in self.pairs],
        }
