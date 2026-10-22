"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from duplicate_lab.benchmark_copydays import run_benchmark, write_benchmark_reports
from duplicate_lab.benchmark_strong import (
    generate_controlled_negatives,
    run_strong_benchmark,
    write_strong_reports,
)
from duplicate_lab.inventory import build_inventory
from duplicate_lab.quality import build_quality_report
from duplicate_lab.reporting import validate_output_directory, write_reports
from duplicate_lab.retention import build_retention_report, load_retention_policy
from duplicate_lab.scanner import scan


def _extensions(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("directory", type=Path, help="Diretorio de fotografias (somente leitura)")
    parser.add_argument(
        "--extensions",
        type=_extensions,
        default=["jpg", "jpeg"],
        help="Lista separada por virgulas",
    )


def _add_scan_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--phash-threshold", type=int, default=8, choices=range(0, 65), metavar="0..64"
    )
    parser.add_argument(
        "--comparison-side", type=int, default=512, choices=range(64, 2049), metavar="64..2048"
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="duplicate-lab", description="Laboratorio somente leitura de duplicatas fotograficas"
    )
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="Descobrir e validar imagens")
    _add_common(inventory)
    scan_command = commands.add_parser("scan", help="Executar a pipeline e mostrar o resumo")
    _add_common(scan_command)
    _add_scan_options(scan_command)
    report = commands.add_parser("report", help="Executar a pipeline e gravar relatorios")
    _add_common(report)
    _add_scan_options(report)
    report.add_argument(
        "--output-dir", type=Path, required=True, help="Diretorio explicito, separado do acervo"
    )
    report.add_argument(
        "--format",
        choices=("json", "csv", "html", "both", "all"),
        default="both",
        help="both gera JSON+CSV; all gera JSON+CSV+HTML",
    )
    report.add_argument(
        "--overwrite", action="store_true", help="Autorizar substituicao de relatorios existentes"
    )
    report.add_argument(
        "--quality", action="store_true", help="Incluir indicadores tecnicos no relatorio HTML"
    )
    report.add_argument(
        "--quality-manifest",
        type=Path,
        help="Manifesto JSON externo que confirma grupos da mesma captura; implica --quality",
    )
    report.add_argument(
        "--retention-policy",
        type=Path,
        help="Política JSON externa para recomendações de retenção de cópias exatas",
    )
    benchmark = commands.add_parser(
        "benchmark-copydays", help="Avaliar o detector no INRIA Copydays"
    )
    benchmark.add_argument(
        "dataset_root", type=Path, help="Raiz extraída com original/ e jpegqual/"
    )
    benchmark.add_argument("--output-dir", type=Path, required=True)
    benchmark.add_argument("--include-strong", action="store_true")
    benchmark.add_argument("--max-queries", type=int, help="Limite determinístico para smoke test")
    benchmark.add_argument("--overwrite", action="store_true")
    strong = commands.add_parser(
        "benchmark-copydays-strong", help="Executar Benchmark 02 com Strong e negativos"
    )
    strong.add_argument("dataset_root", type=Path)
    strong.add_argument("--distractor-root", type=Path, required=True)
    strong.add_argument("--output-dir", type=Path, required=True)
    strong.add_argument("--baseline", type=Path)
    strong.add_argument("--max-queries", type=int, help="Limite determinístico para smoke test")
    strong.add_argument("--comparison-side", type=int, default=512)
    strong.add_argument("--overwrite", action="store_true")
    return root


def _print_scan(result) -> None:
    summary = result.to_dict()["summary"]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    for group in result.exact_groups:
        print(f"exact group: {len(group.paths)} files, {group.redundant_bytes} redundant bytes")
    for pair in result.pairs:
        if pair.classification != "exact_duplicate":
            print(
                f"{pair.classification}: {pair.left.name} <> {pair.right.name} "
                f"pHash={pair.phash_distance} SSIM={pair.ssim:.5f} MAE={pair.mae:.5f}"
            )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )
    try:
        if args.command == "benchmark-copydays-strong":
            if args.max_queries is not None and args.max_queries < 1:
                raise ValueError("--max-queries deve ser positivo")
            generate_controlled_negatives(
                args.distractor_root / "database", count=256, namespace="db"
            )
            generate_controlled_negatives(
                args.distractor_root / "queries", count=64, namespace="query"
            )
            result = run_strong_benchmark(
                args.dataset_root,
                args.distractor_root,
                baseline_path=args.baseline,
                comparison_side=args.comparison_side,
                max_queries=args.max_queries,
            )
            for path in write_strong_reports(result, args.output_dir, overwrite=args.overwrite):
                print(f"written: {path}")
            print(
                json.dumps(
                    {key: value["metrics"] for key, value in result["scenarios"].items()},
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "benchmark-copydays":
            if args.max_queries is not None and args.max_queries < 1:
                raise ValueError("--max-queries deve ser positivo")
            result = run_benchmark(
                args.dataset_root,
                include_strong=args.include_strong,
                max_queries=args.max_queries,
            )
            for path in write_benchmark_reports(result, args.output_dir, overwrite=args.overwrite):
                print(f"written: {path}")
            print(json.dumps(result["metrics"], indent=2, ensure_ascii=False))
            return 0
        if args.command == "inventory":
            records = build_inventory(args.directory, args.extensions)
            print(json.dumps([item.to_dict() for item in records], indent=2, ensure_ascii=False))
            return 0
        result = scan(args.directory, args.extensions, args.phash_threshold, args.comparison_side)
        _print_scan(result)
        if args.command == "report":
            destination = validate_output_directory(args.directory, args.output_dir)
            formats = {
                "both": {"json", "csv"},
                "all": {"json", "csv", "html"},
            }.get(args.format, {args.format})
            quality_requested = args.quality or args.quality_manifest is not None
            if quality_requested and "html" not in formats:
                raise ValueError("A analise de qualidade requer formato html ou all")
            if args.retention_policy and "html" not in formats:
                raise ValueError("A política de retenção requer formato html ou all")
            quality_report = (
                build_quality_report(result, args.directory, args.quality_manifest)
                if quality_requested
                else None
            )
            retention_report = (
                build_retention_report(
                    result, args.directory, load_retention_policy(args.retention_policy)
                )
                if args.retention_policy
                else None
            )
            for path in write_reports(
                result,
                destination,
                formats,
                overwrite=args.overwrite,
                quality_report=quality_report,
                retention_report=retention_report,
            ):
                print(f"written: {path}")
        return 0
    except (OSError, ValueError) as exc:
        logging.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
