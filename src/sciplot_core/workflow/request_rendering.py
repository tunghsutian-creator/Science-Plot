"""Execute the auto, recipe, or direct-render branch of a workflow request."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.terminal_binding import (
    BoundTerminalFigureEvidence,
    bind_terminal_figure_evidence,
)
from sciplot_core.materials_rules import compute_analysis_metrics
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
from sciplot_core.workflow.request_io import (
    _request_options,
    _resolve_optional_request_path,
)
from sciplot_core.workflow.route_intent import WorkflowRoute, WorkflowRouteIntent
from sciplot_core.workflow.dma_named_recipe import (
    DmaNamedRecipePlanBinding,
    bind_dma_named_recipe_request,
)


@dataclass(frozen=True)
class RequestRenderResult:
    """Route identity, renderer result, and source actually plotted."""

    route_intent: WorkflowRouteIntent
    final_recipe: str | None
    result: dict[str, Any]
    plotted_data_source: Path
    selected_figure_plan: ResolvedFigurePlan | None = None
    figure_evidence: BoundTerminalFigureEvidence | None = field(
        init=False,
        default=None,
    )

    def __post_init__(self) -> None:
        result = deepcopy(self.result)
        evidence = bind_terminal_figure_evidence(
            selected_plan=self.selected_figure_plan,
            result=result,
        )
        object.__setattr__(self, "result", result)
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
) -> RequestRenderResult:
    """Render a request through exactly one normalized route."""

    selected_figure_plan = resolved_figure_plan_from_payload(
        request.get("resolved_figure_plan")
    )
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
            )
        if selected_figure_plan is not None:
            raise ValueError(
                "workflow_recipe_figure_plan_unsupported: named recipes cannot "
                "execute this selected FigurePlan without a bounded exact-task seam."
            )
        result = run_recipe(
            final_recipe,
            input_path,
            output_dir=output_dir,
            options=_request_options(request),
        )
        transform_steps.extend(
            step for step in result.get("transform_steps", []) if isinstance(step, dict)
        )
        return RequestRenderResult(
            route_intent=route_intent,
            final_recipe=final_recipe,
            result=result,
            plotted_data_source=Path(str(result.get("processed_source") or input_path)),
            selected_figure_plan=None,
        )
    template = route_intent.requested_template
    if template is None:
        raise AssertionError("Direct-render route lost its captured template identity.")
    render_options = request.get("render_options")
    effective_render_request = (
        {
            **request,
            "rule_id": selected_figure_plan.rule_id,
        }
        if selected_figure_plan is not None
        else request
    )
    result = _render_with_auto_split(
        input_path,
        template=template,
        output_dir=output_dir,
        options=render_options if isinstance(render_options, dict) else {},
        export_formats=request.get("exports"),
        request=effective_render_request,
    )
    rendered = RequestRenderResult(
        route_intent=route_intent,
        final_recipe=None,
        result=result,
        plotted_data_source=input_path,
        selected_figure_plan=selected_figure_plan,
    )
    _write_render_report(output_dir, request=request, result=rendered.result)
    return rendered


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
            "Normalized stress ($\\sigma/\\sigma_0$)",
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
