"""Discover and prioritize scientific source candidates for batch runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.text_files import text_preview
from sciplot_core.semantic import (
    has_tensile_export_parent,
    is_rheology_frequency_comparison_dir,
    is_rheology_temperature_comparison_dir,
    is_tensile_export_dir,
)


TABLE_SUFFIXES = {".csv", ".xlsx", ".xls"}
TORQUE_TEXT_SUFFIXES = {".txt", ".tsv"}
SMOKE_SEMANTIC_PRIORITY = {
    "impact_metric": 0,
    "rheology_frequency": 1,
    "rheology_temperature_sweep": 2,
    "rheology_creep": 3,
    "rheology_stress_relaxation": 4,
    "tensile_curve": 5,
    "ftir_spectrum": 6,
    "torque_curve": 7,
    "generic_replicate": 8,
    "generic_curve": 9,
}


def smoke_path_priority(path: Path) -> tuple[int, str]:
    text = path.as_posix().lower()
    if "impact" in text:
        return (0, text)
    if "流变" in text or "rheology" in text or "pinlv" in text or "/freq/" in text:
        return (1, text)
    if "tensile" in text:
        return (2, text)
    return (3, text)


def is_tensile_related(path: Path) -> bool:
    text = path.as_posix().casefold()
    return (
        "/tensile/" in text
        or "/拉伸/" in text
        or is_tensile_export_dir(path)
        or has_tensile_export_parent(path)
    )


def is_torque_text_export(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in TORQUE_TEXT_SUFFIXES:
        return False
    path_text = path.as_posix().casefold()
    if "torque" in path_text or "转矩" in path_text:
        return True
    try:
        preview = text_preview(path).casefold()
    except Exception:
        return False
    return "screw torque" in preview or "screwtorque" in preview or "转矩" in preview


def _is_under_any_root(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _is_under_any_dir(path: Path, dirs: tuple[Path, ...]) -> bool:
    return any(path == directory or directory in path.parents for directory in dirs)


def normalize_tensile_roots(values: list[Path] | None) -> tuple[Path, ...]:
    if not values:
        return ()
    return tuple(path.expanduser().resolve() for path in values)


def candidate_sources(
    input_dir: Path,
    all_files: list[Path],
    *,
    tensile_roots: tuple[Path, ...] = (),
) -> tuple[list[Path], list[dict[str, Any]]]:
    skipped: list[dict[str, Any]] = []
    rheology_comparison_dirs = tuple(
        sorted(
            (
                path
                for path in [input_dir, *input_dir.rglob("*")]
                if path.is_dir()
                and (
                    is_rheology_frequency_comparison_dir(path)
                    or is_rheology_temperature_comparison_dir(path)
                )
            ),
            key=lambda path: path.as_posix(),
        )
    )
    tensile_dirs = sorted(
        (path for path in input_dir.rglob("*") if is_tensile_export_dir(path)),
        key=lambda path: path.as_posix(),
    )
    table_files = sorted(
        (
            path
            for path in all_files
            if (path.suffix.lower() in TABLE_SUFFIXES or is_torque_text_export(path))
            and not has_tensile_export_parent(path)
            and not _is_under_any_dir(path, rheology_comparison_dirs)
        ),
        key=smoke_path_priority,
    )
    for path in all_files:
        if path.suffix.lower() in TABLE_SUFFIXES and _is_under_any_dir(
            path, rheology_comparison_dirs
        ):
            skipped.append(
                {
                    "path": str(path),
                    "reason": "covered_by_rheology_sweep_comparison_dir",
                }
            )
    candidates: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(
        [*rheology_comparison_dirs, *tensile_dirs, *table_files],
        key=smoke_path_priority,
    ):
        if path in seen:
            continue
        seen.add(path)
        if (
            tensile_roots
            and is_tensile_related(path)
            and not _is_under_any_root(path, tensile_roots)
        ):
            skipped.append(
                {
                    "path": str(path),
                    "reason": "tensile_outside_allowed_roots",
                }
            )
            continue
        candidates.append(path)
    return candidates, skipped


def semantic_priority(
    semantic: dict[str, Any],
    source: Path,
) -> tuple[int, str]:
    family = str(semantic.get("semantic_family") or "unknown")
    return (
        SMOKE_SEMANTIC_PRIORITY.get(
            family,
            int(semantic.get("rule_priority") or 99),
        ),
        source.as_posix(),
    )
