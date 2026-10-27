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
from duplicate_lab.exact_plan import (
    build_plan,
    exact_scan,
    load_artifact,
    revalidate_plan,
    write_artifact,
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
        prog="duplicate-lab",
        description="Laboratorio de revisão e quarentena explícita de duplicatas"
    )
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    batch = commands.add_parser("visual-set", help="Descobrir fila visual JPEG limitada")
    batch.add_argument("directory", type=Path)
    batch.add_argument("--output-dir", type=Path, required=True)
    batch.add_argument("--collapse-exact", action="store_true",
                       help="Reunir localizações SHA-256 iguais; não agrupa similaridade")
    batch.add_argument("--max-files", type=int, default=200)
    batch.add_argument("--max-candidates", type=int, default=1000,
                       help="Limite total de candidatos (1..1000), sem truncamento")
    batch.add_argument("--page-size", type=int, default=25,
                       help="Candidatos por página HTML (1..100)")
    selected = commands.add_parser("visual-set-pair", help="Avaliar par por ID da fila")
    selected.add_argument("queue_file", type=Path)
    selected.add_argument("pair_id")
    selected.add_argument("--output-dir", type=Path, required=True)
    selected.add_argument("--decision", choices=(
        "pending", "accepted_candidate", "rejected_candidate", "uncertain"
    ), default="pending")
    selected.add_argument("--reason", default="")
    visual = commands.add_parser("visual-pair", help="Revisão humana de dois JPEGs, sem ações")
    visual.add_argument("left", type=Path)
    visual.add_argument("right", type=Path)
    visual.add_argument("--output-dir", type=Path, required=True)
    visual.add_argument("--decision", choices=(
        "pending", "accepted_candidate", "rejected_candidate", "uncertain"
    ), default="pending")
    visual.add_argument("--reason", default="")
    exact = commands.add_parser(
        "exact-scan", help="Inventário binário e grupos SHA-256, sem visual"
    )
    _add_common(exact)
    exact.add_argument("--output", type=Path, required=True)
    plan = commands.add_parser("exact-plan", help="Plano revisável; nunca movimenta arquivos")
    plan.add_argument("scan_file", type=Path)
    plan.add_argument("--quarantine-dir", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--retention-policy", type=Path)
    plan.add_argument("--decisions", type=Path, help="JSON: SHA-256 -> {keep, reason}")
    plan.add_argument(
        "--dependencies-reviewed",
        action="store_true",
        help="Registrar revisão humana das dependências externas/catálogos",
    )
    check = commands.add_parser("exact-check", help="Revalidar plano sem executar ações")
    check.add_argument("plan_file", type=Path)
    gallery = commands.add_parser("exact-gallery", help="Visualizar plano exato em HTML local")
    gallery.add_argument("plan_file", type=Path)
    gallery.add_argument("--output", type=Path, required=True)
    auth = commands.add_parser("exact-authorize", help="Autorizar plano exato para mover/restaurar")
    auth.add_argument("plan_file", type=Path)
    auth.add_argument("--confirm-plan-id", required=True)
    auth.add_argument("--exclusive-access", action="store_true", required=True)
    auth.add_argument("--output", type=Path, required=True)
    for name in ("exact-quarantine", "exact-restore"):
        operation = commands.add_parser(name, help="Executar/retomar ações autorizadas")
        operation.add_argument("plan_file", type=Path)
        operation.add_argument("--authorization", type=Path, required=True)
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
        if args.command == "visual-set":
            from duplicate_lab.visual_set import discover_set

            result = discover_set(args.directory, args.output_dir,
                                  args.max_files, args.max_candidates,
                                  collapse_exact=args.collapse_exact, page_size=args.page_size)
            print(f"Fila privada: {len(result['candidates'])} candidatos; nenhuma ação autorizada")
            print(json.dumps(result["summary"], ensure_ascii=False))
            return 0
        if args.command == "visual-set-pair":
            from duplicate_lab.visual_set import load_queue, review_set_pair

            review_set_pair(load_queue(args.queue_file),
                            args.pair_id, args.output_dir, args.decision, args.reason)
            print(f"Revisão privada: {args.output_dir}; nenhuma ação autorizada")
            return 0
        if args.command == "visual-pair":
            from duplicate_lab.visual_review import review_pair

            review_pair(args.left, args.right, args.output_dir, args.decision, args.reason)
            print(f"Revisão privada: {args.output_dir}; nenhuma ação autorizada")
            return 0
        if args.command in ("exact-authorize", "exact-quarantine", "exact-restore"):
            from duplicate_lab.quarantine import authorize, execute, load_execution_artifact

            plan = load_execution_artifact(args.plan_file, "exact-plan")
            if args.command == "exact-authorize":
                approval = authorize(plan, args.confirm_plan_id)
                write_artifact(approval, args.output, Path(plan["scan"]["root"]))
                print(f"Autorização explícita gravada: {args.output}")
            else:
                approval = load_execution_artifact(args.authorization, "exact-authorization")
                print(json.dumps(execute(plan, approval, restore=args.command == "exact-restore")))
            return 0
        if args.command == "exact-gallery":
            from duplicate_lab.html_report import write_exact_gallery

            write_exact_gallery(load_artifact(args.plan_file, "exact-plan"), args.output)
            print(f"written: {args.output}; galeria somente leitura")
            return 0
        if args.command == "exact-scan":
            payload = exact_scan(args.directory, args.extensions)
            write_artifact(payload, args.output, args.directory)
            print(f"written: {args.output}; exact groups: {len(payload['groups'])}")
            return 0
        if args.command == "exact-plan":
            snapshot = load_artifact(args.scan_file, "exact-scan")
            policy = load_retention_policy(args.retention_policy) if args.retention_policy else None
            decisions = (
                json.loads(args.decisions.read_text(encoding="utf-8")) if args.decisions else None
            )
            if decisions is not None and not isinstance(decisions, dict):
                raise ValueError("Decisões devem ser um objeto JSON")
            payload = build_plan(
                snapshot,
                args.quarantine_dir,
                policy,
                decisions,
                dependencies_reviewed=args.dependencies_reviewed,
            )
            write_artifact(payload, args.output, Path(snapshot["root"]))
            print(f"written: {args.output}; dry-run; action_authorized=false")
            return 0
        if args.command == "exact-check":
            result = revalidate_plan(load_artifact(args.plan_file, "exact-plan"))
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["unchanged"] and result["ready_for_review"] else 2
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
