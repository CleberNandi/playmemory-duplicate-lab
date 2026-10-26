"""Run from the checkout: uv run python examples/synthetic_quarantine.py."""

import json
import tempfile
from pathlib import Path

from duplicate_lab.cli import main


def run(*args):
    if main(list(map(str, args))) != 0:
        raise RuntimeError("Synthetic demonstration failed")


with tempfile.TemporaryDirectory(prefix="duplicate-lab-synthetic-") as folder:
    base = Path(folder)
    collection = base / "collection"
    collection.mkdir()
    for name in ("keep.jpg", "copy-a.jpg", "copy-b.jpg"):
        (collection / name).write_bytes(b"synthetic bytes; not a real photograph")
    scan, plan = base / "scan.json", base / "plan.json"
    decisions, auth = base / "decisions.json", base / "authorization.json"
    run("exact-scan", collection, "--output", scan)
    digest = json.loads(scan.read_text())["groups"][0]["sha256"]
    decisions.write_text(json.dumps({digest: {"keep": "keep.jpg", "reason": "Synthetic review"}}))
    run(
        "exact-plan",
        scan,
        "--decisions",
        decisions,
        "--dependencies-reviewed",
        "--quarantine-dir",
        base / "quarantine",
        "--output",
        plan,
    )
    run("exact-check", plan)
    plan_id = json.loads(plan.read_text())["id"]
    run(
        "exact-authorize",
        plan,
        "--confirm-plan-id",
        plan_id,
        "--exclusive-access",
        "--output",
        auth,
    )
    run("exact-quarantine", plan, "--authorization", auth)
    assert sorted(p.name for p in collection.iterdir()) == ["keep.jpg"]
    assert (collection / "keep.jpg").read_bytes().startswith(b"synthetic bytes")
    print("MOVE VERIFIED: preserved path present; two candidates in quarantine")
    run("exact-restore", plan, "--authorization", auth)
    assert len(list(collection.iterdir())) == 3
    assert all(p.read_bytes().startswith(b"synthetic bytes") for p in collection.iterdir())
    print("RESTORE VERIFIED: three files at initial paths; content verified")
