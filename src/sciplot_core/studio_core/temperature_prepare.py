"""Prepare the source-bound rheology-temperature Studio figure queue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.studio_core.figure_task_evidence import figure_queue_from_plan
from sciplot_core.studio_core.semantic_source import _studio_source_for_request
from sciplot_core.studio_render.models import StudioPreparationBlocked


def prepare_temperature_figure_queue(
    *,
    figure_plan: ResolvedFigurePlan | None,
    source_input: Path | None,
    request: dict[str, Any],
    base_dir: Path,
) -> tuple[
    list[dict[str, Any]],
    PreparationSourceAttestation | None,
    list[dict[str, Any]] | None,
]:
    """Build the exact queue and perform temperature semantic preparation once."""

    if figure_plan is None or figure_plan.rule_id != "rheology_temperature_sweep":
        return [], None, None
    queue = figure_queue_from_plan(figure_plan, "rheology_temperature_sweep")
    if source_input is None:
        raise StudioPreparationBlocked(
            "temperature_figure_plan_source_mismatch",
            "Temperature Studio preparation lost its resolved raw source.",
        )
    _prepared_source, preparation_steps, preparation_attestation = (
        _studio_source_for_request(
            source_input,
            request=request,
            base_dir=base_dir,
        )
    )
    if (
        preparation_attestation is None
        or figure_plan.source_sha256 != preparation_attestation.source_tree_sha256_after
    ):
        raise StudioPreparationBlocked(
            "temperature_figure_plan_source_mismatch",
            "Temperature semantic preparation does not match the selected "
            "FigurePlan source snapshot.",
        )
    return queue, preparation_attestation, preparation_steps


__all__ = ["prepare_temperature_figure_queue"]
