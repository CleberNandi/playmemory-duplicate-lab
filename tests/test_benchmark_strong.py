from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from duplicate_lab.benchmark_strong import (
    _evaluate,
    build_strong_manifest,
    confirmation_tradeoffs,
    generate_controlled_negatives,
    scenario_metrics,
    threshold_tradeoffs,
    validate_negative_sets,
)
from duplicate_lab.hashing import sha256_file


def _image(path: Path, value: int = 50) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), (value, value, value)).save(path)


def _strong_dataset(root: Path) -> None:
    for index in range(157):
        _image(root / "original" / f"{index:04d}00.jpg", index % 255)
    # 72 identities have a second query: 157 + 72 = 229.
    for index in range(157):
        _image(root / "strong" / f"{index:04d}01.jpg", index % 255)
    for index in range(72):
        _image(root / "strong" / f"{index:04d}02.jpg", index % 255)


def _row(*, expected: str | None, confirmed: int, truth: bool, error: str | None = None):
    return {
        "expected_original": expected,
        "expected_rank": 1 if expected else None,
        "expected_is_candidate": truth,
        "expected_is_confirmed": truth,
        "confirmed_count": confirmed,
        "error": error,
    }


def test_strong_ground_truth_and_multiple_queries_per_original(tmp_path: Path) -> None:
    _strong_dataset(tmp_path)
    manifest = build_strong_manifest(tmp_path)
    assert len(manifest) == 229
    assert len({entry.original for entry in manifest}) == 157
    assert sum(entry.capture_id == "0000" for entry in manifest) == 2


def test_strong_ground_truth_rejects_ambiguous_prefix(tmp_path: Path) -> None:
    _strong_dataset(tmp_path)
    (tmp_path / "original" / "015600.jpg").unlink()
    _image(tmp_path / "original" / "000099.jpg")
    with pytest.raises(ValueError, match="ambíguo"):
        build_strong_manifest(tmp_path)


def test_controlled_distractors_are_deterministic_and_disjoint(tmp_path: Path) -> None:
    first = generate_controlled_negatives(tmp_path / "db", count=4, namespace="db", side=64)
    digests = [sha256_file(path) for path in first]
    second = generate_controlled_negatives(tmp_path / "db", count=4, namespace="db", side=64)
    queries = generate_controlled_negatives(
        tmp_path / "queries", count=3, namespace="query", side=64
    )
    assert [sha256_file(path) for path in second] == digests
    validation = validate_negative_sets((), first, queries)
    assert validation["classification"] == "verified"
    assert validation["exact_collisions"] == 0


def test_negative_metrics_count_queries_not_pairs() -> None:
    rows = [
        _row(expected=None, confirmed=2, truth=False),
        _row(expected=None, confirmed=0, truth=False),
        _row(expected=None, confirmed=1, truth=False, error="decode"),
    ]
    metrics = scenario_metrics(rows)
    assert metrics["negative_queries"] == 2
    assert metrics["negative_queries_with_false_confirmation"] == 1
    assert metrics["false_positive_rate"] == pytest.approx(0.5)
    assert metrics["false_acceptance_rate"] == pytest.approx(0.5)


def test_false_positive_and_false_negative_denominators() -> None:
    rows = [
        _row(expected="a", confirmed=2, truth=True),
        _row(expected="b", confirmed=0, truth=False),
    ]
    metrics = scenario_metrics(rows)
    assert metrics["pair_precision"] == pytest.approx(0.5)
    assert metrics["pair_recall"] == pytest.approx(0.5)
    assert metrics["false_confirmed_pairs"] == 1
    assert metrics["false_negatives"] == 1


def test_top_k_and_ties_are_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    query = tmp_path / "query.png"
    database = tuple(tmp_path / name for name in ("b.png", "a.png", "c.png"))
    for path in (query, *database):
        _image(path)

    class EqualHash:
        def __sub__(self, other: object) -> int:
            return 0

    monkeypatch.setattr(
        "duplicate_lab.benchmark_strong.oriented_phashes", lambda path: (EqualHash(),) * 4
    )
    monkeypatch.setattr(
        "duplicate_lab.benchmark_strong.structural_metrics", lambda *args: (0.0, 1.0)
    )
    result = _evaluate(
        name="test",
        queries=(query,),
        database=database,
        expected={query: database[0]},
        root=tmp_path,
        comparison_side=64,
    )
    row = result["queries"][0]
    assert row["top_1"] == "a.png"
    assert row["expected_rank"] == 2
    assert result["metrics"]["recall_at_1"] == 0
    assert result["metrics"]["recall_at_5"] == 1


def test_threshold_analysis_keeps_default_separate() -> None:
    rows = [
        {
            "expected_original": "a",
            "pairs_within_analysis_limit": [
                {
                    "distance": 9,
                    "is_expected": True,
                    "default_confirmed": True,
                }
            ],
        },
        {
            "expected_original": None,
            "pairs_within_analysis_limit": [
                {
                    "distance": 13,
                    "is_expected": False,
                    "default_confirmed": True,
                }
            ],
        },
    ]
    table = {row["phash_threshold"]: row for row in threshold_tradeoffs(rows)}
    assert table[8]["recall"] == 0
    assert table[12]["recall"] == 1
    assert table[12]["false_positive_rate"] == 0
    assert table[16]["false_positive_rate"] == 1
    confirmation = confirmation_tradeoffs(rows)
    assert [row["ssim_threshold"] for row in confirmation] == [0.75, 0.80, 0.85]


def test_benchmark_evaluation_does_not_modify_source_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    query, original = tmp_path / "query.png", tmp_path / "original.png"
    _image(query, 10)
    _image(original, 20)
    before = {path: sha256_file(path) for path in (query, original)}
    monkeypatch.setattr(
        "duplicate_lab.benchmark_strong.structural_metrics", lambda *args: (0.0, 1.0)
    )
    _evaluate(
        name="test",
        queries=(query,),
        database=(original,),
        expected={query: original},
        root=tmp_path,
        comparison_side=64,
    )
    assert {path: sha256_file(path) for path in before} == before
