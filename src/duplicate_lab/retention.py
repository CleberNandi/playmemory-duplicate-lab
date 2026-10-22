"""External, read-only retention recommendations for exact duplicate groups."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from duplicate_lab.models import ScanResult

RetentionConclusion = Literal["preferred", "tie", "inconclusive"]


@dataclass(frozen=True)
class RetentionPolicy:
    preferred_directories: tuple[PurePosixPath, ...] = ()
    preferred_name_patterns: tuple[str, ...] = ()
    location_priority: tuple[PurePosixPath, ...] = ()
    protected_directories: tuple[PurePosixPath, ...] = ()


@dataclass(frozen=True)
class RetentionRecommendation:
    group_id: str
    conclusion: RetentionConclusion
    selected: Path | None
    others: tuple[Path, ...]
    criteria: tuple[str, ...]
    justification: str
    warnings: tuple[str, ...]
    operations_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "conclusion": self.conclusion,
            "selected": str(self.selected) if self.selected else None,
            "others": [str(path) for path in self.others],
            "criteria": list(self.criteria),
            "justification": self.justification,
            "warnings": list(self.warnings),
            "operations_performed": self.operations_performed,
        }


@dataclass(frozen=True)
class RetentionReport:
    recommendations: tuple[RetentionRecommendation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"recommendations": [item.to_dict() for item in self.recommendations]}


def _relative_directory(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} deve conter caminhos relativos não vazios")
    normalized = PurePosixPath(value.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"{field} aceita apenas caminhos relativos dentro do acervo")
    return normalized


def load_retention_policy(path: Path) -> RetentionPolicy:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Política de retenção inválida: version deve ser 1")
    allowed = {
        "version",
        "preferred_directories",
        "preferred_name_patterns",
        "location_priority",
        "protected_directories",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"Campos desconhecidos na política: {', '.join(sorted(unknown))}")

    def paths_for(field: str) -> tuple[PurePosixPath, ...]:
        values = payload.get(field, [])
        if not isinstance(values, list) or len(values) != len(set(map(str, values))):
            raise ValueError(f"{field} deve ser uma lista sem duplicatas")
        return tuple(_relative_directory(value, field) for value in values)

    patterns = payload.get("preferred_name_patterns", [])
    if not isinstance(patterns, list) or not all(
        isinstance(item, str) and item for item in patterns
    ):
        raise ValueError("preferred_name_patterns deve ser uma lista de expressões não vazias")
    try:
        for pattern in patterns:
            re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Padrão de nome inválido: {exc}") from exc
    return RetentionPolicy(
        paths_for("preferred_directories"),
        tuple(patterns),
        paths_for("location_priority"),
        paths_for("protected_directories"),
    )


def _inside(relative: PurePosixPath, directory: PurePosixPath) -> bool:
    return relative == directory or directory in relative.parents


def build_retention_report(
    result: ScanResult, source_directory: Path, policy: RetentionPolicy
) -> RetentionReport:
    source = source_directory.resolve()
    recommendations = []
    for index, group in enumerate(result.exact_groups, 1):
        paths = tuple(sorted(group.paths, key=lambda item: item.as_posix().casefold()))
        relatives = {
            path: PurePosixPath(path.resolve().relative_to(source).as_posix()) for path in paths
        }
        warnings = [
            "Nenhuma operação de cópia, movimentação, renomeação ou exclusão foi executada."
        ]
        protected = [
            path
            for path in paths
            if any(_inside(relatives[path].parent, item) for item in policy.protected_directories)
        ]
        if protected:
            warnings.append(
                "Diretório protegido presente; suas cópias não são tratadas como descartáveis."
            )

        winners: list[tuple[str, set[Path]]] = []
        for rank, directory in enumerate(policy.location_priority, 1):
            matches = {path for path in paths if _inside(relatives[path].parent, directory)}
            if matches:
                winners.append((f"prioridade de localização {rank}: {directory}", matches))
                break
        directory_matches = {
            path
            for path in paths
            if any(_inside(relatives[path].parent, item) for item in policy.preferred_directories)
        }
        if directory_matches:
            winners.append(("diretório preferencial", directory_matches))
        name_matches = {
            path
            for path in paths
            if any(re.search(pattern, path.name) for pattern in policy.preferred_name_patterns)
        }
        if name_matches:
            winners.append(("padrão de nome preferencial", name_matches))

        criteria = tuple(label for label, _ in winners)
        unique_winners = {next(iter(items)) for _, items in winners if len(items) == 1}
        if len(unique_winners) > 1:
            conclusion: RetentionConclusion = "inconclusive"
            selected = None
            justification = "Critérios configurados apontam para arquivos diferentes."
        else:
            intersection = set(paths)
            for _, items in winners:
                intersection &= items
            if len(intersection) == 1:
                conclusion = "preferred"
                selected = next(iter(intersection))
                justification = (
                    "Preferência operacional sustentada pelos critérios externos configurados."
                )
            else:
                conclusion = "tie"
                selected = None
                justification = "As regras configuradas não distinguem um único exemplar."
        others = tuple(path for path in paths if path != selected)
        recommendations.append(
            RetentionRecommendation(
                f"exact-{index}",
                conclusion,
                selected,
                others,
                criteria,
                justification,
                tuple(warnings),
            )
        )
    return RetentionReport(tuple(recommendations))
