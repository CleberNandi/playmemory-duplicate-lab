import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import save_jpeg

import duplicate_lab.hashing as hashing
from duplicate_lab.hashing import find_exact_groups, sha256_file
from duplicate_lab.inventory import build_inventory, file_identity
from duplicate_lab.models import PhotoRecord, ScanResult


def test_sha256_and_exact_group_for_different_names(tmp_path: Path, patterned_image):
    first = save_jpeg(patterned_image, tmp_path / "one.jpg")
    second = tmp_path / "two.jpeg"
    second.write_bytes(first.read_bytes())

    assert sha256_file(first) == sha256_file(second)
    groups = find_exact_groups(build_inventory(tmp_path))
    assert len(groups) == 1
    assert groups[0].redundant_files == 1
    assert groups[0].redundant_bytes == first.stat().st_size


def _record(path: Path) -> PhotoRecord:
    identity = file_identity(path.stat())
    return PhotoRecord(path.resolve(), identity.size, compatible=True, identity=identity)


def test_different_sizes_are_not_hashed(tmp_path: Path, monkeypatch):
    records = []
    for name, content in (("a.jpg", b"a"), ("b.jpg", b"bb")):
        path = tmp_path / name
        path.write_bytes(content)
        records.append(_record(path))
    calls = []
    monkeypatch.setattr(hashing, "sha256_file", lambda path, **kwargs: calls.append(path))

    assert find_exact_groups(tuple(records)) == ()
    assert calls == []


@pytest.mark.parametrize(
    ("contents", "expected_groups"),
    [((b"same", b"same"), 1), ((b"left", b"rite"), 0), ((b"", b""), 1)],
)
def test_same_size_candidates_are_hashed_and_compared(tmp_path: Path, contents, expected_groups):
    records = []
    for index, content in enumerate(contents):
        path = tmp_path / f"{index}.jpg"
        path.write_bytes(content)
        records.append(_record(path))

    assert len(find_exact_groups(tuple(records))) == expected_groups


def test_multiple_size_groups_only_hash_non_unique_sizes(tmp_path: Path, monkeypatch):
    contents = (b"a", b"bb", b"bb", b"ccc", b"xyz", b"123")
    records = []
    for index, content in enumerate(contents):
        path = tmp_path / f"{index}.jpg"
        path.write_bytes(content)
        records.append(_record(path))
    real_hash = hashing.sha256_file
    processed = []

    def counted(path, **kwargs):
        processed.append((path.name, path.stat().st_size))
        return real_hash(path, **kwargs)

    monkeypatch.setattr(hashing, "sha256_file", counted)
    groups = find_exact_groups(tuple(records))

    assert [tuple(path.name for path in group.paths) for group in groups] == [("1.jpg", "2.jpg")]
    assert len(processed) == 5
    assert sum(size for _, size in processed) == 13


def test_removed_after_inventory_is_an_error(tmp_path: Path):
    path = tmp_path / "gone.jpg"
    path.write_bytes(b"same")
    records = (_record(path),)
    path.unlink()

    with pytest.raises(FileNotFoundError):
        find_exact_groups(records)


def test_changed_between_inventory_and_hashing_is_an_error(tmp_path: Path):
    paths = (tmp_path / "a.jpg", tmp_path / "b.jpg")
    for path in paths:
        path.write_bytes(b"same")
    records = tuple(_record(path) for path in paths)
    paths[1].write_bytes(b"diff")

    with pytest.raises(OSError, match="alterado desde o inventário"):
        find_exact_groups(records)


def test_detectable_change_during_hashing_is_an_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "changing.jpg"
    path.write_bytes(b"payload")
    real_fstat = os.fstat
    calls = 0

    def changed_fstat(fd):
        nonlocal calls
        result = real_fstat(fd)
        calls += 1
        if calls == 2:
            values = {name: getattr(result, name) for name in (
                "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"
            )}
            values["st_mtime_ns"] += 1
            return SimpleNamespace(**values)
        return result

    monkeypatch.setattr(hashing.os, "fstat", changed_fstat)
    with pytest.raises(OSError, match="durante o hashing"):
        sha256_file(path)


def test_read_failure_is_not_a_duplicate(tmp_path: Path, monkeypatch):
    paths = (tmp_path / "a.jpg", tmp_path / "b.jpg")
    for path in paths:
        path.write_bytes(b"same")
    records = tuple(_record(path) for path in paths)
    real_open = Path.open

    def failing_open(path, *args, **kwargs):
        if path == paths[1]:
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(PermissionError, match="denied"):
        find_exact_groups(records)


def test_group_and_path_order_is_deterministic(tmp_path: Path):
    records = []
    inputs = (
        ("z.jpg", b"one"),
        ("b.jpg", b"two"),
        ("a.jpg", b"two"),
        ("y.jpg", b"one"),
    )
    for name, content in inputs:
        path = tmp_path / name
        path.write_bytes(content)
        records.append(_record(path))

    forward = find_exact_groups(tuple(records))
    reverse = find_exact_groups(tuple(reversed(records)))

    assert forward == reverse
    assert all(group.paths == tuple(sorted(group.paths, key=str)) for group in forward)


def test_exact_group_report_contract_does_not_expose_identity(tmp_path: Path):
    paths = (tmp_path / "a.jpg", tmp_path / "b.jpg")
    for path in paths:
        path.write_bytes(b"same")
    records = tuple(_record(path) for path in paths)
    result = ScanResult(records, find_exact_groups(records), ())

    payload = result.to_dict()
    assert set(payload) == {"summary", "inventory", "exact_groups", "pairs"}
    assert set(payload["inventory"][0]) == {
        "path", "size_bytes", "width", "height", "format", "exif_orientation",
        "compatible", "error",
    }
    assert set(payload["exact_groups"][0]) == {
        "sha256", "paths", "redundant_files", "redundant_bytes",
    }
