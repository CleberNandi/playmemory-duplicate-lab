from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from PIL import Image

from duplicate_lab.benchmark_copydays import (
    GROUND_TRUTH_SOURCE,
    JPEG_LEVELS,
    build_manifest,
    calculate_metrics,
    run_benchmark,
    safe_extract_archive,
    validate_tar_members,
    write_benchmark_reports,
)


def _image(path: Path, color: tuple[int, int, int] = (30, 60, 90)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path, format="JPEG")


def _dataset(root: Path) -> None:
    for name in ("200000.jpg", "200100.jpg"):
        _image(root / "original" / name)
        for quality in JPEG_LEVELS:
            _image(root / "jpegqual" / str(quality) / name)


def test_manifest_matches_complete_jpeg_blocks(tmp_path: Path) -> None:
    _dataset(tmp_path)
    manifest = build_manifest(tmp_path)
    assert len(manifest) == 18
    assert manifest[0].capture_id == "200000"
    assert manifest[0].parameter == "3"
    assert all(item.ground_truth_source == GROUND_TRUTH_SOURCE for item in manifest)


def test_manifest_rejects_incomplete_block(tmp_path: Path) -> None:
    _dataset(tmp_path)
    (tmp_path / "jpegqual" / "75" / "200100.jpg").unlink()
    with pytest.raises(ValueError, match="incompleto"):
        build_manifest(tmp_path)


def test_strong_prefix_must_resolve_unambiguously(tmp_path: Path) -> None:
    _dataset(tmp_path)
    _image(tmp_path / "original" / "200001.jpg")
    for quality in JPEG_LEVELS:
        _image(tmp_path / "jpegqual" / str(quality) / "200001.jpg")
    _image(tmp_path / "strong" / "200002.jpg")
    with pytest.raises(ValueError, match="ambíguo"):
        build_manifest(tmp_path, include_strong=True)


def test_metrics_keep_retrieval_and_pair_classification_separate() -> None:
    rows = [
        {
            "expected_original": "a",
            "expected_rank": 1,
            "expected_is_candidate": True,
            "expected_is_confirmed": True,
            "confirmed_count": 2,
            "error": None,
        },
        {
            "expected_original": "b",
            "expected_rank": 5,
            "expected_is_candidate": False,
            "expected_is_confirmed": False,
            "confirmed_count": 0,
            "error": None,
        },
        {
            "expected_original": "c",
            "expected_rank": None,
            "expected_is_candidate": False,
            "expected_is_confirmed": False,
            "confirmed_count": 1,
            "error": None,
        },
        {
            "expected_original": "d",
            "expected_rank": None,
            "expected_is_candidate": False,
            "expected_is_confirmed": False,
            "confirmed_count": 0,
            "error": "decode",
        },
    ]
    metrics = calculate_metrics(rows)
    assert metrics["denominator"] == 3
    assert metrics["recall_at_1"] == pytest.approx(1 / 3)
    assert metrics["recall_at_5"] == pytest.approx(2 / 3)
    assert metrics["mrr"] == pytest.approx((1 + 1 / 5) / 3)
    assert metrics["false_positives"] == 2
    assert metrics["false_negatives"] == 2
    assert metrics["decode_failure_rate"] == pytest.approx(1 / 4)


def test_query_without_ground_truth_is_excluded_from_denominator() -> None:
    rows = [
        {
            "expected_original": None,
            "expected_rank": None,
            "expected_is_candidate": False,
            "expected_is_confirmed": False,
            "confirmed_count": 1,
            "error": None,
        }
    ]
    assert calculate_metrics(rows)["denominator"] == 0


def test_retrieval_ties_are_deterministic_and_false_positives_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dataset(tmp_path)

    class EqualHash:
        def __sub__(self, other: object) -> int:
            return 0

    monkeypatch.setattr(
        "duplicate_lab.benchmark_copydays.oriented_phashes",
        lambda path: (EqualHash(),) * 4,
    )
    monkeypatch.setattr(
        "duplicate_lab.benchmark_copydays.structural_metrics",
        lambda *args: (1.0, 0.0),
    )
    result = run_benchmark(tmp_path, max_queries=2, comparison_side=64)
    assert result["queries"][1]["expected_rank"] == 2
    assert result["queries"][1]["top_1"].endswith("200000.jpg")
    assert result["metrics"]["false_positives"] == 2


def test_query_read_error_is_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _dataset(tmp_path)

    class EqualHash:
        def __sub__(self, other: object) -> int:
            return 0

    def hashes(path: Path) -> tuple[EqualHash, ...]:
        if "jpegqual" in path.parts:
            raise OSError("synthetic read failure")
        return (EqualHash(),) * 4

    monkeypatch.setattr("duplicate_lab.benchmark_copydays.oriented_phashes", hashes)
    result = run_benchmark(tmp_path, max_queries=1)
    assert result["metrics"]["decode_failures"] == 1
    assert result["queries"][0]["error"] == "query: synthetic read failure"


def _tar(path: Path, name: str, *, symlink: bool = False) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        info = tarfile.TarInfo(name)
        if symlink:
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            bundle.addfile(info)
        else:
            payload = b"jpeg"
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))


@pytest.mark.parametrize("name", ["../escape.jpg", "/absolute.jpg"])
def test_tar_validation_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    _tar(archive, name)
    with pytest.raises(ValueError, match="inseguro"):
        validate_tar_members(archive)


def test_tar_validation_rejects_links(tmp_path: Path) -> None:
    archive = tmp_path / "link.tar.gz"
    _tar(archive, "link", symlink=True)
    with pytest.raises(ValueError, match="insegura"):
        validate_tar_members(archive)


def test_safe_extraction_never_overwrites(tmp_path: Path) -> None:
    archive = tmp_path / "safe.tar.gz"
    _tar(archive, "original/image.jpg")
    destination = tmp_path / "output"
    safe_extract_archive(archive, destination)
    assert (destination / "original" / "image.jpg").read_bytes() == b"jpeg"
    with pytest.raises(FileExistsError):
        safe_extract_archive(archive, destination)


def test_reports_are_reproducible_and_never_overwritten(tmp_path: Path) -> None:
    row = {
        "query": "q.jpg",
        "top_1": "o.jpg",
        "expected_rank": 1,
        "expected_distance": 0,
        "expected_is_confirmed": True,
        "incorrect_confirmed": [],
        "error": None,
    }
    result = {"queries": [row], "counts": {}, "metrics": {}, "timing": {}, "memory": {}}
    targets = write_benchmark_reports(result, tmp_path / "reports")
    assert [path.name for path in targets] == [
        "copydays-benchmark.json",
        "copydays-queries.csv",
        "copydays-summary.html",
    ]
    with pytest.raises(FileExistsError):
        write_benchmark_reports(result, tmp_path / "reports")
