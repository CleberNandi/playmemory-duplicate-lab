"""Experiment-only robust geometric evidence for duplicate-image evaluation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np

from duplicate_lab.experiments.local_features import Features


@dataclass(frozen=True)
class VerificationConfig:
    ratio_threshold: float = 0.75
    min_matches: int = 8
    min_inliers: int = 8
    min_inlier_ratio: float = 0.35
    min_inlier_coverage: float = 0.02
    min_grid_cells: int = 3
    max_symmetric_error: float = 5.0
    min_corner_area_ratio: float = 0.03
    max_corner_area_ratio: float = 12.0
    max_condition: float = 1e8
    max_perspective: float = 0.003
    min_scale: float = 0.12
    max_scale: float = 8.0
    max_shear_cosine: float = 0.65
    ransac_reprojection_threshold: float = 4.0
    seed: int = 202503

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def evidence_fingerprint(self) -> tuple[float, float, int]:
        """Parameters that change matching, RANSAC, or the resulting measurements."""
        return (self.ratio_threshold, self.ransac_reprojection_threshold, self.seed)


@dataclass(frozen=True)
class GeometricEvidence:
    raw_matches: int
    ratio_matches: int
    mutual_matches: int
    median_distance: float | None
    unique_train_ratio: float
    inliers: int
    inlier_ratio: float
    query_coverage: float
    candidate_coverage: float
    inlier_query_coverage: float
    inlier_candidate_coverage: float
    query_grid_cells: int
    candidate_grid_cells: int
    reprojection_error: float | None
    inverse_reprojection_error: float | None
    symmetric_error: float | None
    determinant: float | None
    condition: float | None
    scale_min: float | None
    scale_max: float | None
    shear_cosine: float | None
    perspective: float | None
    corner_area_ratio: float | None
    homography: tuple[tuple[float, ...], ...] | None
    degenerate: bool
    plausible: bool
    status: str

    def confirms_current(self) -> bool:
        return (
            self.ratio_matches >= 8
            and self.inliers >= 8
            and self.inlier_ratio >= 0.35
            and min(self.query_coverage, self.candidate_coverage) >= 0.02
            and self.reprojection_error is not None
            and self.reprojection_error <= 5.0
            and not self.degenerate
        )

    def confirms_selective(self, config: VerificationConfig) -> bool:
        return (
            self.ratio_matches >= config.min_matches
            and self.inliers >= config.min_inliers
            and self.inlier_ratio >= config.min_inlier_ratio
            and min(self.inlier_query_coverage, self.inlier_candidate_coverage)
            >= config.min_inlier_coverage
            and min(self.query_grid_cells, self.candidate_grid_cells) >= config.min_grid_cells
            and self.symmetric_error is not None
            and self.symmetric_error <= config.max_symmetric_error
            and self.is_plausible(config)
        )

    def is_plausible(self, config: VerificationConfig) -> bool:
        values = (
            self.condition,
            self.corner_area_ratio,
            self.perspective,
            self.scale_min,
            self.scale_max,
            self.shear_cosine,
        )
        if self.degenerate or any(value is None for value in values):
            return False
        return bool(
            self.condition <= config.max_condition  # type: ignore[operator]
            and config.min_corner_area_ratio
            <= self.corner_area_ratio  # type: ignore[operator]
            <= config.max_corner_area_ratio
            and self.perspective <= config.max_perspective  # type: ignore[operator]
            and config.min_scale
            <= self.scale_min  # type: ignore[operator]
            <= self.scale_max  # type: ignore[operator]
            <= config.max_scale
            and self.shear_cosine <= config.max_shear_cosine  # type: ignore[operator]
        )

    def confirms_mutual(self, config: VerificationConfig) -> bool:
        return self.mutual_matches >= config.min_matches and self.confirms_current()


def _coverage(points: np.ndarray, size: tuple[int, int]) -> float:
    if len(points) < 2 or min(size) <= 0:
        return 0.0
    extent = np.ptp(points, axis=0)
    return float(np.prod(extent) / (size[0] * size[1]))


def _grid_cells(points: np.ndarray, size: tuple[int, int], divisions: int = 4) -> int:
    if not len(points) or min(size) <= 0:
        return 0
    scaled = points / np.asarray(size, dtype=np.float32)
    cells = np.clip((scaled * divisions).astype(int), 0, divisions - 1)
    return len({(int(x), int(y)) for x, y in cells})


def _polygon_area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))) / 2


def homography_diagnostics(
    homography: np.ndarray,
    query_size: tuple[int, int],
    candidate_size: tuple[int, int],
    config: VerificationConfig,
) -> dict[str, float | bool]:
    """Measure numerical and projective plausibility without claiming identity."""
    if homography.shape != (3, 3) or not np.isfinite(homography).all():
        return {"degenerate": True, "plausible": False}
    h = homography / homography[2, 2] if abs(homography[2, 2]) > 1e-12 else homography
    affine = h[:2, :2]
    determinant = float(np.linalg.det(affine))
    condition = float(np.linalg.cond(h))
    singular = np.linalg.svd(affine, compute_uv=False)
    scale_min, scale_max = float(min(singular)), float(max(singular))
    columns = affine[:, 0], affine[:, 1]
    denominator = float(np.linalg.norm(columns[0]) * np.linalg.norm(columns[1]))
    shear = abs(float(np.dot(*columns) / denominator)) if denominator else math.inf
    perspective = float(np.linalg.norm(h[2, :2]))
    width, height = query_size
    corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]]).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(corners, h).reshape(-1, 2)
    candidate_area = float(candidate_size[0] * candidate_size[1])
    corner_area_ratio = _polygon_area(projected) / candidate_area if candidate_area else math.inf
    degenerate = bool(abs(determinant) < 1e-8 or not math.isfinite(condition) or condition > 1e10)
    plausible = bool(
        not degenerate
        and condition <= config.max_condition
        and config.min_corner_area_ratio <= corner_area_ratio <= config.max_corner_area_ratio
        and perspective <= config.max_perspective
        and config.min_scale <= scale_min <= scale_max <= config.max_scale
        and shear <= config.max_shear_cosine
    )
    return {
        "determinant": determinant,
        "condition": condition,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "shear_cosine": shear,
        "perspective": perspective,
        "corner_area_ratio": corner_area_ratio,
        "degenerate": degenerate,
        "plausible": plausible,
    }


def _ratio_matches(source: np.ndarray, target: np.ndarray, threshold: float) -> list[cv2.DMatch]:
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    return [
        pair[0]
        for pair in matcher.knnMatch(source, target, k=2)
        if len(pair) == 2 and pair[0].distance < threshold * pair[1].distance
    ]


def mutual_ratio_matches(
    query_descriptors: np.ndarray, candidate_descriptors: np.ndarray, threshold: float
) -> tuple[list[cv2.DMatch], list[cv2.DMatch]]:
    """Return forward ratio matches and the forward subset consistent in reverse."""
    forward = _ratio_matches(query_descriptors, candidate_descriptors, threshold)
    reverse = _ratio_matches(candidate_descriptors, query_descriptors, threshold)
    reverse_pairs = {(match.trainIdx, match.queryIdx) for match in reverse}
    return forward, [
        match for match in forward if (match.queryIdx, match.trainIdx) in reverse_pairs
    ]


def analyze_pair(
    query: Features, candidate: Features, config: VerificationConfig | None = None
) -> GeometricEvidence:
    if config is None:
        config = VerificationConfig()
    empty = dict(
        raw_matches=0,
        ratio_matches=0,
        mutual_matches=0,
        median_distance=None,
        unique_train_ratio=0.0,
        inliers=0,
        inlier_ratio=0.0,
        query_coverage=0.0,
        candidate_coverage=0.0,
        inlier_query_coverage=0.0,
        inlier_candidate_coverage=0.0,
        query_grid_cells=0,
        candidate_grid_cells=0,
        reprojection_error=None,
        inverse_reprojection_error=None,
        symmetric_error=None,
        determinant=None,
        condition=None,
        scale_min=None,
        scale_max=None,
        shear_cosine=None,
        perspective=None,
        corner_area_ratio=None,
        homography=None,
        degenerate=True,
        plausible=False,
    )
    if query.descriptors is None or candidate.descriptors is None:
        return GeometricEvidence(**empty, status="no_descriptors")
    if min(len(query.descriptors), len(candidate.descriptors)) < 2:
        return GeometricEvidence(**empty, status="insufficient_descriptors")
    forward, mutual = mutual_ratio_matches(
        query.descriptors, candidate.descriptors, config.ratio_threshold
    )
    q_points = np.asarray([query.keypoints[m.queryIdx] for m in forward], dtype=np.float32)
    c_points = np.asarray([candidate.keypoints[m.trainIdx] for m in forward], dtype=np.float32)
    base = {
        **empty,
        "raw_matches": len(query.descriptors),
        "ratio_matches": len(forward),
        "mutual_matches": len(mutual),
        "median_distance": (
            float(np.median([match.distance for match in forward])) if forward else None
        ),
        "unique_train_ratio": len({m.trainIdx for m in forward}) / len(forward) if forward else 0.0,
    }
    if len(forward) < 4:
        return GeometricEvidence(**base, status="insufficient_matches")
    cv2.setRNGSeed(config.seed)
    homography, mask = cv2.findHomography(
        q_points.reshape(-1, 1, 2),
        c_points.reshape(-1, 1, 2),
        cv2.RANSAC,
        config.ransac_reprojection_threshold,
    )
    if homography is None or mask is None or not np.isfinite(homography).all():
        return GeometricEvidence(**base, status="invalid_homography")
    inlier_mask = mask.ravel().astype(bool)
    q_inliers, c_inliers = q_points[inlier_mask], c_points[inlier_mask]
    inliers = int(inlier_mask.sum())
    projected = cv2.perspectiveTransform(q_points.reshape(-1, 1, 2), homography).reshape(-1, 2)
    errors = np.linalg.norm(projected - c_points, axis=1)
    reprojection = float(np.median(errors[inlier_mask])) if inliers else None
    inverse_error = symmetric = None
    try:
        inverse = np.linalg.inv(homography)
        back = cv2.perspectiveTransform(c_points.reshape(-1, 1, 2), inverse).reshape(-1, 2)
        inverse_errors = np.linalg.norm(back - q_points, axis=1)
        inverse_error = float(np.median(inverse_errors[inlier_mask])) if inliers else None
        symmetric = (reprojection + inverse_error) / 2 if reprojection is not None else None
    except np.linalg.LinAlgError:
        pass
    diagnostics = homography_diagnostics(homography, query.image_size, candidate.image_size, config)
    values = {
        **base,
        "inliers": inliers,
        "inlier_ratio": inliers / len(forward),
        "query_coverage": _coverage(q_points, query.image_size),
        "candidate_coverage": _coverage(c_points, candidate.image_size),
        "inlier_query_coverage": _coverage(q_inliers, query.image_size),
        "inlier_candidate_coverage": _coverage(c_inliers, candidate.image_size),
        "query_grid_cells": _grid_cells(q_inliers, query.image_size),
        "candidate_grid_cells": _grid_cells(c_inliers, candidate.image_size),
        "reprojection_error": reprojection,
        "inverse_reprojection_error": inverse_error,
        "symmetric_error": symmetric,
        "homography": tuple(tuple(float(value) for value in row) for row in homography),
        **diagnostics,
    }
    return GeometricEvidence(**values, status="analyzed")


def reciprocal_rank_fusion(
    rankings: list[list[str]], *, constant: int = 60
) -> list[tuple[str, float]]:
    """Fuse heterogeneous rankings without mixing their raw score scales."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (constant + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
