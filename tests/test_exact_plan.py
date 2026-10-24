"""Behavioral checks using disposable binary files; no real photographs."""

import json
import os
from pathlib import Path, PurePosixPath

import pytest

from duplicate_lab.cli import main
from duplicate_lab.exact_plan import (
    build_plan,
    exact_scan,
    load_artifact,
    revalidate_plan,
    write_artifact,
)
from duplicate_lab.retention import RetentionPolicy


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "photos"
    for relative, data in {
        "reference/a.jpg": b"same",
        "incoming/renamed.jpg": b"same",
        "third/a.jpg": b"same",
        "different/a.jpg": b"else",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def selected(scan):
    return {scan["groups"][0]["sha256"]: {"keep": "reference/a.jpg", "reason": "Catalogued path"}}


def plan_for(root, tmp_path, **kwargs):
    scan = exact_scan(root)
    return build_plan(
        scan,
        tmp_path / "quarantine",
        decisions=selected(scan),
        dependencies_reviewed=True,
        **kwargs,
    )


def test_binary_groups_and_review_only(corpus, tmp_path):
    original = {str(p): p.read_bytes() for p in corpus.rglob("*.jpg")}
    scan = exact_scan(corpus)
    assert len(scan["inventory"]) == 4
    assert scan["groups"][0]["members"] == [
        "incoming/renamed.jpg",
        "reference/a.jpg",
        "third/a.jpg",
    ]
    plan = plan_for(corpus, tmp_path)
    group = plan["groups"][0]
    assert group["status"] == "ready_for_review"
    assert group["keep"] == "reference/a.jpg"
    assert len(group["candidates"]) == 2
    assert not plan["action_authorized"] and not plan["operations_performed"]
    assert revalidate_plan(plan)["unchanged"]
    assert not (tmp_path / "quarantine").exists()
    assert original == {str(p): p.read_bytes() for p in corpus.rglob("*.jpg")}


def test_no_implicit_winner_or_dependency_clearance(corpus, tmp_path):
    plan = build_plan(exact_scan(corpus), tmp_path / "quarantine")
    assert plan["groups"][0]["keep"] is None
    assert "keep_unresolved" in plan["groups"][0]["blockers"]
    assert "catalogue_dependencies_not_reviewed" in plan["groups"][0]["blockers"]


def test_protected_member_never_candidate_and_policy_unchanged(corpus, tmp_path):
    policy = RetentionPolicy(
        preferred_directories=(PurePosixPath("reference"),),
        protected_directories=(PurePosixPath("third"),),
    )
    plan = build_plan(
        exact_scan(corpus), tmp_path / "quarantine", policy, dependencies_reviewed=True
    )
    group = plan["groups"][0]
    assert group["choice"] == "configured_rule"
    assert group["keep"] == "reference/a.jpg"
    assert [c["source"] for c in group["candidates"]] == ["incoming/renamed.jpg"]
    assert next(m for m in group["members"] if m["path"] == "third/a.jpg")["protected"]


@pytest.mark.parametrize("change", ["edit", "remove", "replace_symlink", "hardlink"])
def test_scan_and_plan_staleness(corpus, tmp_path, change):
    scan = exact_scan(corpus)
    plan = plan_for(corpus, tmp_path)
    path = corpus / "incoming/renamed.jpg"
    if change == "edit":
        path.write_bytes(b"else")  # Same size, different content.
    elif change == "remove":
        path.unlink()
    elif change == "replace_symlink":
        path.unlink()
        path.symlink_to(corpus / "reference/a.jpg")
    else:
        os.link(path, tmp_path / "another-link")
    group = build_plan(
        scan, tmp_path / "quarantine", decisions=selected(scan), dependencies_reviewed=True
    )["groups"][0]
    assert group["status"] == "blocked"
    assert any(b.startswith("stale:") for b in group["blockers"])
    assert not revalidate_plan(plan)["unchanged"]
    assert not revalidate_plan(plan)["ready_for_review"]


def test_links_excluded_or_blocked(corpus, tmp_path):
    (corpus / "alias.jpg").symlink_to(corpus / "reference/a.jpg")
    (corpus / "alias-dir").symlink_to(corpus / "reference", target_is_directory=True)
    (corpus / "broken.jpg").symlink_to(corpus / "missing")
    os.link(corpus / "third/a.jpg", corpus / "hard.jpg")
    scan = exact_scan(corpus)
    assert {r["path"] for r in scan["excluded"]} == {"alias.jpg", "alias-dir", "broken.jpg"}
    group = build_plan(
        scan, tmp_path / "quarantine", decisions=selected(scan), dependencies_reviewed=True
    )["groups"][0]
    assert "hardlink:hard.jpg" in group["blockers"]
    assert "hardlink:third/a.jpg" in group["blockers"]


@pytest.mark.parametrize("dependency", ["renamed.xmp", "renamed.jpg.xmp"])
def test_sidecars_block_even_after_human_ack(corpus, tmp_path, dependency):
    (corpus / "incoming" / dependency).write_text("metadata")
    assert (
        "dependencies:incoming/renamed.jpg" in plan_for(corpus, tmp_path)["groups"][0]["blockers"]
    )


@pytest.mark.parametrize("conflict", ["file", "directory", "broken_link", "parent_file"])
def test_destination_conflicts(corpus, tmp_path, conflict):
    plan = plan_for(corpus, tmp_path)
    target = Path(plan["groups"][0]["candidates"][0]["destination"])
    target.parent.mkdir(parents=True)
    if conflict == "file":
        target.write_bytes(b"do not overwrite")
    elif conflict == "directory":
        target.mkdir()
    elif conflict == "broken_link":
        target.symlink_to(tmp_path / "absent")
    else:
        target.parent.rmdir()
        target.parent.write_text("obstruction")
    result = revalidate_plan(plan)
    assert not result["unchanged"] and not result["ready_for_review"]
    assert result["groups"][0]["status"] == "blocked"


def test_conflicting_policy_and_invalid_human_choice(corpus, tmp_path):
    scan = exact_scan(corpus)
    policy = RetentionPolicy(
        preferred_directories=(PurePosixPath("reference"),), preferred_name_patterns=("renamed",)
    )
    assert build_plan(scan, tmp_path / "q", policy)["groups"][0]["keep"] is None
    decision = {scan["groups"][0]["sha256"]: {"keep": "different/a.jpg", "reason": "wrong"}}
    with pytest.raises(ValueError):
        build_plan(scan, tmp_path / "q", decisions=decision)


def test_artifact_no_overwrite_checksum_and_overlap(corpus, tmp_path):
    scan = exact_scan(corpus)
    output = tmp_path / "scan.json"
    write_artifact(scan, output, corpus)
    assert load_artifact(output, "exact-scan") == scan
    with pytest.raises(FileExistsError):
        write_artifact(scan, output, corpus)
    with pytest.raises(ValueError):
        write_artifact(scan, corpus / "report.json", corpus)
    with pytest.raises(ValueError):
        build_plan(scan, corpus / "q")
    with pytest.raises(ValueError):
        build_plan(scan, corpus.parent)
    scan["root"] = "changed"
    output.write_text(json.dumps(scan))
    with pytest.raises(ValueError, match="Checksum"):
        load_artifact(output, "exact-scan")


def test_cli_roundtrip(corpus, tmp_path, capsys):
    scan_file, plan_file = tmp_path / "scan.json", tmp_path / "plan.json"
    assert main(["exact-scan", str(corpus), "--output", str(scan_file)]) == 0
    scan = load_artifact(scan_file, "exact-scan")
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps(selected(scan)))
    assert (
        main(
            [
                "exact-plan",
                str(scan_file),
                "--decisions",
                str(decisions),
                "--quarantine-dir",
                str(tmp_path / "q"),
                "--output",
                str(plan_file),
                "--dependencies-reviewed",
            ]
        )
        == 0
    )
    assert main(["exact-check", str(plan_file)]) == 0
    (corpus / "reference/a.jpg").unlink()
    assert main(["exact-check", str(plan_file)]) == 2
    assert "false" in capsys.readouterr().out


def test_all_protected_and_unresolved_have_no_candidates(corpus, tmp_path):
    policy = RetentionPolicy(protected_directories=(PurePosixPath("."),))
    plan = plan_for(corpus, tmp_path, policy=policy)
    assert plan["groups"][0]["candidates"] == []
    assert "no_candidates" in plan["groups"][0]["blockers"]
    unresolved = build_plan(exact_scan(corpus), tmp_path / "q")
    assert unresolved["groups"][0]["candidates"] == []


def test_symlink_roots_and_artifact_targets_rejected(corpus, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(corpus, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        exact_scan(alias)
    output = tmp_path / "output.json"
    target = tmp_path / "absent.json"
    output.symlink_to(target)
    with pytest.raises(ValueError, match="Symlink"):
        write_artifact(exact_scan(corpus), output, corpus)
    assert not target.exists()


def test_new_sidecar_stales_previously_reviewable_plan(corpus, tmp_path):
    plan = plan_for(corpus, tmp_path)
    (corpus / "reference/a.xmp").write_text("new dependency")
    result = revalidate_plan(plan)
    assert not result["unchanged"] and not result["ready_for_review"]
