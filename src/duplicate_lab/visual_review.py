"""Explicit, read-only JPEG pair review; never produces an execution plan."""

from __future__ import annotations

import html
import json
from pathlib import Path

from duplicate_lab.hashing import oriented_phashes, sha256_file
from duplicate_lab.html_report import _thumbnail
from duplicate_lab.inventory import inspect_file
from duplicate_lab.similarity import structural_metrics

DECISIONS = ("pending", "accepted_candidate", "rejected_candidate", "uncertain")


def review_pair(
    left: Path, right: Path, output: Path, decision: str = "pending", reason: str = ""
) -> dict:
    """Persist a private snapshot and human assessment, without inferring capture identity."""
    if decision not in DECISIONS or (decision != "pending" and not reason.strip()):
        raise ValueError("Avaliação inválida ou motivo ausente")
    paths = (left.absolute(), right.absolute())
    for path in paths:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Links não suportados")
    paths = tuple(p.resolve(strict=True) for p in paths)
    if paths[0].samefile(paths[1]):
        raise ValueError("Escolha dois arquivos distintos")
    output = output.resolve()
    if any(output == p.parent or p.parent in output.parents for p in paths):
        raise ValueError("Saída deve ficar fora dos diretórios das imagens")
    records = tuple(inspect_file(p) for p in paths)
    if not all(r.compatible for r in records):
        raise ValueError("Somente JPEG válido nesta entrega")
    digests = [sha256_file(r.path, expected_identity=r.identity) for r in records]
    distance = int(oriented_phashes(paths[0])[0] - oriented_phashes(paths[1])[0])
    ssim, mae = structural_metrics(*paths, rotation=0)
    thumbnails = [_thumbnail(p) for p in paths]
    if not all(thumbnails):
        raise ValueError("Não foi possível gerar as miniaturas")
    result = {
        "kind": "visual-pair-review", "version": 1,
        "files": [dict(r.to_dict(), sha256=d) for r, d in zip(records, digests, strict=True)],
        "binary_equal": digests[0] == digests[1],
        "metrics": {"phash_distance": distance, "ssim": ssim, "mae": mae,
                    "comparison_side": 512, "rotation_search": False},
        "human_review": {"decision": decision, "reason": reason},
        "capture_identity": "not_established", "action_authorized": False,
    }
    figures = "".join(
        f'<figure><img src="{thumb}" alt="Prévia"><figcaption>'
        f'{html.escape(str(r.path))}<br>{r.width} × {r.height} · {r.size_bytes} bytes'
        '</figcaption></figure>'
        for r, thumb in zip(records, thumbnails, strict=True)
    )
    document = (
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
        '<title>Revisão de par visual</title><style>'
        'body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:1rem}'
        '.pair{display:flex;flex-wrap:wrap}figure{flex:1;min-width:280px;margin:1rem}'
        'img{width:100%;object-fit:contain;image-rendering:auto}'
        'figcaption{overflow-wrap:anywhere}pre{white-space:pre-wrap}</style>'
        '<h1>Revisão humana de par visual</h1>'
        '<p>Prévia reduzida; não demonstra mesma captura ou transformação. '
        'Nenhuma preferência de preservação ou ação é autorizada. '
        'Métricas normalizam o quadro para 512 × 512 em cinza, sem buscar rotação; '
        'EXIF é normalizado. Não comprovam identidade.</p>'
        f'<div class="pair">{figures}</div><pre>'
        + html.escape(json.dumps(result, indent=2, ensure_ascii=False)) + '</pre></html>'
    )
    # Recheck after decoding/rendering. External writers must still be stopped.
    for r, digest in zip(records, digests, strict=True):
        if sha256_file(r.path, expected_identity=r.identity) != digest:
            raise ValueError("Imagem alterada durante a revisão")
    output.mkdir(parents=True, exist_ok=False)
    (output / "review.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output / "gallery.html").write_text(document, encoding="utf-8")
    return result
