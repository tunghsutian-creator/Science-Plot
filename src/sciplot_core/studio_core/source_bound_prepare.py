"""Prepare one source-attested Studio FigurePlan exactly once."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn
from uuid import uuid4

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.preparation_source_attestation import (
    PreparationSourceAttestation,
    requires_preparation_source_attestation,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_queue_from_plan,
    validate_figure_queue_against_plan,
)
from sciplot_core.studio_core.semantic_source import _studio_source_for_request
from sciplot_core.studio_render.models import StudioPreparationBlocked

if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source import (
        ResolvedScientificSource,
    )


def prepare_source_bound_figure_queue(
    *,
    figure_plan: ResolvedFigurePlan | None,
    source_input: Path | None,
    request: dict[str, Any],
    base_dir: Path,
    resolved_scientific_source: ResolvedScientificSource | None = None,
) -> tuple[
    list[dict[str, Any]],
    PreparationSourceAttestation | None,
    list[dict[str, Any]] | None,
]:
    """Build one exact queue and share its attested semantic preparation."""

    if figure_plan is None or not requires_preparation_source_attestation(
        figure_plan.rule_id
    ):
        return [], None, None
    rule_id = figure_plan.rule_id
    queue = figure_queue_from_plan(figure_plan, rule_id)
    if source_input is None:
        _blocked(rule_id, "Studio preparation lost its resolved raw source.")
    _prepared_source, preparation_steps, preparation_attestation = (
        _studio_source_for_request(
            source_input,
            request=request,
            base_dir=base_dir,
            resolved_scientific_source=resolved_scientific_source,
        )
    )
    if (
        preparation_attestation is None
        or figure_plan.source_sha256 != preparation_attestation.source_tree_sha256_after
    ):
        _blocked(
            rule_id,
            "Semantic preparation does not match the selected FigurePlan source snapshot.",
        )
    return queue, preparation_attestation, preparation_steps


def bind_mechanical_task_sources(
    queue: list[dict[str, Any]],
    *,
    figure_plan: ResolvedFigurePlan | None,
    source_attestation: PreparationSourceAttestation | None,
    project_dir: Path,
    request: dict[str, Any],
) -> list[dict[str, Any]]:
    """Materialize mechanical child tables inside the figure-set transaction."""

    if figure_plan is None or figure_plan.rule_id not in MECHANICAL_RULE_IDS:
        return queue
    validate_figure_queue_against_plan(queue, figure_plan)
    if any("_mechanical_task_source" in item for item in queue):
        _blocked(
            figure_plan.rule_id,
            "Studio alone must materialize a fresh, complete mechanical "
            "task-source queue.",
        )
    if source_attestation is None:
        _blocked(figure_plan.rule_id, "Mechanical preparation lost its attestation.")
    from sciplot_core.mechanical_task_sources import build_mechanical_task_sources

    task_source_dir = (
        project_dir.expanduser().resolve()
        / "studio"
        / "processed"
        / "mechanical_task_sources"
        / f"{figure_plan.plan_id}_{uuid4().hex}"
    )
    try:
        records = build_mechanical_task_sources(
            Path(source_attestation.prepared_source.path),
            raw_source=Path(source_attestation.source_root),
            source_attestation=source_attestation,
            figure_plan=figure_plan,
            output_dir=task_source_dir,
            request=request,
            options=(
                dict(request["render_options"])
                if isinstance(request.get("render_options"), dict)
                else {}
            ),
        )
    except (OSError, ValueError) as exc:
        shutil.rmtree(task_source_dir, ignore_errors=True)
        raise StudioPreparationBlocked(
            "mechanical_task_source_mismatch",
            f"{figure_plan.rule_id}: {exc}",
        ) from exc
    except BaseException:
        shutil.rmtree(task_source_dir, ignore_errors=True)
        raise
    by_id = {record.task.figure_id: record for record in records}
    if tuple(by_id) != figure_plan.selected_figure_ids:
        shutil.rmtree(task_source_dir, ignore_errors=True)
        _blocked(
            figure_plan.rule_id,
            "Materialized mechanical task sources do not exactly cover the plan.",
        )
    return [
        {**item, "_mechanical_task_source": by_id[str(item["id"])]} for item in queue
    ]


def _blocked(rule_id: str, message: str) -> NoReturn:
    reason_prefix = (
        "temperature" if rule_id == "rheology_temperature_sweep" else rule_id
    )
    raise StudioPreparationBlocked(
        f"{reason_prefix}_figure_plan_source_mismatch",
        f"{rule_id}: {message}",
    )


__all__ = ["bind_mechanical_task_sources", "prepare_source_bound_figure_queue"]
