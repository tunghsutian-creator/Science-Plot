"""Bind Workflow rendering to the same source snapshot as its figure plan."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sciplot_core.publication import build_transform_step
from typing import TYPE_CHECKING, Any

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    source_trees_match_sha256,
)

if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source import (
        ResolvedScientificSource,
    )


def verify_workflow_figure_plan_source_binding(
    plan: ResolvedFigurePlan | None,
    *,
    input_path: Path,
    raw_archive: dict[str, Any],
    resolved_scientific_source: ResolvedScientificSource | None = None,
) -> None:
    """Require archived and any unbound live inputs to match the plan."""

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
    live_source_is_bound = bool(
        plan.source_sha256
        and resolved_scientific_source is not None
        and resolved_scientific_source.source == input_path.expanduser().resolve()
        and resolved_scientific_source.source_sha256 == plan.source_sha256
    )
    sources_to_hash = (
        (archive_path,)
        if live_source_is_bound
        else (input_path, archive_path)
    )
    sources_match = source_trees_match_sha256(
        plan.source_sha256,
        *sources_to_hash,
    )
    if not sources_match:
        raise RuntimeError(
            "Workflow source changed after its resolved figure plan was "
            "prepared; rerun the request from a stable source."
        )


__all__ = ["verify_workflow_figure_plan_source_binding"]


def initial_transform_steps(
    *,
    mapping_application: dict[str, Any] | None,
    cleanup_application: dict[str, Any] | None,
    original_input_path: Path,
    input_path: Path,
) -> list[dict[str, Any]]:
    steps = [
        deepcopy(step)
        for step in (
            mapping_application.get("transform_steps", [])
            if mapping_application is not None
            else []
        )
        if isinstance(step, dict)
    ]
    if cleanup_application is not None:
        steps.append(
            build_transform_step(
                step_id="assisted_cleanup",
                operation="confirmed_cleanup",
                input_path=original_input_path,
                output_path=input_path,
                implementation_ref=(
                    "sciplot_core.assisted_cleanup.consume_ready_cleanup_result"
                ),
                parameters={
                    "cleanup_result": cleanup_application["cleanup_result"],
                    "mapping_proposal": cleanup_application["mapping_proposal"],
                    "request_patch": cleanup_application["request_patch"],
                    "human_confirmed": True,
                },
            )
        )
    return steps
