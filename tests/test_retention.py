import json
from pathlib import Path

import pytest
from conftest import save_jpeg

from duplicate_lab.cli import main
from duplicate_lab.html_report import render_html
from duplicate_lab.retention import (
    RetentionPolicy,
    build_retention_report,
    load_retention_policy,
)
from duplicate_lab.scanner import scan


def _exact_group(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    for directory in ("camera", "edited", "backup seguro"):
        (source / directory).mkdir(parents=True)
    original = save_jpeg(patterned_image, source / "camera" / "IMG_á 01.jpg")
    for relative in ("edited/favorite.jpg", "backup seguro/copy.jpg"):
        (source / relative).write_bytes(original.read_bytes())
    return source, scan(source)


def test_preferred_directory_and_name_select_exact_duplicate(tmp_path: Path, patterned_image):
    source, result = _exact_group(tmp_path, patterned_image)
    policy = RetentionPolicy(
        preferred_directories=(Path("edited"),),
        preferred_name_patterns=(r"^favorite",),
    )

    recommendation = build_retention_report(result, source, policy).recommendations[0]

    assert recommendation.conclusion == "preferred"
    assert recommendation.selected.name == "favorite.jpg"
    assert not recommendation.operations_performed


def test_tie_conflict_protection_special_paths_and_determinism(tmp_path: Path, patterned_image):
    source, result = _exact_group(tmp_path, patterned_image)
    tie = build_retention_report(result, source, RetentionPolicy()).recommendations[0]
    conflict_policy = RetentionPolicy(
        preferred_directories=(Path("camera"),),
        preferred_name_patterns=(r"favorite",),
        protected_directories=(Path("backup seguro"),),
    )
    first = build_retention_report(result, source, conflict_policy)
    second = build_retention_report(result, source, conflict_policy)

    assert tie.conclusion == "tie"
    assert first == second
    assert first.recommendations[0].conclusion == "inconclusive"
    assert any("protegido" in item for item in first.recommendations[0].warnings)
    assert any("IMG_á 01.jpg" in str(path) for path in first.recommendations[0].others)


def test_location_priority_is_explicit_and_html_is_informative(tmp_path: Path, patterned_image):
    source, result = _exact_group(tmp_path, patterned_image)
    policy = RetentionPolicy(location_priority=(Path("backup seguro"), Path("camera")))
    report = build_retention_report(result, source, policy)

    document = render_html(result, retention_report=report)

    assert report.recommendations[0].selected.name == "copy.jpg"
    assert "recomendações de retenção" in document
    assert "Nenhuma operação" in document
    assert "copy.jpg" in document


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": 2},
        {"version": 1, "preferred_directories": ["../outside"]},
        {"version": 1, "preferred_name_patterns": ["["]},
        {"version": 1, "unknown": []},
        {"version": 1, "location_priority": ["camera", "camera"]},
    ],
)
def test_policy_configuration_validation(tmp_path: Path, payload: dict):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_retention_policy(path)


def test_policy_loader_and_source_files_remain_unchanged(tmp_path: Path, patterned_image):
    source, result = _exact_group(tmp_path, patterned_image)
    before = {path: path.read_bytes() for path in source.rglob("*.jpg")}
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "preferred_directories": ["camera"],
                "preferred_name_patterns": [],
                "location_priority": [],
                "protected_directories": ["backup seguro"],
            }
        ),
        encoding="utf-8",
    )

    build_retention_report(result, source, load_retention_policy(policy_path))

    assert {path: path.read_bytes() for path in source.rglob("*.jpg")} == before


def test_cli_rejects_retention_policy_for_non_html_report(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    save_jpeg(patterned_image, source / "photo.jpg")
    policy = tmp_path / "policy.json"
    policy.write_text('{"version": 1}', encoding="utf-8")

    exit_code = main(
        [
            "report",
            str(source),
            "--output-dir",
            str(tmp_path / "output"),
            "--format",
            "json",
            "--retention-policy",
            str(policy),
        ]
    )

    assert exit_code == 2
