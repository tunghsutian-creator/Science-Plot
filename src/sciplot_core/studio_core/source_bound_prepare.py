"""Prepare one source-attested Studio FigurePlan exactly once."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.studio_core.figure_task_evidence import figure_queue_from_plan
from sciplot_core.studio_core.semantic_source import _studio_source_for_request
from sciplot_core.studio_render.models import StudioPreparationBlocked


_SOURCE_BOUND_PLAN_RULE_IDS = frozenset(
    {"dma_temperature_sweep", "rheology_temperature_sweep"}
)


def prepare_source_bound_figure_queue(
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
    """Build one exact queue and share its attested semantic preparation."""

    if figure_plan is None or figure_plan.rule_id not in _SOURCE_BOUND_PLAN_RULE_IDS:
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


def _blocked(rule_id: str, message: str) -> NoReturn:
    reason_prefix = (
        "temperature" if rule_id == "rheology_temperature_sweep" else rule_id
    )
    raise StudioPreparationBlocked(
        f"{reason_prefix}_figure_plan_source_mismatch",
        f"{rule_id}: {message}",
    )


__all__ = ["prepare_source_bound_figure_queue"]
