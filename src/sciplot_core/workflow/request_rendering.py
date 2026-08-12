"""Execute the auto, recipe, or direct-render branch of a workflow request."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.figure_plan.plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.execution import finalize_figure_plan_result
from sciplot_core.figure_plan.terminal_binding import (
    BoundTerminalFigureEvidence,
    bind_terminal_figure_evidence,
)
from sciplot_core.materials_rules import (
    NORMALIZED_STRESS_RATIO_DISPLAY_LABEL,
    compute_analysis_metrics,
)
from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.semantic import prepare_semantic_source
from sciplot_recipes import run_recipe
from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_RECIPE,
    DMA_TEMPERATURE_RULE_ID,
)

from sciplot_core.workflow.auto_split import _render_with_auto_split
from sciplot_core.workflow.reports import (
    _write_auto_report,
    _write_render_report,
)
from sciplot_core.workflow.request_io import _resolve_optional_request_path
from sciplot_core.workflow.route_intent import WorkflowRoute, WorkflowRouteIntent
from sciplot_core.workflow.dma_named_recipe import (
    DmaNamedRecipePlanBinding,
    bind_dma_named_recipe_request,
)
from sciplot_core.workflow.legacy_route_rendering import (
    _render_legacy_direct_request,
    _render_legacy_recipe_request,
)

if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source import (
        ResolvedScientificSource,
    )


@dataclass(frozen=True)
class RequestRenderResult:
    """Route identity, renderer result, and source actually plotted."""

    route_intent: WorkflowRouteIntent
    final_recipe: str | None
    result: dict[str, Any]
    plotted_data_source: Path
    selected_figure_plan: ResolvedFigurePlan | None = None
    completed_figure_plan: ResolvedFigurePlan | None = field(
        init=False,
        default=None,
    )
    figure_evidence: BoundTerminalFigureEvidence | None = field(
        init=False,
        default=None,
    )

    def __post_init__(self) -> None:
        result = deepcopy(self.result)
        terminal_evidence = bind_terminal_figure_evidence(
            selected_plan=self.selected_figure_plan,
            result=result,
        )
        completed = (
            terminal_evidence.completed_plan
            if terminal_evidence is not None
            and terminal_evidence.completed_plan is not None
            else finalize_figure_plan_result(self.selected_figure_plan, result)
        )
        evidence = terminal_evidence
        if terminal_evidence is not None and completed is not None:
            result["resolved_figure_plan"] = completed.to_payload()
            result.pop("figure_outcomes", None)
            evidence = BoundTerminalFigureEvidence(
                selected_plan=terminal_evidence.selected_plan,
                terminal_tasks=terminal_evidence.terminal_tasks,
                reported_outcomes=completed.outcomes,
                completed_plan=completed,
            )
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "completed_figure_plan", completed)
        object.__setattr__(self, "figure_evidence", evidence)

    @property
    def route(self) -> WorkflowRoute:
        """Compatibility projection of the captured workflow route."""

        return self.route_intent.route


def execute_request_render(
    *,
    request: dict[str, Any],
    route_intent: WorkflowRouteIntent,
    semantic: dict[str, Any],
    study_model: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    base_dir: Path,
    transform_steps: list[dict[str, Any]],
    resolved_scientific_source: ResolvedScientificSource | None = None,
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> RequestRenderResult:
    """Render a request through exactly one normalized route."""

    selected_figure_plan = _resolved_figure_plan
    plan_payload = request.get("resolved_figure_plan")
    if selected_figure_plan is None and plan_payload is not None:
        selected_figure_plan = resolved_figure_plan_from_payload(plan_payload)
    if selected_figure_plan is not None:
        request_rule = request.get("rule_id")
        semantic_rule = semantic.get("rule_id")
        if (
            request_rule is not None and request_rule != selected_figure_plan.rule_id
        ) or (
            isinstance(semantic_rule, str)
            and semantic_rule.strip()
            and semantic_rule.strip() != selected_figure_plan.rule_id
        ):
            raise ValueError(
                "workflow_figure_plan_rule_mismatch: selected FigurePlan rule "
                "does not match the render request."
            )
    if route_intent.route == "auto":
        return _render_auto_request(
            request=request,
            route_intent=route_intent,
            semantic=semantic,
            study_model=study_model,
            input_path=input_path,
            output_dir=output_dir,
            base_dir=base_dir,
            transform_steps=transform_steps,
            selected_figure_plan=selected_figure_plan,
            resolved_scientific_source=resolved_scientific_source,
        )
    if route_intent.route == "recipe":
        final_recipe = route_intent.requested_recipe
        if final_recipe is None:
            raise AssertionError("Recipe route lost its captured recipe identity.")
        if (
            selected_figure_plan is not None
            and final_recipe == DMA_TEMPERATURE_RECIPE
            and selected_figure_plan.rule_id == DMA_TEMPERATURE_RULE_ID
        ):
            binding = bind_dma_named_recipe_request(
                requested_recipe=final_recipe,
                request=request,
                semantic=semantic,
                plan=selected_figure_plan,
                input_path=input_path,
                resolved_scientific_source=resolved_scientific_source,
            )
            return _render_semantic_plan_request(
                request=request,
                route_intent=route_intent,
                semantic=semantic,
                study_model=study_model,
                input_path=input_path,
                output_dir=output_dir,
                base_dir=base_dir,
                transform_steps=transform_steps,
                selected_figure_plan=selected_figure_plan,
                final_recipe=final_recipe,
                named_recipe_binding=binding,
                resolved_scientific_source=resolved_scientific_source,
            )
        if resolved_scientific_source is not None:
            return _render_semantic_plan_request(
                request=request,
                route_intent=route_intent,
                semantic=semantic,
                study_model=study_model,
                input_path=input_path,
                output_dir=output_dir,
                base_dir=base_dir,
                transform_steps=transform_steps,
                selected_figure_plan=selected_figure_plan,
                final_recipe=final_recipe,
                named_recipe_binding=None,
                resolved_scientific_source=resolved_scientific_source,
            )
        if selected_figure_plan is not None:
            raise ValueError(
                "workflow_recipe_figure_plan_unsupported: named recipes cannot "
                "execute this selected FigurePlan without a bounded exact-task seam."
            )
        return _render_legacy_recipe_request(
            route_intent=route_intent,
            final_recipe=final_recipe,
            request=request,
            input_path=input_path,
            output_dir=output_dir,
            transform_steps=transform_steps,
            recipe_runner=run_recipe,
            result_factory=RequestRenderResult,
        )
    template = route_intent.requested_template
    if template is None:
        raise AssertionError("Direct-render route lost its captured template identity.")
    if (
        resolved_scientific_source is not None
        or (
            selected_figure_plan is not None
            and selected_figure_plan.rule_id in MECHANICAL_RULE_IDS
        )
    ):
        return _render_semantic_plan_request(
            request=request,
            route_intent=route_intent,
            semantic=semantic,
            study_model=study_model,
            input_path=input_path,
            output_dir=output_dir,
            base_dir=base_dir,
            transform_steps=transform_steps,
            selected_figure_plan=selected_figure_plan,
            final_recipe=None,
            named_recipe_binding=None,
            resolved_scientific_source=resolved_scientific_source,
        )
    return _render_legacy_direct_request(
        route_intent=route_intent,
        template=template,
        request=request,
        input_path=input_path,
        output_dir=output_dir,
        selected_figure_plan=selected_figure_plan,
        render_with_auto_split=_render_with_auto_split,
        result_factory=RequestRenderResult,
        write_render_report=_write_render_report,
    )


def _render_auto_request(
    *,
    request: dict[str, Any],
    route_intent: WorkflowRouteIntent,
    semantic: dict[str, Any],
    study_model: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    base_dir: Path,
    transform_steps: list[dict[str, Any]],
    selected_figure_plan: ResolvedFigurePlan | None,
    resolved_scientific_source: ResolvedScientificSource | None,
) -> RequestRenderResult:
    """Execute the automatic route through shared semantic-plan preparation."""

    return _render_semantic_plan_request(
        request=request,
        route_intent=route_intent,
        semantic=semantic,
        study_model=study_model,
        input_path=input_path,
        output_dir=output_dir,
        base_dir=base_dir,
        transform_steps=transform_steps,
        selected_figure_plan=selected_figure_plan,
        final_recipe=(
            str(semantic["recommended_recipe"])
            if semantic.get("recommended_recipe") is not None
            else None
        ),
        named_recipe_binding=None,
        resolved_scientific_source=resolved_scientific_source,
    )


def _render_semantic_plan_request(
    *,
    request: dict[str, Any],
    route_intent: WorkflowRouteIntent,
    semantic: dict[str, Any],
    study_model: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    base_dir: Path,
    transform_steps: list[dict[str, Any]],
    selected_figure_plan: ResolvedFigurePlan | None,
    final_recipe: str | None,
    named_recipe_binding: DmaNamedRecipePlanBinding | None,
    resolved_scientific_source: ResolvedScientificSource | None,
) -> RequestRenderResult:
    """Prepare semantic data once and execute the already-selected plan."""

    replicate_policy = (
        study_model.get("replicate_policy")
        if isinstance(study_model.get("replicate_policy"), dict)
        else {}
    )
    effective_replicate_mode = request.get("replicate_mode") or replicate_policy.get(
        "mode"
    )
    prepared = prepare_semantic_source(
        input_path,
        output_dir=output_dir,
        semantic=semantic,
        curation_path=_resolve_optional_request_path(
            request.get("curation"),
            base_dir=base_dir,
        ),
        series_order=request.get("series_order"),
        column_confirmations=request.get("column_confirmations"),
        replicate_mode=effective_replicate_mode,
        resolved_scientific_source=resolved_scientific_source,
    )
    transform_steps.extend(
        step for step in prepared.get("transform_steps", []) if isinstance(step, dict)
    )
    render_options = dict(semantic.get("render_options") or {})
    request_render_options = request.get("render_options")
    if isinstance(request_render_options, dict):
        render_options.update(request_render_options)
    if semantic.get("rule_id") == "rheology_stress_relaxation":
        render_options.setdefault("x_label_override", "Time (s)")
        render_options.setdefault(
            "y_label_override",
            NORMALIZED_STRESS_RATIO_DISPLAY_LABEL,
        )
    template = request.get("template") or semantic["template"]
    effective_render_request = {
        **request,
        "rule_id": semantic.get("rule_id"),
        "study_model": study_model,
        "template": template,
    }
    result = _render_with_auto_split(
        Path(str(prepared["source"])),
        source_input=input_path,
        source_attestation=(
            prepared.get("source_attestation")
            if isinstance(
                prepared.get("source_attestation"), PreparationSourceAttestation
            )
            else None
        ),
        template=str(template),
        output_dir=output_dir,
        options=render_options,
        export_formats=request.get("exports"),
        request=effective_render_request,
        _terminal_source_prepared=True,
        _resolved_scientific_source=resolved_scientific_source,
        _resolved_figure_plan=selected_figure_plan,
    )
    plotted_data_source = Path(str(prepared["source"]))
    processed_source = (
        Path(str(prepared["processed_source"]))
        if prepared["processed_source"]
        else None
    )
    result = {
        **result,
        "semantic_family": semantic["semantic_family"],
        "rule_id": semantic.get("rule_id"),
        "final_recipe": final_recipe,
        "processed": prepared["processed"],
        "processed_source": prepared["processed_source"],
        "analysis_metrics": compute_analysis_metrics(
            source_path=input_path,
            processed_source=processed_source,
            semantic=semantic,
            output_dir=output_dir,
        ),
    }
    if named_recipe_binding is not None:
        result["named_recipe_plan_binding"] = named_recipe_binding.to_payload()
    rendered = RequestRenderResult(
        route_intent=route_intent,
        final_recipe=final_recipe,
        result=result,
        plotted_data_source=plotted_data_source,
        selected_figure_plan=selected_figure_plan,
    )
    _write_auto_report(
        output_dir,
        request=request,
        result=rendered.result,
        semantic=semantic,
        final_recipe=final_recipe,
        route=route_intent.route,
    )
    return rendered
