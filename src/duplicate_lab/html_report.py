"""Self-contained, local HTML presentation for scan results."""

# HTML, CSS, and JavaScript literals are clearer when selected lines remain intact.
# ruff: noqa: E501

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from duplicate_lab.models import PairResult, PhotoRecord, ScanResult
from duplicate_lab.quality import QualityGroup, QualityIndicators, QualityReport
from duplicate_lab.retention import RetentionReport

THUMBNAIL_SIZE = (360, 240)
THUMBNAIL_MAX_BYTES = 96 * 1024


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _metric(value: float | int | None, digits: int = 3) -> str:
    if value is None:
        return "não disponível"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def _thumbnail(path: Path) -> str | None:
    """Return a bounded JPEG data URI; never embed the original file bytes."""
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            for quality in (78, 65, 50, 35):
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=quality, optimize=True)
                payload = buffer.getvalue()
                if len(payload) <= THUMBNAIL_MAX_BYTES:
                    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")
            return None
    except (OSError, ValueError, UnidentifiedImageError):
        return None


def _image(
    record: PhotoRecord | None,
    path: Path,
    thumbnails: dict[Path, str | None],
    quality: dict[Path, QualityIndicators] | None = None,
) -> str:
    dimensions = (
        f"{record.width} × {record.height}"
        if record and record.width is not None and record.height is not None
        else "não disponíveis"
    )
    size = f"{record.size_bytes:,}".replace(",", ".") if record else "não disponível"
    thumbnail = thumbnails.get(path)
    media = (
        f'<img src="{thumbnail}" alt="Miniatura de {_escape(path.name)}" loading="lazy">'
        if thumbnail
        else '<div class="thumb-missing">Miniatura indisponível</div>'
    )
    indicator = quality.get(path) if quality else None
    quality_html = ""
    if indicator:
        quality_html = f"""<span>Nitidez relativa: {_metric(indicator.sharpness, 5)}</span>
        <span>Luminância média: {_metric(indicator.mean_luminance)}</span>
        <span>Muito claros: {_metric(indicator.bright_fraction)} · muito escuros: {_metric(indicator.dark_fraction)}</span>
        <span>Quantização JPEG média: {_metric(indicator.jpeg_quantization_mean)}</span>
        <span>Blocos (experimental): {_metric(indicator.blockiness_experimental, 5)}</span>
        <span>EXIF relevante disponível: {"sim" if indicator.exif_available else "não"}</span>"""
    return f"""
      <figure>{media}<figcaption><strong>{_escape(path.name)}</strong>
      <span title="{_escape(path)}">{_escape(path)}</span>
      <span>{dimensions} · {size} bytes</span>{quality_html}</figcaption></figure>"""


def _classification(pair: PairResult) -> str:
    labels = {
        "similar_image": "indício visual forte (heurístico)",
        "visual_candidate": "candidato visual (heurístico)",
        "unclassified": "análise incompleta",
    }
    return labels.get(pair.classification, "resultado heurístico")


def _exact_sections(
    result: ScanResult,
    records: dict[Path, PhotoRecord],
    thumbnails: dict[Path, str | None],
) -> str:
    sections = []
    for index, group in enumerate(result.exact_groups, 1):
        images = "".join(_image(records.get(path), path, thumbnails) for path in group.paths)
        name = min(path.name.casefold() for path in group.paths)
        sections.append(
            f"""<details class="result exact" data-kind="exact" data-name="{_escape(name)}"
              data-phash="" data-ssim="" data-mae="">
              <summary>Grupo exato {index}: {len(group.paths)} arquivos</summary>
              <div class="facts"><span>SHA-256: <code>{_escape(group.sha256)}</code></span>
              <span>Redundâncias: {group.redundant_files}</span>
              <span>Espaço redundante: {group.redundant_bytes:,} bytes</span></div>
              <p class="notice">Bytes idênticos. Nenhum arquivo é recomendado para exclusão.</p>
              <div class="images">{images}</div></details>"""
        )
    return "".join(sections) or '<p class="empty">Nenhum grupo exato encontrado.</p>'


def _pair_sections(
    result: ScanResult,
    records: dict[Path, PhotoRecord],
    thumbnails: dict[Path, str | None],
    quality: dict[Path, QualityIndicators] | None = None,
) -> str:
    sections = []
    pairs = [pair for pair in result.pairs if pair.classification != "exact_duplicate"]
    for index, pair in enumerate(pairs, 1):
        images = _image(records.get(pair.left), pair.left, thumbnails, quality) + _image(
            records.get(pair.right), pair.right, thumbnails, quality
        )
        name = f"{pair.left.name} {pair.right.name}".casefold()
        incomplete = pair.error or any(
            value is None
            for value in (pair.phash_distance, pair.rotation_degrees, pair.ssim, pair.mae)
        )
        kind = "issue" if incomplete else "visual"
        error = f'<p class="error">Erro: {_escape(pair.error)}</p>' if pair.error else ""
        sections.append(
            f"""<details class="result {kind}" data-kind="{kind}" data-name="{_escape(name)}"
              data-phash="{_escape(pair.phash_distance if pair.phash_distance is not None else "")}"
              data-ssim="{_escape(pair.ssim if pair.ssim is not None else "")}"
              data-mae="{_escape(pair.mae if pair.mae is not None else "")}">
              <summary>Par {index}: {_escape(pair.left.name)} ↔ {_escape(pair.right.name)}</summary>
              <div class="images">{images}</div>
              <div class="facts"><span>pHash: {_metric(pair.phash_distance)}</span>
              <span>Rotação considerada: {_metric(pair.rotation_degrees)}°</span>
              <span>SSIM: {_metric(pair.ssim)}</span><span>MAE: {_metric(pair.mae)}</span>
              <span>Classificação: {_escape(_classification(pair))}</span></div>
              <p class="notice">A equivalência visual não está confirmada; revise as imagens.</p>{error}
              </details>"""
        )
    return "".join(sections) or '<p class="empty">Nenhum candidato visual encontrado.</p>'


def _quality_groups(
    groups: tuple[QualityGroup, ...],
    records: dict[Path, PhotoRecord],
    thumbnails: dict[Path, str | None],
    quality: dict[Path, QualityIndicators],
) -> str:
    sections = []
    for group in groups:
        members = []
        for member in group.members:
            reasons = "".join(f"<li>{_escape(reason)}</li>" for reason in member.reasons)
            members.append(
                f"""<div class="quality-member {member.recommendation}">
                <h4>{_escape(member.recommendation)}</h4>
                {_image(records.get(member.path), member.path, thumbnails, quality)}
                <ul>{reasons or "<li>Sem vantagem técnica conclusiva.</li>"}</ul></div>"""
            )
        limitations = "".join(f"<li>{_escape(item)}</li>" for item in group.limitations)
        evidence = (
            "identidade binária confirmada"
            if group.eligibility == "binary_identity"
            else "equivalência de captura confirmada por manifesto local"
        )
        sections.append(
            f"""<details class="result quality" data-kind="quality" data-name="{_escape(group.group_id.casefold())}" open>
            <summary>{_escape(group.group_id)} — {group.conclusion}</summary>
            <p class="notice">Elegibilidade: {evidence}. Recomendação apenas informativa.</p>
            <div class="quality-members">{"".join(members)}</div>
            <h4>Limitações</h4><ul>{limitations}</ul></details>"""
        )
    return "".join(sections)


def _retention_groups(report: RetentionReport) -> str:
    sections = []
    for item in report.recommendations:
        selected = str(item.selected) if item.selected else "nenhum arquivo"
        criteria = "".join(f"<li>{_escape(value)}</li>" for value in item.criteria)
        warnings = "".join(f"<li>{_escape(value)}</li>" for value in item.warnings)
        sections.append(
            f"""<details class="result retention" data-kind="retention" data-name="{_escape(item.group_id.casefold())}" open>
            <summary>{_escape(item.group_id)} — retenção: {_escape(item.conclusion)}</summary>
            <p><strong>Exemplar recomendado:</strong> {_escape(selected)}</p>
            <p>{_escape(item.justification)}</p><h4>Critérios externos</h4>
            <ul>{criteria or "<li>Nenhum critério distinguiu os caminhos.</li>"}</ul>
            <h4>Avisos</h4><ul>{warnings}</ul></details>"""
        )
    return "".join(sections)


def render_html(
    result: ScanResult,
    quality_report: QualityReport | None = None,
    retention_report: RetentionReport | None = None,
) -> str:
    """Prepare presentation data and render one offline, self-contained document."""
    records = {record.path: record for record in result.inventory}
    used_paths = {path for group in result.exact_groups for path in group.paths} | {
        path
        for pair in result.pairs
        if pair.classification != "exact_duplicate"
        for path in (pair.left, pair.right)
    }
    if quality_report:
        used_paths.update(
            member.path for group in quality_report.groups for member in group.members
        )
    thumbnails = {path: _thumbnail(path) for path in used_paths}
    summary = result.to_dict()["summary"]
    visual_pairs = [pair for pair in result.pairs if pair.classification != "exact_duplicate"]
    incomplete_pairs = [
        pair for pair in visual_pairs if pair.error or pair.ssim is None or pair.mae is None
    ]
    invalid = [record for record in result.inventory if not record.compatible]
    issues = "".join(
        f"<li><strong>{_escape(item.path.name)}</strong>: {_escape(item.error or 'formato incompatível')}</li>"
        for item in invalid
    )
    if not issues and not incomplete_pairs:
        issues = "<li>Nenhum arquivo não classificado ou erro de análise.</li>"
    elif incomplete_pairs:
        issues += f"<li>{len(incomplete_pairs)} comparação(ões) com análise incompleta.</li>"

    quality = {item.path: item for item in quality_report.indicators} if quality_report else {}
    exact = _exact_sections(result, records, thumbnails)
    pairs = _pair_sections(result, records, thumbnails, quality)
    quality_sections = (
        _quality_groups(quality_report.groups, records, thumbnails, quality)
        if quality_report
        else ""
    )
    retention_sections = _retention_groups(retention_report) if retention_report else ""
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'">
<title>PlayMemories Duplicate Lab — revisão local</title>
<style>
:root{{--ink:#17212b;--muted:#5d6874;--paper:#f4f1ea;--card:#fff;--line:#d4d0c8;--accent:#315b66;--warn:#8b4d15}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1200px;margin:auto;padding:2rem}}h1{{margin-bottom:.25rem}}.privacy,.notice{{color:var(--muted)}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.75rem;margin:1.5rem 0}}
.stat,.result,.issues,.controls{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem}}
.stat strong{{display:block;font-size:1.6rem}}.controls{{display:flex;flex-wrap:wrap;gap:.75rem;position:sticky;top:0;z-index:2}}
input,select{{font:inherit;padding:.5rem;border:1px solid var(--line);border-radius:6px;background:white}}input{{flex:1;min-width:220px}}
.result{{margin:1rem 0}}summary{{cursor:pointer;font-weight:700}}.images{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;margin-top:1rem}}
figure{{margin:0;min-width:0}}img,.thumb-missing{{display:block;width:100%;height:240px;object-fit:contain;background:#20262b;border-radius:7px}}
.thumb-missing{{color:white;display:grid;place-items:center}}figcaption span{{display:block;color:var(--muted);overflow-wrap:anywhere}}
.facts{{display:flex;flex-wrap:wrap;gap:.6rem 1.4rem;margin-top:1rem}}code{{overflow-wrap:anywhere}}.error{{color:#9b2525;font-weight:700}}
.quality-members{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}}.quality-member{{border:1px solid var(--line);border-radius:8px;padding:.75rem}}.quality-member.preferred{{border:3px solid var(--accent)}}
.hidden{{display:none}}@media(max-width:650px){{main{{padding:1rem}}.images{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Galeria local de revisão</h1><p class="privacy">Relatório autocontido com miniaturas de fotografias potencialmente privadas. Mantenha-o local.</p>
<section class="summary" aria-label="Resumo">
<div class="stat"><strong>{summary["files"]}</strong>fotografias</div>
<div class="stat"><strong>{len(result.exact_groups)}</strong>grupos exatos</div>
<div class="stat"><strong>{summary["exact_redundant_files"]}</strong>duplicatas exatas redundantes</div>
<div class="stat"><strong>{len(visual_pairs)}</strong>candidatos visuais</div>
<div class="stat"><strong>{len(invalid)}</strong>arquivos não classificados</div>
<div class="stat"><strong>{len(quality_report.groups) if quality_report else 0}</strong>grupos com avaliação técnica</div>
<div class="stat"><strong>{len(retention_report.recommendations) if retention_report else 0}</strong>recomendações de retenção</div>
</section>
<p>Métricas disponíveis: SHA-256 para grupos exatos; distância pHash, rotação, SSIM e MAE para candidatos visuais. Classificações são heurísticas.</p>
<section class="issues"><h2>Erros e análises incompletas</h2><ul>{issues}</ul></section>
<section class="controls" aria-label="Controles"><input id="search" type="search" placeholder="Buscar nome de arquivo">
<select id="filter"><option value="all">Todos os resultados</option><option value="retention">Retenção</option><option value="quality">Avaliação técnica</option><option value="exact">Grupos exatos</option><option value="visual">Candidatos visuais</option><option value="issue">Análises incompletas</option></select>
<select id="sort"><option value="name">Ordenar por nome</option><option value="phash">Distância pHash</option><option value="ssim-desc">SSIM (maior primeiro)</option><option value="mae">MAE</option></select></section>
<section id="results"><h2>Resultados: retenção, qualidade, grupos exatos e candidatos visuais</h2>{retention_sections}{quality_sections}{exact}{pairs}</section>
</main><script>
(() => {{'use strict';const search=document.querySelector('#search'),filter=document.querySelector('#filter'),sort=document.querySelector('#sort'),root=document.querySelector('#results');
const cards=[...root.querySelectorAll('.result')];function number(card,key,fallback){{const value=Number(card.dataset[key]);return card.dataset[key]===''?fallback:value}}
function update(){{const query=search.value.toLocaleLowerCase('pt-BR');for(const card of cards)card.classList.toggle('hidden',!(card.dataset.name.includes(query)&&(filter.value==='all'||card.dataset.kind===filter.value)));
cards.sort((a,b)=>{{if(sort.value==='phash')return number(a,'phash',Infinity)-number(b,'phash',Infinity);if(sort.value==='ssim-desc')return number(b,'ssim',-Infinity)-number(a,'ssim',-Infinity);if(sort.value==='mae')return number(a,'mae',Infinity)-number(b,'mae',Infinity);return a.dataset.name.localeCompare(b.dataset.name,'pt-BR')}}).forEach(card=>root.append(card));}}
[search,filter,sort].forEach(control=>control.addEventListener('input',update));update();}})();
</script></body></html>"""
