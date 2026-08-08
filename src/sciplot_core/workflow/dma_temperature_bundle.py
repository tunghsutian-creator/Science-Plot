"""Render the selected DMA temperature/storage-modulus task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_RULE_ID,
    DMA_TEMPERATURE_TEMPLATE,
    DMA_TEMPERATURE_X_METRIC,
    DMA_TEMPERATURE_Y_METRIC,
)
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding
from sciplot_core.workflow.dma_execution_evidence import (
    build_dma_temperature_execution_evidence,
)
from sciplot_core.workflow.dma_temperature_plan import (
    require_dma_temperature_execution_plan,
)
from sciplot_core.workflow.single_task_bundle import (
    render_selected_single_task_bundle,
)


def _render_veusz_dma_temperature_bundle(
    input_path: Path,
    *,
    source_input: Path | None,
    source_attestation: PreparationSourceAttestation | None,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    """Render one exact DMA task without invoking the rheology plan resolver."""

    if str(request.get("rule_id") or "").strip() != DMA_TEMPERATURE_RULE_ID:
        return None
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    if plan is None:
        raise ValueError(
            "dma_temperature_figure_plan_required: DMA temperature execution "
            "requires one selected FigurePlan."
        )
    raw_source = source_input or input_path
    source_facts = require_dma_temperature_execution_plan(
        plan,
        source=raw_source,
    )
    task = plan.tasks[0]
    terminal_binding: MaterializedTerminalSourceBinding | None = None
    if source_input is not None:
        if source_attestation is None:
            raise ValueError(
                "dma_temperature_preparation_attestation_missing: semantic "
                "preparation lost its typed source evidence."
            )
        source_attestation.verify_current(
            source_root=source_input,
            prepared_source=input_path,
        )
        if (
            source_attestation.rule_id != DMA_TEMPERATURE_RULE_ID
            or source_attestation.source_tree_sha256_after != plan.source_sha256
        ):
            raise ValueError(
                "dma_temperature_preparation_attestation_mismatch: prepared data "
                "does not belong to the selected DMA source snapshot."
            )
        if task.sample_order != source_facts.sample_order:
            raise ValueError(
                "dma_temperature_terminal_source_binding_mismatch: selected "
                "sample order diverges from the validated raw source."
            )
        terminal_binding = MaterializedTerminalSourceBinding.create(
            task_key=task.figure_id,
            rule_id=DMA_TEMPERATURE_RULE_ID,
            template=DMA_TEMPERATURE_TEMPLATE,
            x_metric=DMA_TEMPERATURE_X_METRIC,
            y_metric=DMA_TEMPERATURE_Y_METRIC,
            raw_sources=(
                Path(item.path) for item in source_attestation.selected_sources
            ),
            prepared_source=input_path,
            terminal_source=input_path,
            sample_order=source_facts.sample_order,
            point_counts=dict(
                zip(
                    source_facts.sample_order,
                    source_facts.point_counts,
                    strict=True,
                )
            ),
        )
    terminal_options = {
        **options,
        "x_metric": DMA_TEMPERATURE_X_METRIC,
        "y_metric": DMA_TEMPERATURE_Y_METRIC,
    }
    result = render_selected_single_task_bundle(
        input_path,
        plan=plan,
        task=task,
        output_dir=output_dir,
        options=terminal_options,
        export_formats=export_formats,
        request=request,
        metric_id=DMA_TEMPERATURE_Y_METRIC,
        bundle_kind="dma_temperature_single_metric_figure_set",
        missing_reason_code="dma_temperature_task_artifacts_incomplete",
        terminal_source_binding=terminal_binding,
    )
    result["dma_temperature_execution_evidence"] = (
        build_dma_temperature_execution_evidence(
            plan=plan,
            task=task,
            facts=source_facts,
            result=result,
        )
    )
    return result


__all__ = ["_render_veusz_dma_temperature_bundle"]
