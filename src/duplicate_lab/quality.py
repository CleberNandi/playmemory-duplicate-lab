"""Conservative, explainable technical-quality indicators and comparisons."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from duplicate_lab.models import ScanResult

Recommendation = Literal["preferred", "alternative", "tie", "incomparable", "inconclusive"]
Eligibility = Literal["binary_identity", "ground_truth_capture"]
ComparisonRelation = Literal["dominates", "tie", "incomparable", "inconclusive"]
ANALYSIS_SIDE = 512


@dataclass(frozen=True)
class QualityIndicators:
    path: Path
    oriented_width: int | None
    oriented_height: int | None
    total_pixels: int | None
    aspect_ratio: float | None
    sharpness: float | None
    mean_luminance: float | None
    bright_fraction: float | None
    dark_fraction: float | None
    jpeg_quantization_mean: float | None
    blockiness_experimental: float | None
    exif_available: bool | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(frozen=True)
class QualityMember:
    path: Path
    recommendation: Recommendation
    reasons: tuple[str, ...]
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "recommendation": self.recommendation,
            "reasons": list(self.reasons),
            "rank": self.rank,
        }


@dataclass(frozen=True)
class QualityComparison:
    left: Path
    right: Path
    relation: ComparisonRelation
    preferred: Path | None
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": str(self.left),
            "right": str(self.right),
            "relation": self.relation,
            "preferred": str(self.preferred) if self.preferred else None,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class QualityGroup:
    group_id: str
    eligibility: Eligibility
    members: tuple[QualityMember, ...]
    conclusion: Recommendation
    limitations: tuple[str, ...]
    comparisons: tuple[QualityComparison, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "eligibility": self.eligibility,
            "members": [member.to_dict() for member in self.members],
            "conclusion": self.conclusion,
            "limitations": list(self.limitations),
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
        }


@dataclass(frozen=True)
class QualityReport:
    indicators: tuple[QualityIndicators, ...]
    groups: tuple[QualityGroup, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicators": [item.to_dict() for item in self.indicators],
            "groups": [group.to_dict() for group in self.groups],
        }


def _normalized_luminance(image: Image.Image, side: int = ANALYSIS_SIDE) -> np.ndarray:
    grayscale = image.convert("L")
    width, height = grayscale.size
    scale = side / max(width, height)
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    grayscale = grayscale.resize(target, Image.Resampling.LANCZOS)
    return np.asarray(grayscale, dtype=np.float32) / 255.0


def _sharpness(array: np.ndarray) -> float | None:
    if min(array.shape, default=0) < 3:
        return None
    center = array[1:-1, 1:-1]
    laplacian = array[:-2, 1:-1] + array[2:, 1:-1] + array[1:-1, :-2] + array[1:-1, 2:] - 4 * center
    return float(np.var(laplacian))


def _blockiness(array: np.ndarray) -> float | None:
    """Approximate discontinuities on an analysis grid; experimental, not JPEG quality."""
    if min(array.shape, default=0) < 16:
        return None
    vertical = np.abs(np.diff(array, axis=1))
    horizontal = np.abs(np.diff(array, axis=0))
    v_boundaries = vertical[:, 7::8]
    h_boundaries = horizontal[7::8, :]
    if not v_boundaries.size or not h_boundaries.size:
        return None
    boundary = (float(v_boundaries.mean()) + float(h_boundaries.mean())) / 2
    baseline = (float(vertical.mean()) + float(horizontal.mean())) / 2
    return max(0.0, boundary - baseline)


def analyze_quality(path: Path) -> QualityIndicators:
    resolved = path.resolve()
    try:
        with Image.open(resolved) as source:
            quantization = getattr(source, "quantization", None)
            quantization_values = (
                [value for table in quantization.values() for value in table]
                if quantization
                else []
            )
            exif_available = bool(source.getexif())
            oriented = ImageOps.exif_transpose(source)
            width, height = oriented.size
            array = _normalized_luminance(oriented)
        return QualityIndicators(
            path=resolved,
            oriented_width=width,
            oriented_height=height,
            total_pixels=width * height,
            aspect_ratio=width / height if height else None,
            sharpness=_sharpness(array),
            mean_luminance=float(array.mean()),
            bright_fraction=float(np.mean(array >= 250 / 255)),
            dark_fraction=float(np.mean(array <= 5 / 255)),
            jpeg_quantization_mean=(
                float(np.mean(quantization_values)) if quantization_values else None
            ),
            blockiness_experimental=_blockiness(array),
            exif_available=exif_available,
        )
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        return QualityIndicators(
            resolved, None, None, None, None, None, None, None, None, None, None, None, str(exc)
        )


def load_ground_truth_manifest(
    manifest_path: Path, source_directory: Path, known_paths: set[Path]
) -> tuple[tuple[str, tuple[Path, ...]], ...]:
    manifest = manifest_path.resolve()
    source = source_directory.resolve()
    if manifest == source or source in manifest.parents:
        raise ValueError("O manifesto de ground truth deve ficar fora do acervo")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("groups"), list):
        raise ValueError("Manifesto de ground truth invalido")
    groups: list[tuple[str, tuple[Path, ...]]] = []
    already_grouped: set[Path] = set()
    for raw in payload["groups"]:
        group_id = raw.get("id")
        members = raw.get("members")
        if not isinstance(group_id, str) or not group_id or not isinstance(members, list):
            raise ValueError("Grupo de ground truth invalido")
        paths = tuple((source / member).resolve() for member in members if isinstance(member, str))
        if len(paths) != len(members) or len(paths) < 2 or len(set(paths)) != len(paths):
            raise ValueError(f"Membros invalidos no grupo {group_id}")
        if any(source not in path.parents or path not in known_paths for path in paths):
            raise ValueError(f"Arquivo desconhecido ou fora do acervo no grupo {group_id}")
        if already_grouped.intersection(paths):
            raise ValueError("Um arquivo nao pode pertencer a grupos confirmados sobrepostos")
        already_grouped.update(paths)
        groups.append((group_id, paths))
    return tuple(groups)


def _advantages(candidate: QualityIndicators, other: QualityIndicators) -> tuple[str, ...]:
    reasons = []
    if (
        candidate.total_pixels
        and other.total_pixels
        and candidate.total_pixels >= other.total_pixels * 1.10
    ):
        reasons.append("resolução efetiva superior")
    if (
        candidate.sharpness is not None
        and other.sharpness is not None
        and candidate.sharpness >= other.sharpness * 1.08
    ):
        reasons.append("nitidez relativa superior na escala normalizada")
    if (
        candidate.jpeg_quantization_mean is not None
        and other.jpeg_quantization_mean is not None
        and candidate.jpeg_quantization_mean <= other.jpeg_quantization_mean * 0.95
    ):
        reasons.append("quantização JPEG relativamente menos agressiva")
        if (
            candidate.blockiness_experimental is not None
            and other.blockiness_experimental is not None
            and candidate.blockiness_experimental <= other.blockiness_experimental * 0.85
        ):
            reasons.append("menos descontinuidades de bloco observadas experimentalmente")
    return tuple(reasons)


def _disadvantages(candidate: QualityIndicators, other: QualityIndicators) -> tuple[str, ...]:
    disadvantages = list(_advantages(other, candidate))
    if (
        "nitidez relativa superior na escala normalizada" in disadvantages
        and candidate.jpeg_quantization_mean is not None
        and other.jpeg_quantization_mean is not None
        and other.jpeg_quantization_mean > candidate.jpeg_quantization_mean * 1.5
    ):
        # Strong compression can create false high-frequency edges. Do not let that
        # sharpness reading veto cleaner quantization evidence.
        disadvantages.remove("nitidez relativa superior na escala normalizada")
    return tuple(disadvantages)


def _rank_capture_group(
    group_id: str,
    paths: tuple[Path, ...],
    indicators: dict[Path, QualityIndicators],
) -> QualityGroup:
    ordered_paths = tuple(sorted(paths, key=lambda item: item.as_posix().casefold()))
    if any(indicators[path].error for path in ordered_paths):
        members = tuple(QualityMember(path, "inconclusive", ()) for path in ordered_paths)
        return QualityGroup(
            group_id,
            "ground_truth_capture",
            members,
            "inconclusive",
            ("Há indicadores ausentes por erro de decodificação.",),
        )

    comparisons: list[QualityComparison] = []
    outgoing = {path: set() for path in ordered_paths}
    incoming = {path: set() for path in ordered_paths}
    reasons_by_path: dict[Path, set[str]] = {path: set() for path in ordered_paths}
    for index, left in enumerate(ordered_paths):
        for right in ordered_paths[index + 1 :]:
            comparison = compare_quality_indicators(indicators[left], indicators[right])
            comparisons.append(comparison)
            if comparison.relation == "dominates" and comparison.preferred:
                other = right if comparison.preferred == left else left
                outgoing[comparison.preferred].add(other)
                incoming[other].add(comparison.preferred)
                reasons_by_path[comparison.preferred].update(comparison.evidence)

    ranks: dict[Path, int] = {}
    remaining = set(ordered_paths)
    rank = 1
    while remaining:
        tier = sorted(
            (path for path in remaining if not (incoming[path] & remaining)),
            key=lambda item: item.as_posix().casefold(),
        )
        if not tier:  # Defensive fallback; strict dominance should be acyclic.
            tier = sorted(remaining, key=lambda item: item.as_posix().casefold())
        for path in tier:
            ranks[path] = rank
            remaining.remove(path)
        rank += 1

    top = [path for path in ordered_paths if ranks[path] == 1]
    all_ties = bool(comparisons) and all(item.relation == "tie" for item in comparisons)
    has_inconclusive = any(item.relation == "inconclusive" for item in comparisons)
    if all_ties:
        conclusion: Recommendation = "tie"
    elif len(top) == 1 and _reachable(top[0], outgoing) == set(ordered_paths) - {top[0]}:
        conclusion = "preferred"
    elif has_inconclusive and not any(outgoing.values()):
        conclusion = "inconclusive"
    else:
        conclusion = "incomparable"

    members_list = []
    for path in sorted(ordered_paths, key=lambda item: (ranks[item], item.as_posix().casefold())):
        if conclusion == "tie":
            recommendation: Recommendation = "tie"
        elif conclusion == "preferred" and path == top[0]:
            recommendation = "preferred"
        elif incoming[path]:
            recommendation = "alternative"
        elif has_inconclusive:
            recommendation = "inconclusive"
        else:
            recommendation = "incomparable"
        reasons = tuple(sorted(reasons_by_path[path]))
        if not reasons:
            reasons = ("sem superioridade técnica demonstrada sobre as alternativas",)
        members_list.append(QualityMember(path, recommendation, reasons, ranks[path]))
    members = tuple(members_list)
    return QualityGroup(
        group_id,
        "ground_truth_capture",
        members,
        conclusion,
        (
            "Indicadores são relativos a este grupo e não medem valor estético.",
            "Ruído, textura, sharpening e ampliação artificial podem enganar a nitidez.",
            "Exposição é descritiva e não participa da preferência.",
            "Quantização e blocos JPEG são indicadores experimentais, não a qualidade original.",
        ),
        tuple(comparisons),
    )


def _reachable(start: Path, outgoing: dict[Path, set[Path]]) -> set[Path]:
    reached: set[Path] = set()
    pending = list(outgoing[start])
    while pending:
        path = pending.pop()
        if path not in reached:
            reached.add(path)
            pending.extend(outgoing[path] - reached)
    return reached


def compare_quality_indicators(
    left: QualityIndicators, right: QualityIndicators
) -> QualityComparison:
    if left.error or right.error:
        return QualityComparison(
            left.path,
            right.path,
            "inconclusive",
            None,
            ("indicadores ausentes por erro de decodificação",),
        )
    if left.aspect_ratio and right.aspect_ratio:
        ratio_delta = abs(left.aspect_ratio - right.aspect_ratio) / max(
            left.aspect_ratio, right.aspect_ratio
        )
        if ratio_delta > 0.02:
            return QualityComparison(
                left.path,
                right.path,
                "incomparable",
                None,
                ("proporções diferem de forma relevante",),
            )
    left_advantages = _advantages(left, right)
    right_advantages = _advantages(right, left)
    left_disadvantages = _disadvantages(left, right)
    right_disadvantages = _disadvantages(right, left)
    if len(left_advantages) >= 2 and not left_disadvantages:
        return QualityComparison(left.path, right.path, "dominates", left.path, left_advantages)
    if len(right_advantages) >= 2 and not right_disadvantages:
        return QualityComparison(left.path, right.path, "dominates", right.path, right_advantages)
    available = (
        left.total_pixels,
        right.total_pixels,
        left.sharpness,
        right.sharpness,
        left.jpeg_quantization_mean,
        right.jpeg_quantization_mean,
    )
    if all(value is None for value in available):
        return QualityComparison(
            left.path, right.path, "inconclusive", None, ("indicadores técnicos ausentes",)
        )
    if not left_advantages and not right_advantages:
        return QualityComparison(
            left.path,
            right.path,
            "tie",
            None,
            ("nenhuma diferença técnica confiável ultrapassou os limiares",),
        )
    evidence = tuple(
        [
            *(f"{left.path.name}: {item}" for item in left_advantages),
            *(f"{right.path.name}: {item}" for item in right_advantages),
        ]
    )
    return QualityComparison(left.path, right.path, "incomparable", None, evidence)


def build_quality_report(
    result: ScanResult,
    source_directory: Path,
    manifest_path: Path | None = None,
) -> QualityReport:
    indicators = tuple(analyze_quality(record.path) for record in result.inventory)
    by_path = {item.path: item for item in indicators}
    groups: list[QualityGroup] = []
    exact_paths: set[Path] = set()
    for index, exact in enumerate(result.exact_groups, 1):
        exact_paths.update(exact.paths)
        groups.append(
            QualityGroup(
                f"exact-{index}",
                "binary_identity",
                tuple(
                    QualityMember(path, "tie", ("conteúdo binário SHA-256 idêntico",))
                    for path in exact.paths
                ),
                "tie",
                ("Nenhuma diferença técnica é atribuída a cópias byte a byte idênticas.",),
            )
        )
    if manifest_path:
        known = set(by_path)
        for group_id, paths in load_ground_truth_manifest(manifest_path, source_directory, known):
            if exact_paths.intersection(paths):
                raise ValueError("Cópias exatas não devem reaparecer no manifesto de capturas")
            groups.append(_rank_capture_group(group_id, paths, by_path))
    return QualityReport(indicators, tuple(groups))
