from pathlib import Path

from conftest import save_jpeg

from duplicate_lab.hashing import find_exact_groups, sha256_file
from duplicate_lab.inventory import build_inventory


def test_sha256_and_exact_group_for_different_names(tmp_path: Path, patterned_image):
    first = save_jpeg(patterned_image, tmp_path / "one.jpg")
    second = tmp_path / "two.jpeg"
    second.write_bytes(first.read_bytes())

    assert sha256_file(first) == sha256_file(second)
    groups = find_exact_groups(build_inventory(tmp_path))
    assert len(groups) == 1
    assert groups[0].redundant_files == 1
    assert groups[0].redundant_bytes == first.stat().st_size
