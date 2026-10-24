"""Exact-only snapshots and review plans. No photo mutation operations exist here."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from duplicate_lab.hashing import find_exact_groups, sha256_file
from duplicate_lab.inventory import file_identity, normalize_extensions
from duplicate_lab.models import ExactGroup, PhotoRecord, ScanResult
from duplicate_lab.retention import RetentionPolicy, build_retention_report


def seal(payload: dict) -> dict:
    """Checksum detects accidental edits, not malicious changes or authorization."""
    payload = {key: value for key, value in payload.items() if key != "id"}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    return {**payload, "id": hashlib.sha256(encoded).hexdigest()}


def load_artifact(path: Path, kind: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != kind or payload.get("version") != 1:
        raise ValueError(f"Artefato inválido: esperado {kind} v1")
    if seal(payload)["id"] != payload.get("id"):
        raise ValueError("Checksum inválido; regenere o artefato")
    return payload


def member_path(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts or rel.as_posix() != relative:
        raise ValueError("Caminho de membro inválido")
    path = root.joinpath(*rel.parts)
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError(f"Symlink bloqueado: {relative}")
    return path


def snapshot(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Membro não é arquivo regular")
    return {**asdict(file_identity(info)), "nlink": info.st_nlink}


def checked_hash(path: Path, expected: dict) -> str:
    if snapshot(path) != expected:
        raise ValueError("Arquivo alterado desde o inventário")
    digest = sha256_file(path, expected_identity=file_identity(path.lstat()))
    if snapshot(path) != expected:
        raise ValueError("Arquivo alterado durante leitura")
    return digest


def exact_scan(directory: Path, extensions=None) -> dict:
    # Reject symlink ancestors before resolving; preserve lexical membership.
    root = Path(os.path.abspath(directory))
    member_path(root.parent, root.name)
    if not root.is_dir():
        raise ValueError("Acervo inválido")
    allowed = normalize_extensions(extensions)
    records, excluded = [], []

    def walk_error(error):
        raise error

    for folder, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        for name in sorted(dirs + names):
            path = Path(folder) / name
            if path.is_symlink():
                excluded.append({"path": path.relative_to(root).as_posix(), "reason": "symlink"})
        dirs[:] = sorted(name for name in dirs if not (Path(folder) / name).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if path.is_symlink() or path.suffix.lower() not in allowed:
                continue
            member_path(root, path.relative_to(root).as_posix())
            record = {"path": path.relative_to(root).as_posix(), "identity": snapshot(path)}
            records.append(record)
    # Reuse the established size-prefilter + SHA-256 detector. Here compatible
    # means an eligible regular binary file, not a decoded/validated JPEG.
    photos = tuple(
        PhotoRecord(
            root / r["path"],
            r["identity"]["size"],
            compatible=True,
            identity=file_identity((root / r["path"]).lstat()),
        )
        for r in records
    )
    exact_groups = find_exact_groups(photos)
    groups = []
    for group in exact_groups:
        members = sorted(p.relative_to(root).as_posix() for p in group.paths)
        groups.append({"sha256": group.sha256, "members": members})
    for record in records:
        path = member_path(root, record["path"])
        if snapshot(path) != record["identity"]:
            raise ValueError("Arquivo alterado durante o scan")
    return seal(
        {
            "kind": "exact-scan",
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "root": str(root),
            "extensions": sorted(allowed),
            "inventory": sorted(records, key=lambda r: r["path"]),
            "excluded": excluded,
            "groups": groups,
        }
    )


def _inside(relative: str, directories) -> bool:
    parent = PurePosixPath(relative).parent
    return any(parent == directory or directory in parent.parents for directory in directories)


def _dependencies(path: Path) -> list[str]:
    # Conservative heuristic, not a complete catalogue/sidecar resolver.
    return sorted(
        p.name
        for p in path.parent.iterdir()
        if p != path
        and (
            p.stem.casefold() == path.stem.casefold()
            or p.name.casefold().startswith(path.name.casefold() + ".")
        )
    )


def build_plan(
    scan: dict,
    quarantine: Path,
    policy: RetentionPolicy | None = None,
    decisions: dict | None = None,
    *,
    dependencies_reviewed: bool = False,
) -> dict:
    if seal(scan)["id"] != scan.get("id") or scan.get("kind") != "exact-scan":
        raise ValueError("Snapshot inválido")
    root = Path(scan["root"])
    destination = Path(os.path.abspath(quarantine))
    member_path(destination.parent, destination.name)
    if destination == root or root in destination.parents or destination in root.parents:
        raise ValueError("Quarentena deve ser separada e não sobrepor o acervo")
    if destination.exists() and not destination.is_dir():
        raise ValueError("Quarentena não é diretório")
    policy = policy or RetentionPolicy()
    decisions = decisions or {}
    if set(decisions) - {g["sha256"] for g in scan["groups"]}:
        raise ValueError("Decisão menciona grupo desconhecido")
    records = {r["path"]: r for r in scan["inventory"]}
    exact_groups = tuple(
        ExactGroup(g["sha256"], tuple(root / p for p in g["members"]), 0, 0) for g in scan["groups"]
    )
    # Only feed lexical, in-root paths to the existing recommendation contract.
    groups = []
    for index, group in enumerate(scan["groups"]):
        blockers, members = [], []
        digest = group["sha256"]
        for relative in group["members"]:
            record = records[relative]
            protected = _inside(relative, policy.protected_directories)
            member = {**record, "protected": protected, "dependencies": []}
            try:
                path = member_path(root, relative)
                if checked_hash(path, record["identity"]) != digest:
                    raise ValueError("Conteúdo diverge do scan")
                member["dependencies"] = _dependencies(path)
                if member["dependencies"]:
                    blockers.append(f"dependencies:{relative}")
                if record["identity"]["nlink"] != 1:
                    blockers.append(f"hardlink:{relative}")
            except (OSError, ValueError) as exc:
                blockers.append(f"stale:{relative}:{exc}")
            members.append(member)
        keep, reason, choice = None, None, "unresolved"
        decision = decisions.get(digest)
        if decision is not None:
            if (
                not isinstance(decision, dict)
                or set(decision) != {"keep", "reason"}
                or decision["keep"] not in group["members"]
                or not isinstance(decision["reason"], str)
                or not decision["reason"].strip()
            ):
                raise ValueError("Decisão exige keep do grupo e reason não vazio")
            keep, reason, choice = decision["keep"], decision["reason"], "human"
        elif not blockers:
            result = ScanResult((), (exact_groups[index],), ())
            recommendation = build_retention_report(result, root, policy).recommendations[0]
            if recommendation.selected:
                keep = recommendation.selected.relative_to(root).as_posix()
                reason = "; ".join(recommendation.criteria)
                choice = "configured_rule"
        if keep is None:
            blockers.append("keep_unresolved")
        if not dependencies_reviewed:
            blockers.append("catalogue_dependencies_not_reviewed")
        candidates = []
        for member in members:
            if keep is None or member["path"] == keep or member["protected"]:
                continue
            target = destination / digest / member["path"]
            try:
                member_path(destination, target.relative_to(destination).as_posix())
                if os.path.lexists(target) or any(
                    p.exists() and not p.is_dir() for p in target.parents
                ):
                    blockers.append(f"destination_conflict:{member['path']}")
            except (OSError, ValueError) as exc:
                blockers.append(f"destination_blocked:{member['path']}:{exc}")
            candidates.append({"source": member["path"], "destination": str(target)})
        if not candidates:
            blockers.append("no_candidates")
        groups.append(
            {
                "sha256": digest,
                "members": members,
                "keep": keep,
                "choice": choice,
                "reason": reason,
                "candidates": candidates,
                "blockers": sorted(set(blockers)),
                "status": "blocked" if blockers else "ready_for_review",
            }
        )
    return seal(
        {
            "kind": "exact-plan",
            "version": 1,
            "scan": scan,
            "quarantine": str(destination),
            "policy": {k: [str(v) for v in values] for k, values in asdict(policy).items()},
            "decisions": decisions,
            "dependencies_reviewed": dependencies_reviewed,
            "groups": groups,
            "action_authorized": False,
            "operations_performed": False,
        }
    )


def revalidate_plan(plan: dict) -> dict:
    if seal(plan)["id"] != plan.get("id") or plan.get("kind") != "exact-plan":
        raise ValueError("Plano inválido")
    raw = plan["policy"]
    policy = RetentionPolicy(
        tuple(PurePosixPath(v) for v in raw["preferred_directories"]),
        tuple(raw["preferred_name_patterns"]),
        tuple(PurePosixPath(v) for v in raw["location_priority"]),
        tuple(PurePosixPath(v) for v in raw["protected_directories"]),
    )
    current = build_plan(
        plan["scan"],
        Path(plan["quarantine"]),
        policy,
        plan["decisions"],
        dependencies_reviewed=plan["dependencies_reviewed"],
    )
    return {
        "plan_id": plan["id"],
        "unchanged": current == plan,
        "ready_for_review": bool(current["groups"])
        and all(g["status"] == "ready_for_review" for g in current["groups"]),
        "groups": current["groups"],
        "action_authorized": False,
    }


def write_artifact(payload: dict, output: Path, source: Path) -> None:
    target = Path(os.path.abspath(output))
    member_path(target.parent, target.name)
    root = source.resolve()
    if target == root or root in target.parents:
        raise ValueError("Artefato deve ficar fora do acervo")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
