"""Bind Workflow rendering to the same source snapshot as its figure plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    source_trees_match_sha256,
)


def verify_workflow_figure_plan_source_binding(
    plan: ResolvedFigurePlan | None,
    *,
    input_path: Path,
    raw_archive: dict[str, Any],
) -> None:
    """Require live and archived render inputs to match the resolved plan."""

    if plan is None:
        return
    archive = (
        raw_archive.get("effective_input")
        if isinstance(raw_archive.get("effective_input"), dict)
        else raw_archive
    )
    archive_value = archive.get("path")
    archive_path = (
        Path(archive_value).expanduser()
        if isinstance(archive_value, str) and archive_value.strip()
        else None
    )
    if plan.rule_id == "dsc_curve":
        from sciplot_core.figure_plan.dsc_resolution import (
            dsc_single_curve_source_sha256,
        )

        sources_match = bool(
            plan.source_sha256
            and archive_path is not None
            and dsc_single_curve_source_sha256(input_path) == plan.source_sha256
            and dsc_single_curve_source_sha256(archive_path) == plan.source_sha256
        )
    else:
        sources_match = source_trees_match_sha256(
            plan.source_sha256,
            input_path,
            archive_path,
        )
    if not sources_match:
        raise RuntimeError(
            "Workflow source changed after its resolved figure plan was "
            "prepared; rerun the request from a stable source."
        )


__all__ = ["verify_workflow_figure_plan_source_binding"]
