"""Deterministic ORB matching and conservative geometric verification."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class ORBConfig:
    max_side: int = 1024
    nfeatures: int = 1200
    scale_factor: float = 1.2
    nlevels: int = 8
    fast_threshold: int = 20
    ratio_threshold: float = 0.75
    min_filtered_matches: int = 8
    min_inliers: int = 8
    min_inlier_ratio: float = 0.35
    min_spatial_coverage: float = 0.02
    ransac_reprojection_threshold: float = 4.0
    max_reprojection_error: float = 5.0
    seed: int = 202503

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Features:
    path: Path
    image_size: tuple[int, int]
    keypoints: np.ndarray
    descriptors: np.ndarray | None
    extraction_seconds: float
    error: str | None = None

    @property
    def keypoint_count(self) -> int:
        return len(self.keypoints)


@dataclass(frozen=True)
class MatchResult:
    raw_matches: int
    filtered_matches: int
    distances: tuple[float, ...]
    query_coverage: float
    candidate_coverage: float
    inliers: int
    inlier_ratio: float
    reprojection_error: float | None
    matching_seconds: float
    ransac_seconds: float
    status: str
    confirmed: bool

    @property
    def score(self) -> tuple[float, ...]:
        """Higher is better; deterministic path ordering resolves exact ties externally."""
        median = float(np.median(self.distances)) if self.distances else 256.0
        return (float(self.inliers), self.inlier_ratio, float(self.filtered_matches), -median)


def load_grayscale(path: Path, max_side: int) -> np.ndarray:
    """Read with EXIF orientation and aspect-preserving bounded resize."""
    if max_side <= 0:
        raise ValueError("max_side must be positive")
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L")
        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return np.ascontiguousarray(np.asarray(image, dtype=np.uint8))


def extract_features(path: Path, config: ORBConfig) -> Features:
    started = time.perf_counter()
    try:
        gray = load_grayscale(path, config.max_side)
        cv2.setRNGSeed(config.seed)
        detector = cv2.ORB_create(
            nfeatures=config.nfeatures,
            scaleFactor=config.scale_factor,
            nlevels=config.nlevels,
            fastThreshold=config.fast_threshold,
        )
        keypoints, descriptors = detector.detectAndCompute(gray, None)
        points = np.asarray([point.pt for point in keypoints], dtype=np.float32).reshape(-1, 2)
        if descriptors is not None:
            descriptors = np.ascontiguousarray(descriptors)
        return Features(
            path, (gray.shape[1], gray.shape[0]), points, descriptors, time.perf_counter() - started
        )
    except (OSError, ValueError, cv2.error) as exc:
        return Features(
            path,
            (0, 0),
            np.empty((0, 2), dtype=np.float32),
            None,
            time.perf_counter() - started,
            str(exc),
        )


def _coverage(points: np.ndarray, indices: list[int], size: tuple[int, int]) -> float:
    if len(indices) < 2 or not size[0] or not size[1]:
        return 0.0
    selected = points[indices]
    extent = np.ptp(selected, axis=0)
    return float((extent[0] * extent[1]) / (size[0] * size[1]))


def _empty(status: str, matching_seconds: float = 0.0) -> MatchResult:
    return MatchResult(0, 0, (), 0.0, 0.0, 0, 0.0, None, matching_seconds, 0.0, status, False)


def match_features(query: Features, candidate: Features, config: ORBConfig) -> MatchResult:
    """Apply two-neighbour Lowe ratio filtering, then homography RANSAC."""
    started = time.perf_counter()
    if query.error or candidate.error:
        return _empty("decode_error", time.perf_counter() - started)
    if query.descriptors is None or candidate.descriptors is None:
        return _empty("no_descriptors", time.perf_counter() - started)
    if len(query.descriptors) < 2 or len(candidate.descriptors) < 2:
        return _empty("insufficient_descriptors", time.perf_counter() - started)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    try:
        neighbours = matcher.knnMatch(query.descriptors, candidate.descriptors, k=2)
    except cv2.error:
        return _empty("matching_error", time.perf_counter() - started)
    good = [
        pair[0]
        for pair in neighbours
        if len(pair) == 2 and pair[0].distance < config.ratio_threshold * pair[1].distance
    ]
    matching_seconds = time.perf_counter() - started
    q_indices = [item.queryIdx for item in good]
    c_indices = [item.trainIdx for item in good]
    q_coverage = _coverage(query.keypoints, q_indices, query.image_size)
    c_coverage = _coverage(candidate.keypoints, c_indices, candidate.image_size)
    distances = tuple(float(item.distance) for item in good)
    if len(good) < config.min_filtered_matches:
        return MatchResult(
            len(neighbours),
            len(good),
            distances,
            q_coverage,
            c_coverage,
            0,
            0.0,
            None,
            matching_seconds,
            0.0,
            "insufficient_matches",
            False,
        )
    if min(q_coverage, c_coverage) < config.min_spatial_coverage:
        return MatchResult(
            len(neighbours),
            len(good),
            distances,
            q_coverage,
            c_coverage,
            0,
            0.0,
            None,
            matching_seconds,
            0.0,
            "concentrated_matches",
            False,
        )
    source = query.keypoints[q_indices].reshape(-1, 1, 2)
    target = candidate.keypoints[c_indices].reshape(-1, 1, 2)
    ransac_started = time.perf_counter()
    cv2.setRNGSeed(config.seed)
    homography, mask = cv2.findHomography(
        source, target, cv2.RANSAC, config.ransac_reprojection_threshold
    )
    ransac_seconds = time.perf_counter() - ransac_started
    if homography is None or mask is None or not np.isfinite(homography).all():
        return MatchResult(
            len(neighbours),
            len(good),
            distances,
            q_coverage,
            c_coverage,
            0,
            0.0,
            None,
            matching_seconds,
            ransac_seconds,
            "invalid_homography",
            False,
        )
    determinant = float(np.linalg.det(homography[:2, :2]))
    condition = float(np.linalg.cond(homography))
    if abs(determinant) < 1e-8 or not math.isfinite(condition) or condition > 1e10:
        return MatchResult(
            len(neighbours),
            len(good),
            distances,
            q_coverage,
            c_coverage,
            0,
            0.0,
            None,
            matching_seconds,
            ransac_seconds,
            "degenerate_homography",
            False,
        )
    inlier_mask = mask.ravel().astype(bool)
    inliers = int(inlier_mask.sum())
    ratio = inliers / len(good)
    projected = cv2.perspectiveTransform(source, homography)
    errors = np.linalg.norm(projected.reshape(-1, 2) - target.reshape(-1, 2), axis=1)
    reprojection_error = float(np.median(errors[inlier_mask])) if inliers else None
    confirmed = bool(
        inliers >= config.min_inliers
        and ratio >= config.min_inlier_ratio
        and reprojection_error is not None
        and reprojection_error <= config.max_reprojection_error
    )
    status = "geometric_match" if confirmed else "insufficient_geometric_evidence"
    return MatchResult(
        len(neighbours),
        len(good),
        distances,
        q_coverage,
        c_coverage,
        inliers,
        ratio,
        reprojection_error,
        matching_seconds,
        ransac_seconds,
        status,
        confirmed,
    )
