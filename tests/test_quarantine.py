import copy
import os
from pathlib import Path

import pytest

from duplicate_lab.cli import main
from duplicate_lab.exact_plan import build_plan, exact_scan, seal, write_artifact
from duplicate_lab.quarantine import authorize, execute
from duplicate_lab.retention import RetentionPolicy


def fixture(tmp_path):
    root = tmp_path / "collection"
    root.mkdir()
    (root / "protected").mkdir()
    for name in ("protected/keep.jpg", "copy1.jpg", "copy2.jpg"):
        (root / name).write_bytes(b"synthetic content")
    scan = exact_scan(root)
    plan = build_plan(
        scan,
        tmp_path / "quarantine",
        RetentionPolicy(protected_directories=(Path("protected"),)),
        {scan["groups"][0]["sha256"]: {"keep": "protected/keep.jpg", "reason": "synthetic review"}},
        dependencies_reviewed=True,
    )
    return root, plan, authorize(plan, plan["id"])


def test_cycle(tmp_path):
    root, plan, auth = fixture(tmp_path)
    result = execute(plan, auth)
    assert [s for _, s in result["actions"]] == ["moved", "moved"]
    assert (root / "protected/keep.jpg").read_bytes() == b"synthetic content"
    for a in auth["actions"]:
        assert not Path(a["source"]).exists()
        assert Path(a["destination"]).read_bytes() == b"synthetic content"
    assert execute(plan, auth) == result
    assert [s for _, s in execute(plan, auth, restore=True)["actions"]] == ["restored"] * 2
    execute(plan, auth, restore=True)
    for a in auth["actions"]:
        assert Path(a["source"]).read_bytes() == b"synthetic content"
        assert not Path(a["destination"]).exists()
    with pytest.raises(ValueError):
        execute(plan, auth)


@pytest.mark.parametrize(
    "event",
    [
        "move_intent",
        "after_move_rename",
        "moved",
        "restore_intent",
        "after_restore_rename",
        "restored",
    ],
)
def test_interrupt_resume(tmp_path, event):
    root, plan, auth = fixture(tmp_path)

    def interrupt(state, number):
        if state == event and number == 0:
            raise KeyboardInterrupt()

    restoring = event.startswith("restore") or event == "after_restore_rename"
    if restoring:
        execute(plan, auth)
    with pytest.raises(KeyboardInterrupt):
        execute(plan, auth, restore=restoring, fault=interrupt)
    execute(plan, auth, restore=restoring)
    execute(plan, auth, restore=True)
    assert len(list(root.rglob("*.jpg"))) == 3


@pytest.mark.parametrize("path", ["protected/keep.jpg", "copy1.jpg"])
@pytest.mark.parametrize("mutation", ["change", "remove", "symlink", "hardlink", "sidecar"])
def test_stale(tmp_path, path, mutation):
    root, plan, auth = fixture(tmp_path)
    file = root / path
    if mutation == "change":
        file.write_bytes(b"changed")
    elif mutation == "remove":
        file.unlink()
    elif mutation == "symlink":
        file.unlink()
        file.symlink_to(tmp_path / "missing")
    elif mutation == "hardlink":
        os.link(file, tmp_path / "hardlink")
    else:
        file.with_suffix(".xmp").write_text("sidecar")
    with pytest.raises((ValueError, OSError)):
        execute(plan, auth)
    assert (root / "copy2.jpg").exists()


@pytest.mark.parametrize("conflict", ["file", "broken-link", "directory"])
def test_destination_conflict(tmp_path, conflict):
    root, plan, auth = fixture(tmp_path)
    target = Path(auth["actions"][0]["destination"])
    target.parent.mkdir(parents=True)
    if conflict == "file":
        target.write_bytes(b"occupied")
    elif conflict == "broken-link":
        target.symlink_to(tmp_path / "missing")
    else:
        target.mkdir()
    with pytest.raises((ValueError, OSError)):
        execute(plan, auth)
    assert (root / "copy1.jpg").exists()


def test_restore_conflict(tmp_path):
    root, plan, auth = fixture(tmp_path)
    execute(plan, auth)
    (root / "copy1.jpg").write_bytes(b"new occupant")
    with pytest.raises(ValueError):
        execute(plan, auth, restore=True)
    assert (root / "copy1.jpg").read_bytes() == b"new occupant"
    assert Path(auth["actions"][0]["destination"]).exists()
    (root / "copy1.jpg").unlink()
    execute(plan, auth, restore=True)


def test_unauthorized_malformed(tmp_path):
    root, plan, auth = fixture(tmp_path)
    with pytest.raises(ValueError):
        authorize(plan, "wrong")
    with pytest.raises(ValueError):
        execute(plan, {**auth, "actions": []})
    modified = copy.deepcopy(plan)
    modified["groups"][0]["candidates"][0]["destination"] = str(tmp_path / "unexpected")
    with pytest.raises(ValueError):
        execute(seal(modified), auth)
    with pytest.raises(ValueError):
        execute(seal({**plan, "unknown": True}), auth)
    assert (root / "copy1.jpg").exists()


def test_cross_filesystem(tmp_path):
    import shutil
    import tempfile

    if not Path("/dev/shm").is_dir() or Path("/dev/shm").stat().st_dev == tmp_path.stat().st_dev:
        pytest.skip("second filesystem unavailable")
    root, plan, _ = fixture(tmp_path)
    q = Path(tempfile.mkdtemp(prefix="duplicate-lab-test-", dir="/dev/shm"))
    try:
        plan = seal({**plan, "quarantine": str(q)})
        scan = exact_scan(root)
        plan = build_plan(scan, q, decisions=plan["decisions"], dependencies_reviewed=True)
        auth = authorize(plan, plan["id"])
        with pytest.raises(ValueError, match="Filesystems"):
            execute(plan, auth)
        assert (root / "copy1.jpg").exists()
    finally:
        shutil.rmtree(q)


def test_cli_cycle(tmp_path):
    root, plan, _ = fixture(tmp_path)
    planfile, authfile = tmp_path / "plan.json", tmp_path / "auth.json"
    write_artifact(plan, planfile, root)
    assert (
        main(
            [
                "exact-authorize",
                str(planfile),
                "--confirm-plan-id",
                plan["id"],
                "--exclusive-access",
                "--output",
                str(authfile),
            ]
        )
        == 0
    )
    for command in ("exact-quarantine", "exact-restore"):
        assert main([command, str(planfile), "--authorization", str(authfile)]) == 0


def test_partial_failure_restore_pending(tmp_path):
    root, plan, auth = fixture(tmp_path)

    def fail(state, number):
        if state == "moved" and number == 0:
            (root / "copy2.jpg").unlink()
            (root / "copy2.jpg").write_bytes(b"replacement")

    with pytest.raises(ValueError):
        execute(plan, auth, fault=fail)
    assert not (root / "copy1.jpg").exists()
    # Restore the valid completed action; block the altered pending action.
    with pytest.raises(ValueError):
        execute(plan, auth, restore=True)
    assert (root / "copy1.jpg").read_bytes() == b"synthetic content"
    assert (root / "copy2.jpg").read_bytes() == b"replacement"


def test_racing_destination_no_overwrite(tmp_path, monkeypatch):
    from duplicate_lab import quarantine

    root, plan, auth = fixture(tmp_path)
    original = quarantine._rename

    def race(source, target):
        if source == root / "copy1.jpg":
            target.symlink_to(tmp_path / "absent")
        return original(source, target)

    monkeypatch.setattr(quarantine, "_rename", race)
    with pytest.raises(FileExistsError):
        execute(plan, auth)
    assert (root / "copy1.jpg").read_bytes() == b"synthetic content"
    assert Path(auth["actions"][0]["destination"]).is_symlink()


@pytest.mark.parametrize("code", [13, 28, 5])
def test_io_failure_before_rename(tmp_path, monkeypatch, code):
    from duplicate_lab import quarantine

    root, plan, auth = fixture(tmp_path)
    original = quarantine._rename

    def fail(source, target):
        if source == root / "copy1.jpg":
            raise OSError(code, "synthetic I/O failure")
        return original(source, target)

    monkeypatch.setattr(quarantine, "_rename", fail)
    with pytest.raises(OSError):
        execute(plan, auth)
    monkeypatch.setattr(quarantine, "_rename", original)
    execute(plan, auth)
    execute(plan, auth, restore=True)


def test_concurrent_lab_lock(tmp_path):
    import fcntl

    root, plan, auth = fixture(tmp_path)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            execute(plan, auth)
        assert (root / "copy1.jpg").exists()
    finally:
        os.close(fd)


@pytest.mark.parametrize("raw", ['{"kind":"a","kind":"b"}', '{"kind":NaN}', "[]"])
def test_strict_json(tmp_path, raw):
    from duplicate_lab.quarantine import load_execution_artifact

    path = tmp_path / "malformed.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        load_execution_artifact(path, "exact-plan")


def test_restore_broken_link_conflict(tmp_path):
    root, plan, auth = fixture(tmp_path)
    execute(plan, auth)
    (root / "copy1.jpg").symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        execute(plan, auth, restore=True)
    assert Path(auth["actions"][0]["destination"]).exists()


def test_restore_sidecar_conflict(tmp_path):
    root, plan, auth = fixture(tmp_path)
    execute(plan, auth)
    (root / "copy1.xmp").write_text("new dependency")
    with pytest.raises(ValueError):
        execute(plan, auth, restore=True)
    assert Path(auth["actions"][0]["destination"]).exists()


@pytest.mark.parametrize(
    "boundary", ["move_intent", "after_move_rename", "restore_intent", "after_restore_rename"]
)
def test_abrupt_process_exit(tmp_path, boundary):
    import subprocess
    import sys

    root, plan, auth = fixture(tmp_path)
    if "restore" in boundary:
        execute(plan, auth)
    planfile, authfile = tmp_path / "plan.json", tmp_path / "auth.json"
    write_artifact(plan, planfile, root)
    write_artifact(auth, authfile, root)
    code = """
import os, sys
from pathlib import Path
from duplicate_lab.quarantine import execute, load_execution_artifact
plan = load_execution_artifact(Path(sys.argv[1]), 'exact-plan')
auth = load_execution_artifact(Path(sys.argv[2]), 'exact-authorization')
def crash(state, number):
    if state == sys.argv[3] and number == 0:
        os._exit(77)
execute(plan, auth, restore='restore' in sys.argv[3], fault=crash)
"""
    result = subprocess.run([sys.executable, "-c", code, str(planfile), str(authfile), boundary])
    assert result.returncode == 77
    execute(plan, auth, restore="restore" in boundary)
    execute(plan, auth, restore=True)
    assert len(list(root.rglob("*.jpg"))) == 3
