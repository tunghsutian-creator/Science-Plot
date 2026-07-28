"""Resolve Studio source snapshots, metric tables, and safe Excel sheet names."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _studio_snapshot_sources(
    input_path: Path | None,
    *,
    project_dir: Path,
    transform_ledger: dict[str, Any] | None,
) -> list[Path]:
    """Prefer the current plotted table while retaining raw input separately.

    Instrument folders are not necessarily rectangular worksheets. Semantic
    preparation records the exact plot-ready output in the transform ledger;
    all project-local terminal tabular outputs are eligible for the delivery
    workbook and exact rendered-source evidence.
    """
    supported_suffixes = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
    resolved_project = project_dir.resolve()
    if isinstance(transform_ledger, dict):
        steps = (
            transform_ledger.get("steps")
            if isinstance(transform_ledger.get("steps"), list)
            else []
        )
        for step in reversed(steps):
            if not isinstance(step, dict):
                continue
            artifacts = (
                step.get("output_artifacts")
                if isinstance(step.get("output_artifacts"), list)
                else []
            )
            ordered = sorted(
                (item for item in artifacts if isinstance(item, dict)),
                key=lambda item: 0 if item.get("role") == "output" else 1,
            )
            candidates: list[Path] = []
            for artifact in ordered:
                path_value = artifact.get("path")
                if not isinstance(path_value, str) or not path_value.strip():
                    continue
                candidate = Path(path_value).expanduser().resolve()
                if not candidate.is_relative_to(resolved_project):
                    continue
                if not candidate.exists():
                    continue
                if (
                    candidate.is_file()
                    and candidate.suffix.casefold() not in supported_suffixes
                ):
                    continue
                if candidate.is_file() or candidate.is_dir():
                    candidates.append(candidate)
            unique_candidates = list(dict.fromkeys(candidates))
            if unique_candidates:
                return unique_candidates
    return [input_path.expanduser().resolve()] if input_path is not None else []


def _studio_metric_source(source: Path | None) -> Path | None:
    """Resolve one canonical plotted table without guessing among raw files."""

    if source is None:
        return None
    if source.is_file():
        return source
    if not source.is_dir():
        return None
    supported_suffixes = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
    candidates = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in supported_suffixes
    )
    if len(candidates) == 1:
        return candidates[0]
    preferred_tokens = ("comparison", "plotting_data", "source_curves", "prepared")
    preferred = [
        path
        for path in candidates
        if any(token in path.stem.casefold() for token in preferred_tokens)
    ]
    return preferred[0] if len(preferred) == 1 else None


def _excel_sheet_name(label: str, *, fallback: str, used: set[str]) -> str:
    cleaned = "".join(
        "_" if char in "[]:*?/\\'" else char for char in str(label).strip()
    )
    cleaned = (cleaned or fallback)[:31]
    candidate = cleaned
    suffix = 1
    while candidate in used:
        trailer = f"_{suffix}"
        candidate = f"{cleaned[: 31 - len(trailer)]}{trailer}"
        suffix += 1
    used.add(candidate)
    return candidate
