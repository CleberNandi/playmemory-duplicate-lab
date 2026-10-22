"""Explicit report writers; source photographs are never opened for writing."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TextIO

from duplicate_lab.models import ScanResult
from duplicate_lab.quality import QualityReport
from duplicate_lab.retention import RetentionReport

REPORT_FILENAMES = {
    "json": "duplicate-lab-report.json",
    "csv": "duplicate-lab-pairs.csv",
    "html": "duplicate-lab-gallery.html",
}


def validate_output_directory(source_directory: Path, output_directory: Path) -> Path:
    source = source_directory.resolve()
    destination = output_directory.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("O diretorio de relatorios deve ficar fora do acervo analisado")
    return destination


def _open_text(target: Path, overwrite: bool, newline: str | None = None) -> TextIO:
    return target.open("w" if overwrite else "x", encoding="utf-8", newline=newline)


def write_reports(
    result: ScanResult,
    output_directory: Path,
    formats: set[str],
    *,
    overwrite: bool = False,
    quality_report: QualityReport | None = None,
    retention_report: RetentionReport | None = None,
) -> list[Path]:
    unknown = formats - REPORT_FILENAMES.keys()
    if unknown:
        raise ValueError(f"Formato de relatorio desconhecido: {', '.join(sorted(unknown))}")
    output_directory.mkdir(parents=True, exist_ok=True)
    targets = {kind: output_directory / REPORT_FILENAMES[kind] for kind in formats}
    existing = [target for target in targets.values() if target.exists()]
    if existing and not overwrite:
        names = ", ".join(str(path) for path in sorted(existing))
        raise FileExistsError(f"Relatorio existente; use --overwrite para substituir: {names}")

    written: list[Path] = []
    if "json" in formats:
        target = targets["json"]
        with _open_text(target, overwrite) as stream:
            json.dump(result.to_dict(), stream, indent=2, ensure_ascii=False)
        written.append(target)
    if "csv" in formats:
        target = targets["csv"]
        with _open_text(target, overwrite, newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=list(result.pairs[0].to_dict())
                if result.pairs
                else [
                    "left",
                    "right",
                    "phash_distance",
                    "rotation_degrees",
                    "ssim",
                    "mae",
                    "classification",
                    "error",
                ],
            )
            writer.writeheader()
            writer.writerows(pair.to_dict() for pair in result.pairs)
        written.append(target)
    if "html" in formats:
        from duplicate_lab.html_report import render_html

        target = targets["html"]
        with _open_text(target, overwrite) as stream:
            stream.write(render_html(result, quality_report, retention_report))
        written.append(target)
    return written
