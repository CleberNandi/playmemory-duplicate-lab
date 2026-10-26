"""Linux, same-device reversible quarantine for trusted local review artifacts."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

from duplicate_lab.exact_plan import (
    _dependencies,
    checked_hash,
    member_path,
    revalidate_plan,
    seal,
    snapshot,
)


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError("Schema inválido: campos inesperados ou ausentes")


def _absolute(value):
    if not isinstance(value, str) or str(Path(value)) != value or not Path(value).is_absolute():
        raise ValueError("Caminho absoluto canônico exigido")
    member_path(Path(value).parent, Path(value).name)
    return Path(value)


def _validate_plan(plan):
    """Validate complete v1 shape before deriving any executable paths."""
    _keys(
        plan,
        "kind version scan quarantine policy decisions dependencies_reviewed groups "
        "action_authorized operations_performed id",
    )
    if (
        plan["kind"] != "exact-plan"
        or type(plan["version"]) is not int
        or plan["version"] != 1
        or seal(plan) != plan
        or plan["action_authorized"] is not False
        or plan["operations_performed"] is not False
        or plan["dependencies_reviewed"] is not True
    ):
        raise ValueError("Plano não elegível")
    scan = plan["scan"]
    _keys(scan, "kind version created_at root extensions inventory excluded groups id")
    if (
        scan["kind"] != "exact-scan"
        or type(scan["version"]) is not int
        or scan["version"] != 1
        or seal(scan) != scan
    ):
        raise ValueError("Scan inválido")
    root, quarantine = _absolute(scan["root"]), _absolute(plan["quarantine"])
    if root == quarantine or root in quarantine.parents or quarantine in root.parents:
        raise ValueError("Raízes sobrepostas")
    _keys(
        plan["policy"],
        "preferred_directories preferred_name_patterns location_priority protected_directories",
    )
    for values in plan["policy"].values():
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError("Política inválida")
    for value in (scan["inventory"], scan["excluded"], scan["groups"], plan["groups"]):
        if not isinstance(value, list):
            raise ValueError("Listas exigidas pelo schema")
    records = {}
    for record in scan["inventory"]:
        _keys(record, "path identity")
        member_path(root, record["path"])
        _keys(record["identity"], "device inode size mtime_ns ctime_ns nlink")
        if record["path"] in records or any(
            type(v) is not int or v < 0 for v in record["identity"].values()
        ):
            raise ValueError("Inventário inválido")
        records[record["path"]] = record
    if not isinstance(scan["created_at"], str) or not isinstance(scan["extensions"], list):
        raise ValueError("Scan inválido")
    for excluded in scan["excluded"]:
        _keys(excluded, "path reason")
        # Excluded entries may themselves be symlinks; never used for actions.
        if not isinstance(excluded["path"], str) or excluded["reason"] != "symlink":
            raise ValueError("Exclusão inválida")
    groups = {}
    seen = set()
    for group in scan["groups"]:
        _keys(group, "sha256 members")
        digest = group["sha256"]
        if (
            not isinstance(digest, str)
            or not re.fullmatch("[0-9a-f]{64}", digest)
            or digest in groups
            or not isinstance(group["members"], list)
            or len(group["members"]) < 2
        ):
            raise ValueError("Grupo inválido")
        for path in group["members"]:
            if path not in records or path in seen:
                raise ValueError("Membro repetido ou desconhecido")
            seen.add(path)
        groups[digest] = group
    if not isinstance(plan["decisions"], dict):
        raise ValueError("Decisões inválidas")
    for digest, decision in plan["decisions"].items():
        _keys(decision, "keep reason")
        if digest not in groups or decision["keep"] not in groups[digest]["members"]:
            raise ValueError("Decisão inválida")
        if not isinstance(decision["reason"], str) or not decision["reason"].strip():
            raise ValueError("Motivo inválido")
    if not plan["groups"] or len(plan["groups"]) != len(groups):
        raise ValueError("Plano vazio/inconsistente")
    actions = []
    for group in plan["groups"]:
        _keys(group, "sha256 members keep choice reason candidates blockers status")
        digest = group["sha256"]
        original = groups.pop(digest, None)
        if (
            original is None
            or group["status"] != "ready_for_review"
            or group["blockers"] != []
            or group["keep"] not in original["members"]
        ):
            raise ValueError("Grupo bloqueado/inconsistente")
        if (
            group["choice"] not in ("human", "configured_rule")
            or not isinstance(group["reason"], str)
            or not group["reason"].strip()
            or not isinstance(group["members"], list)
            or not isinstance(group["candidates"], list)
        ):
            raise ValueError("Revisão inválida")
        members = {}
        for m in group["members"]:
            _keys(m, "path identity protected dependencies")
            if (
                m["path"] not in original["members"]
                or m["path"] in members
                or m["identity"] != records[m["path"]]["identity"]
                or type(m["protected"]) is not bool
                or m["dependencies"] != []
                or m["identity"]["nlink"] != 1
            ):
                raise ValueError("Membro inválido")
            members[m["path"]] = m
        if set(members) != set(original["members"]):
            raise ValueError("Membros inconsistentes")
        expected = [
            p for p in original["members"] if p != group["keep"] and not members[p]["protected"]
        ]
        if len(group["candidates"]) != len(expected) or not expected:
            raise ValueError("Candidatos inconsistentes")
        for candidate, path in zip(group["candidates"], expected, strict=True):
            _keys(candidate, "source destination")
            destination = str(quarantine / digest / path)
            if candidate != {"source": path, "destination": destination}:
                raise ValueError("Destino/candidato inválido")
            actions.append(
                {
                    "source": str(root / path),
                    "destination": destination,
                    "keep": str(root / group["keep"]),
                    "sha256": digest,
                    "identity": members[path]["identity"],
                    "keep_identity": members[group["keep"]]["identity"],
                }
            )
    return actions


def validate_plan(plan):
    try:
        return _validate_plan(plan)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("Schema do plano inválido") from exc


def load_execution_artifact(path, kind):
    """Reject ambiguous JSON, duplicate keys and excessive input before schema checks."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Chave JSON duplicada")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Constante JSON inválida")

    with Path(path).open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Artefato excede limite de 16 MiB")
    try:
        payload = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
        if not isinstance(payload, dict) or payload.get("kind") != kind or seal(payload) != payload:
            raise ValueError("Artefato inválido")
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("JSON inválido") from exc
    return payload


def authorize(plan, confirmed_id):
    actions = validate_plan(plan)
    if confirmed_id != plan["id"]:
        raise ValueError("Confirme o ID exato do plano")
    result = revalidate_plan(plan)
    if not result["unchanged"] or not result["ready_for_review"]:
        raise ValueError("Plano alterado ou bloqueado")
    return seal(
        {
            "kind": "exact-authorization",
            "version": 1,
            "plan_id": plan["id"],
            "actions": actions,
            "scope": "move-and-restore-same-filesystem",
            "exclusive_access_acknowledged": True,
        }
    )


def _sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _rename(source, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    if fn is None:
        raise ValueError("renameat2 indisponível; nenhum fallback destrutivo")
    if fn(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    _sync(source.parent)
    _sync(destination.parent)


def _verify(path, identity, digest, *, relocated=False):
    member_path(path.parent, path.name)
    actual = snapshot(path)
    fields = ("device", "inode", "size", "mtime_ns", "nlink") if relocated else tuple(identity)
    if any(actual[k] != identity[k] for k in fields) or actual["nlink"] != 1:
        raise ValueError("Identidade alterada")
    if checked_hash(path, actual) != digest:
        raise ValueError("Conteúdo alterado")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if _dependencies(path):
        raise ValueError("Dependências detectadas")


def execute(plan, authorization, *, restore=False, fault=None):
    """Resume using durable intents. fault is a synthetic-test interruption hook."""
    if sys.platform != "linux":
        raise ValueError("Somente Linux suportado")
    actions = validate_plan(plan)
    _keys(authorization, "kind version plan_id actions scope exclusive_access_acknowledged id")
    expected = seal(
        {
            "kind": "exact-authorization",
            "version": 1,
            "plan_id": plan["id"],
            "actions": actions,
            "scope": "move-and-restore-same-filesystem",
            "exclusive_access_acknowledged": True,
        }
    )
    if authorization != expected:
        raise ValueError("Autorização inválida")
    root, q = Path(plan["scan"]["root"]), Path(plan["quarantine"])
    # Directory locks coordinate Lab processes without creating a file in the collection.
    lock = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    db = None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not q.is_dir():
            if restore:
                raise ValueError("Quarentena ausente")
            q.mkdir(mode=0o700, parents=True)
            _sync(q.parent)
        member_path(q.parent, q.name)
        if q.stat().st_uid != os.geteuid() or q.stat().st_mode & 0o022:
            raise ValueError("Quarentena deve pertencer ao operador, sem escrita de terceiros")
        if q.stat().st_dev != root.stat().st_dev:
            raise ValueError("Filesystems distintos bloqueados")
        journal = q / (".exact-" + plan["id"] + ".sqlite3")
        member_path(q, journal.name)
        fresh = not os.path.lexists(journal)
        temporary = None
        if fresh:
            if restore:
                raise ValueError("Journal ausente")
            current = revalidate_plan(plan)
            if not current["unchanged"] or not current["ready_for_review"]:
                raise ValueError("Plano alterado/bloqueado")
            for a in actions:
                if Path(a["source"]).stat().st_dev != q.stat().st_dev:
                    raise ValueError("Filesystems distintos bloqueados")
            fd, name = tempfile.mkstemp(prefix=".exact-bootstrap-", dir=q)
            temporary = Path(name)
            os.close(fd)
        elif not journal.is_file() or journal.stat().st_nlink != 1:
            raise ValueError("Journal inválido")
        db = sqlite3.connect(temporary if fresh else journal)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        if fresh:
            db.executescript(
                "CREATE TABLE manifest (value TEXT NOT NULL); "
                "CREATE TABLE actions "
                "(number INTEGER PRIMARY KEY, state TEXT NOT NULL); "
                "CREATE TABLE events (number INTEGER, event TEXT, detail TEXT);"
            )
            db.execute("INSERT INTO manifest VALUES (?)", (json.dumps(expected, sort_keys=True),))
            db.executemany(
                "INSERT INTO actions VALUES (?, ?)", [(i, "pending") for i in range(len(actions))]
            )
            db.commit()
            db.close()
            db = None
            _rename(temporary, journal)
            db = sqlite3.connect(journal)
            db.execute("PRAGMA synchronous=FULL")
        manifests = db.execute("SELECT value FROM manifest").fetchall()
        if manifests != [(json.dumps(expected, sort_keys=True),)]:
            raise ValueError("Journal não corresponde à autorização")
        rows = db.execute("SELECT number,state FROM actions ORDER BY number").fetchall()
        if [i for i, _ in rows] != list(range(len(actions))):
            raise ValueError("Journal incompleto")

        if not restore and any(state in ("restore_intent", "restored") for _, state in rows):
            raise ValueError("Sessão em restauração/encerrada; gere novo plano")

        def record(i, state):
            db.execute("UPDATE actions SET state=? WHERE number=?", (state, i))
            db.execute("INSERT INTO events (number,event,detail) VALUES (?, ?, ?)", (i, state, ""))
            db.commit()
            if fault:
                fault(state, i)

        for i, state in rows:
            a = actions[i]
            src, dst = Path(a["source"]), Path(a["destination"])
            try:
                if state not in ("pending", "move_intent", "moved", "restore_intent", "restored"):
                    raise ValueError("Estado de journal desconhecido")
                _verify(Path(a["keep"]), a["keep_identity"], a["sha256"])
                if not restore and state in ("restore_intent", "restored"):
                    raise ValueError("Sessão em restauração/encerrada; gere novo plano")
                if restore and state == "pending":
                    if os.path.lexists(dst):
                        raise ValueError("Destino inesperado para ação pendente")
                    _verify(src, a["identity"], a["sha256"])
                    record(i, "restored")
                    continue
                if restore and state == "restored":
                    _verify(src, a["identity"], a["sha256"], relocated=True)
                    if os.path.lexists(dst):
                        raise ValueError("Destino inesperado após restauração")
                    continue
                if state == "move_intent":
                    if os.path.lexists(src) and not os.path.lexists(dst):
                        _verify(src, a["identity"], a["sha256"])
                        if restore:
                            record(i, "restored")
                            continue
                    elif not os.path.lexists(src) and os.path.lexists(dst):
                        _verify(dst, a["identity"], a["sha256"], relocated=True)
                        _sync(src.parent)
                        _sync(dst.parent)
                        record(i, "moved")
                        state = "moved"
                    else:
                        raise ValueError("Movimentação ambígua; intervenção necessária")
                if state == "restore_intent" and not os.path.lexists(dst):
                    _verify(src, a["identity"], a["sha256"], relocated=True)
                    _sync(src.parent)
                    _sync(dst.parent)
                    record(i, "restored")
                    continue
                if restore:
                    _verify(dst, a["identity"], a["sha256"], relocated=True)
                    if os.path.lexists(src):
                        raise ValueError("Origem ocupada; restauração bloqueada")
                    member_path(src.parent, src.name)
                    if not src.parent.is_dir() or src.parent.stat().st_dev != dst.stat().st_dev:
                        raise ValueError("Pasta original ausente ou filesystem alterado")
                    if _dependencies(src):
                        raise ValueError("Dependências na origem de restauração")
                    record(i, "restore_intent")
                    _rename(dst, src)
                    if fault:
                        fault("after_restore_rename", i)
                    _verify(src, a["identity"], a["sha256"], relocated=True)
                    record(i, "restored")
                elif state == "moved":
                    _verify(dst, a["identity"], a["sha256"], relocated=True)
                    if os.path.lexists(src):
                        raise ValueError("Origem reapareceu após movimentação")
                else:
                    _verify(src, a["identity"], a["sha256"])
                    member_path(dst.parent, dst.name)
                    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    # Persist every new directory entry before an intent can rename into it.
                    for parent in (dst.parent, *dst.parent.parents):
                        _sync(parent)
                        if parent == q:
                            break
                    if dst.parent.stat().st_dev != src.stat().st_dev:
                        raise ValueError("Filesystems distintos bloqueados")
                    if os.path.lexists(dst):
                        raise FileExistsError(errno.EEXIST, "Destino ocupado")
                    record(i, "move_intent")
                    _verify(Path(a["keep"]), a["keep_identity"], a["sha256"])
                    _verify(src, a["identity"], a["sha256"])
                    _rename(src, dst)
                    if fault:
                        fault("after_move_rename", i)
                    _verify(dst, a["identity"], a["sha256"], relocated=True)
                    record(i, "moved")
                _verify(Path(a["keep"]), a["keep_identity"], a["sha256"])
            except (OSError, ValueError) as exc:
                db.execute(
                    "INSERT INTO events (number,event,detail) VALUES (?, ?, ?)",
                    (i, "failure", str(exc)),
                )
                db.commit()
                raise
        return {
            "journal": str(journal),
            "actions": db.execute("SELECT number,state FROM actions ORDER BY number").fetchall(),
        }
    except sqlite3.Error as exc:
        raise ValueError("Journal inválido/indisponível; preserve-o para recuperação") from exc
    finally:
        if db is not None:
            db.close()
        os.close(lock)
