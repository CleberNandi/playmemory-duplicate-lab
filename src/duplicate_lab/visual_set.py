"""Bounded discovery queue, independent from exact execution contracts."""

from __future__ import annotations

import html
import itertools
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from duplicate_lab.exact_plan import checked_hash, member_path, seal, snapshot
from duplicate_lab.hashing import oriented_phashes
from duplicate_lab.html_report import _thumbnail
from duplicate_lab.inventory import inspect_file
from duplicate_lab.visual_review import review_pair


def discover_set(
    root: Path, output: Path, max_files: int = 200, max_candidates: int = 100,
    *, collapse_exact: bool = False,
) -> dict:
    """Select all nonbinary pairs at existing pHash threshold 8, orientation zero only."""
    if not 1 <= max_files <= 200 or not 1 <= max_candidates <= 100:
        raise ValueError("Limites: 1..200 arquivos e 1..100 candidatos")
    root = Path(os.path.abspath(root))
    member_path(root.parent, root.name)
    if not root.is_dir():
        raise ValueError("Diretório inválido")
    output = Path(os.path.abspath(output))
    member_path(output.parent, output.name)
    if output == root or root in output.parents or output in root.parents:
        raise ValueError("Saída deve ficar fora do conjunto")
    if output.exists():
        raise FileExistsError(output)
    paths, excluded = [], []

    def fail(error):
        raise error

    for folder, dirs, names in os.walk(root, followlinks=False, onerror=fail):
        for name in sorted(dirs + names):
            path = Path(folder) / name
            if path.is_symlink():
                excluded.append({"path": str(path.relative_to(root)), "reason": "symlink"})
        dirs[:] = sorted(d for d in dirs if not (Path(folder) / d).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if path.is_symlink() or path.suffix.lower() not in {".jpg", ".jpeg"}:
                continue
            paths.append(path)
            if len(paths) > max_files:
                raise ValueError("Limite de arquivos excedido; selecione conjunto menor")
    files, hashes = [], []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        member_path(root, relative)
        identity = snapshot(path)
        record = inspect_file(path)
        if not record.compatible:
            excluded.append({"path": relative, "reason": record.error})
            continue
        digest = checked_hash(path, identity)
        hashes.append(oriented_phashes(path)[0])
        files.append({"path": relative, "identity": identity, "sha256": digest,
                      "width": record.width, "height": record.height})
    by_digest = defaultdict(list)
    for index, item in enumerate(files):
        by_digest[item['sha256']].append(index)
    content_groups = list(by_digest.values())
    groups = content_groups if collapse_exact else [[i] for i in range(len(files))]
    candidates = []
    location_pairs = 0
    for left_group, right_group in itertools.combinations(groups, 2):
        left, right = left_group[0], right_group[0]
        distance = int(hashes[left] - hashes[right])
        if files[left]["sha256"] == files[right]["sha256"] or distance > 8:
            continue
        location_pairs += len(left_group) * len(right_group)
        pair = {"id": f"pair-{left:03d}-{right:03d}", "left": left,
                "right": right, "phash_distance": distance}
        if collapse_exact:
            pair.update(left_members=left_group, right_members=right_group)
        candidates.append(pair)
    summary = {"valid_files": len(files), "unique_binary_contents": len(content_groups),
               "candidate_location_pairs": location_pairs,
               "review_candidates": len(candidates),
               "collapsed_location_pairs": location_pairs - len(candidates)}
    if len(candidates) > max_candidates:
        raise ValueError(
            f"Limite de candidatos excedido: {len(candidates)} revisões, "
            f"{location_pairs} pares de localizações; máximo {max_candidates}. "
            "Selecione conjunto menor; nada publicado"
        )
    candidates.sort(key=lambda p: (p["phash_distance"], p["id"]))
    previews = {i: _thumbnail(root / f["path"]) for i, f in enumerate(files)}
    if not all(previews.values()):
        raise ValueError("Falha ao gerar prévias")
    payload = seal({"kind": "visual-set-review", "version": 2 if collapse_exact else 1,
                    "created_at": datetime.now(UTC).isoformat(), "root": str(root),
                    "selection": {"phash_threshold": 8, "rotation_search": False,
                                  "max_files": max_files, "max_candidates": max_candidates},
                    "files": files, "excluded": excluded, "candidates": candidates,
                    "summary": summary,
                    "action_authorized": False, "capture_identity": "not_established"})
    if collapse_exact:
        payload = seal({**payload, "assessment_scope": "displayed_representatives_only"})
    cards = []
    for pair in candidates:
        figures = ''.join(
            f'<figure><img src="{previews[i]}" alt="Prévia"><figcaption>'
            f'{html.escape(files[i]["path"])} · {files[i]["width"]} × '
            f'{files[i]["height"]}</figcaption></figure>'
            for i in (pair['left'], pair['right'])
        )
        locations = ''
        if collapse_exact:
            for label, key in (("Esquerda", "left_members"), ("Direita", "right_members")):
                names = ''.join(f'<li>{html.escape(files[i]["path"])}</li>' for i in pair[key])
                locations += f'<details><summary>{label}: {len(pair[key])} localizações</summary>'
                locations += f'<ul>{names}</ul></details>'
        cards.append(f'<section><h2>{pair["id"]} · pHash {pair["phash_distance"]}</h2>'
                     f'{figures}{locations}</section>')
    document = ('<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
                '<title>Candidatos visuais</title><style>body{font:16px system-ui;'
                'max-width:1100px;margin:auto}figure{display:inline-block;max-width:45%;'
                'overflow-wrap:anywhere}img{max-width:100%}</style><h1>Candidatos visuais</h1>'
                '<p>Fila estática privada. Similaridade não prova mesma captura. '
                'Nenhuma ação autorizada. Use visual-set-pair com o ID para avaliar. '
                'Prévia reduzida; confira os arquivos integrais.</p>'
                f'<p>{len(files)} JPEGs válidos; {len(excluded)} exclusões; '
                f'{len(candidates)} candidatos. Fila: {payload["id"]}</p>'
                + f'<p>{location_pairs} pares de localizações; '
                f'{summary["collapsed_location_pairs"]} repetições binárias reunidas. '
                'Representante escolhido por ordem de caminho, sem preferência de preservação. '
                'Avaliação restrita aos representantes; sem propagação automática.</p>'
                + ''.join(cards) + '</html>')
    for item in files:
        path = member_path(root, item['path'])
        if checked_hash(path, item['identity']) != item['sha256']:
            raise ValueError("Conteúdo alterado")
    output.mkdir(parents=True, exist_ok=False)
    (output / 'queue.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    (output / 'gallery.html').write_text(document, encoding='utf-8')
    return payload


def review_set_pair(queue: dict, pair_id: str, output: Path,
                    decision: str = 'pending', reason: str = '') -> dict:
    if (queue.get('kind') != 'visual-set-review' or queue.get('version') not in (1, 2)
            or seal(queue)['id'] != queue.get('id')):
        raise ValueError('Fila inválida')
    pair = next((p for p in queue['candidates'] if p['id'] == pair_id), None)
    if pair is None:
        raise ValueError('ID de par inexistente')
    members = [queue['files'][pair[key]] for key in ('left', 'right')]
    root = Path(queue['root'])
    destination = Path(os.path.abspath(output))
    member_path(destination.parent, destination.name)
    if destination == root or root in destination.parents or destination in root.parents:
        raise ValueError('Saída deve ficar fora do conjunto')
    paths = [member_path(root, item['path']) for item in members]

    def validate():
        for path, item in zip(validation_paths, members, strict=True):
            if checked_hash(path, item['identity']) != item['sha256']:
                raise ValueError('Conteúdo alterado; gere nova fila')

    provenance = {'queue_id': queue['id'], 'pair_id': pair_id}
    if queue['version'] == 2:
        indices = pair['left_members'] + pair['right_members']
        members = [queue['files'][i] for i in indices]
        validation_paths = [member_path(root, item['path']) for item in members]
        provenance.update(assessment_scope='displayed_representatives_only',
                          observed_locations=[item['path'] for item in members])
    else:
        validation_paths = paths
    validate()
    return review_pair(*paths, output, decision, reason,
                       provenance=provenance,
                       validate_source=validate)


def load_queue(path: Path) -> dict:
    """Load locally produced v1/v2 queues; checksum is not authentication."""
    queue = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(queue, dict) or queue.get('kind') != 'visual-set-review'
            or queue.get('version') not in (1, 2) or seal(queue)['id'] != queue.get('id')):
        raise ValueError('Fila inválida')
    return queue
