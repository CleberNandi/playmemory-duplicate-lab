from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import duplicate_lab.benchmark_strong as strong_module
import duplicate_lab.experiments.benchmark_geometric_verification as benchmark_module
from duplicate_lab.benchmark_strong import build_strong_manifest
from duplicate_lab.experiments.benchmark_geometric_verification import (
    _decision,
    _evaluate_pairs,
    _natural_pairs,
    _split_distractors,
    audited_metrics,
    negative_query_metrics,
)
from duplicate_lab.experiments.benchmark_local_features import identity_partition
from duplicate_lab.experiments.geometric_verification import (
    GeometricEvidence,
    VerificationConfig,
    homography_diagnostics,
    mutual_ratio_matches,
    reciprocal_rank_fusion,
)


def _evidence(**changes: object) -> GeometricEvidence:
    values = {
        "raw_matches": 20,
        "ratio_matches": 12,
        "mutual_matches": 10,
        "median_distance": 12.0,
        "unique_train_ratio": 1.0,
        "inliers": 10,
        "inlier_ratio": 0.8,
        "query_coverage": 0.4,
        "candidate_coverage": 0.4,
        "inlier_query_coverage": 0.4,
        "inlier_candidate_coverage": 0.4,
        "query_grid_cells": 6,
        "candidate_grid_cells": 6,
        "reprojection_error": 1.0,
        "inverse_reprojection_error": 1.0,
        "symmetric_error": 1.0,
        "determinant": 1.0,
        "condition": 1.0,
        "scale_min": 1.0,
        "scale_max": 1.0,
        "shear_cosine": 0.0,
        "perspective": 0.0,
        "corner_area_ratio": 1.0,
        "homography": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        "degenerate": False,
        "plausible": True,
        "status": "analyzed",
    }
    values.update(changes)
    return GeometricEvidence(**values)  # type: ignore[arg-type]


def test_mutual_matching_removes_one_way_ratio_matches() -> None:
    query = np.zeros((3, 32), dtype=np.uint8)
    candidate = np.zeros((3, 32), dtype=np.uint8)
    query[1, 0], query[2, 0] = 1, 255
    candidate[1, 0], candidate[2, 0] = 3, 127
    forward, mutual = mutual_ratio_matches(query, candidate, 0.9)
    assert len(mutual) <= len(forward)
    assert {(item.queryIdx, item.trainIdx) for item in mutual} <= {
        (item.queryIdx, item.trainIdx) for item in forward
    }


def test_degenerate_and_implausible_homographies_are_rejected() -> None:
    config = VerificationConfig()
    degenerate = homography_diagnostics(np.zeros((3, 3)), (100, 100), (100, 100), config)
    extreme = homography_diagnostics(
        np.asarray([[20.0, 0, 0], [0, 20.0, 0], [0.01, 0, 1.0]]),
        (100, 100),
        (100, 100),
        config,
    )
    assert degenerate["degenerate"]
    assert not extreme["plausible"]


def test_repetitive_and_concentrated_evidence_is_not_selective() -> None:
    config = VerificationConfig()
    assert not _evidence(query_grid_cells=1, candidate_grid_cells=1).confirms_selective(config)
    repetitive = _evidence(unique_train_ratio=0.4)
    assert repetitive.confirms_selective(config)
    assert repetitive.unique_train_ratio < 0.85


def test_metrics_distinguish_pair_and_query_false_positive_rates() -> None:
    rows = [
        {
            "expected_original": "truth-a",
            "error": None,
            "database_count": 5,
            "current_rank": 1,
            "current_expected_candidate": True,
            "current_expected_confirmed": True,
            "current_confirmed_count": 3,
        },
        {
            "expected_original": "truth-b",
            "error": None,
            "database_count": 5,
            "current_rank": 2,
            "current_expected_candidate": True,
            "current_expected_confirmed": False,
            "current_confirmed_count": 1,
        },
    ]
    metrics = audited_metrics(rows, "current")
    assert metrics["false_positive_pairs"] == 3
    assert metrics["negative_pair_denominator"] == 8
    assert metrics["false_positive_rate_per_pair"] == pytest.approx(3 / 8)
    assert metrics["query_false_positive_rate"] == 1.0


def test_rank_fusion_is_scale_free_and_reproducible() -> None:
    first = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "c"]])
    second = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "c"]])
    assert first == second
    assert [name for name, _ in first[:2]] == ["a", "b"]


@pytest.mark.parametrize(
    ("homography", "config_change"),
    [
        (np.eye(3), {"max_condition": 0.5}),
        (np.eye(3), {"min_corner_area_ratio": 1.1}),
        (np.eye(3), {"max_corner_area_ratio": 0.9}),
        (np.asarray([[1.0, 0, 0], [0, 1.0, 0], [0.001, 0, 1.0]]), {"max_perspective": 0.0}),
        (np.eye(3), {"min_scale": 1.1}),
        (np.eye(3), {"max_scale": 0.9}),
        (np.asarray([[1.0, 0.4, 0], [0, 1.0, 0], [0, 0, 1.0]]), {"max_shear_cosine": 0.1}),
    ],
)
def test_each_homography_limit_is_configurable(
    homography: np.ndarray, config_change: dict[str, float]
) -> None:
    baseline = homography_diagnostics(homography, (100, 100), (100, 100), VerificationConfig())
    changed = homography_diagnostics(
        homography,
        (100, 100),
        (100, 100),
        VerificationConfig(**config_change),
    )
    assert baseline["plausible"]
    assert not changed["plausible"]


def test_mutual_semantics_are_shared_with_benchmark() -> None:
    config = VerificationConfig()
    evidence = _evidence(query_grid_cells=1, candidate_grid_cells=1)
    assert evidence.confirms_mutual(config)
    assert not evidence.confirms_selective(config)
    assert _decision(evidence, "mutual", config) == evidence.confirms_mutual(config)


def test_identity_partition_really_separates_capture_ids() -> None:
    identities = {f"capture-{index:03d}" for index in range(100)}
    calibration = {item for item in identities if identity_partition(item) == "calibration"}
    evaluation = {item for item in identities if identity_partition(item) == "test"}
    assert calibration.isdisjoint(evaluation)
    assert calibration | evaluation == identities
    assert calibration and evaluation


def test_natural_pairs_use_real_partition_and_distinct_ids(tmp_path: Path) -> None:
    paths = []
    for index in range(40):
        path = tmp_path / f"capture-{index:03d}.jpg"
        Image.new("RGB", (16, 16), (index * 5, index * 3, index)).save(path)
        paths.append(path)
    pairs = _natural_pairs(tuple(paths), "calibration", limit=12)
    assert pairs
    for left, right in pairs:
        assert left.stem != right.stem
        assert identity_partition(left.stem) == "calibration"
        assert identity_partition(right.stem) == "calibration"


def test_strong_ground_truth_maps_unique_capture_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    originals = tuple(Path("original") / f"{index:04d}00.jpg" for index in range(157))
    strong = tuple(Path("strong") / f"{index % 157:04d}{index + 1:02d}.jpg" for index in range(229))

    def fake_jpgs(directory: Path) -> tuple[Path, ...]:
        return originals if directory.name == "original" else strong

    monkeypatch.setattr(strong_module, "_jpgs", fake_jpgs)
    manifest = build_strong_manifest(Path("dataset"))
    assert len(manifest) == 229
    assert all(item.query.name[:4] == item.original.name[:4] for item in manifest)
    assert all(item.capture_id == item.query.name[:4] for item in manifest)


def test_strong_ground_truth_rejects_ambiguous_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    originals = [Path("original") / f"{index:04d}00.jpg" for index in range(157)]
    originals[-1] = Path("original/000099.jpg")
    strong = tuple(Path("strong") / f"{index % 157:04d}{index + 1:02d}.jpg" for index in range(229))
    monkeypatch.setattr(
        strong_module,
        "_jpgs",
        lambda directory: tuple(originals) if directory.name == "original" else strong,
    )
    with pytest.raises(ValueError, match="ambíguo"):
        build_strong_manifest(Path("dataset"))


def test_negative_query_denominator_is_separate() -> None:
    rows = [
        {"expected_original": None, "error": None, "mutual_confirmed_count": 2},
        {"expected_original": None, "error": None, "mutual_confirmed_count": 0},
        {"expected_original": "truth", "error": None, "mutual_confirmed_count": 1},
    ]
    metrics = negative_query_metrics(rows, "mutual")
    assert metrics == {
        "negative_query_denominator": 2,
        "negative_queries_accepted": 1,
        "negative_query_acceptance_rate": 0.5,
    }


def test_evidence_cache_invalidates_only_evidence_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_analyze(*args: object, **kwargs: object) -> GeometricEvidence:
        nonlocal calls
        calls += 1
        return _evidence()

    monkeypatch.setattr(benchmark_module, "analyze_pair", fake_analyze)
    left, right = Path("left.jpg"), Path("right.jpg")
    features = {left: object(), right: object()}
    cache: dict = {}
    _evaluate_pairs(((left, right),), features, VerificationConfig(), cache)
    _evaluate_pairs(((left, right),), features, VerificationConfig(min_inliers=99), cache)
    assert calls == 1
    _evaluate_pairs(((left, right),), features, VerificationConfig(seed=7), cache)
    _evaluate_pairs(((left, right),), features, VerificationConfig(ratio_threshold=0.7), cache)
    _evaluate_pairs(
        ((left, right),), features, VerificationConfig(ransac_reprojection_threshold=2.0), cache
    )
    assert calls == 4


def test_distractor_split_is_balanced_disjoint_and_reproducible() -> None:
    paths = tuple(Path(f"d-{index:03d}.png") for index in range(256))
    first = _split_distractors(paths)
    second = _split_distractors(paths)
    assert first == second
    assert len(first[0]) == len(first[1]) == 128
    assert set(first[0]).isdisjoint(first[1])


def test_direct_inverse_consistency_required() -> None:
    assert not _evidence(symmetric_error=8.0).confirms_selective(VerificationConfig())
