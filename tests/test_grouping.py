from pathlib import Path

from conftest import save_jpeg

from duplicate_lab.scanner import scan


def test_exact_groups_do_not_merge_transitively(tmp_path: Path, patterned_image):
    first = save_jpeg(patterned_image, tmp_path / "a.jpg")
    (tmp_path / "b.jpg").write_bytes(first.read_bytes())
    save_jpeg(patterned_image, tmp_path / "c.jpg", quality=80)

    result = scan(tmp_path)

    assert len(result.exact_groups) == 1
    assert {path.name for path in result.exact_groups[0].paths} == {"a.jpg", "b.jpg"}
    assert any(pair.classification == "exact_duplicate" for pair in result.pairs)
    assert any(
        pair.classification in {"similar_image", "visual_candidate"} for pair in result.pairs
    )
