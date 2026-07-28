"""Execute the auto, recipe, or direct-render branch of a workflow request."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.materials_rules import compute_analysis_metrics
from sciplot_core.semantic import prepare_semantic_source
from sciplot_recipes import run_recipe

from sciplot_core.workflow.auto_split import _render_with_auto_split
from sciplot_core.workflow.reports import (
    _write_auto_report,
    _write_render_report,
)
from sciplot_core.workflow.request_io import (
    _request_options,
    _resolve_optional_request_path,
)


@dataclass(frozen=True)
class RequestRenderResult:
    """Route identity, renderer result, and source actually plotted."""

    route: str
    final_recipe: str | None
    result: dict[str, Any]
    plotted_data_source: Path


def execute_request_render(
    *,
    request: dict[str, Any],
    semantic: dict[str, Any],
    study_model: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    base_dir: Path,
    transform_steps: list[dict[str, Any]],
) -> RequestRenderResult:
    """Render a request through exactly one normalized route."""

    use_auto = request.get("recipe") == "auto" or (
        not request.get("recipe") and not request.get("template")
    )
    if use_auto:
        return _render_auto_request(
            request=request,
            semantic=semantic,
            study_model=study_model,
            input_path=input_path,
            output_dir=output_dir,
            base_dir=base_dir,
            transform_steps=transform_steps,
        )
    if request.get("recipe"):
        final_recipe = str(request["recipe"])
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
            route="recipe",
            final_recipe=final_recipe,
            result=result,
            plotted_data_source=Path(str(result.get("processed_source") or input_path)),
        )
    template = request.get("template")
    if not isinstance(template, str) or not template.strip():
        raise ValueError(
            "Plot requests without `recipe` must define a non-empty `template`."
        )
    render_options = request.get("render_options")
    result = _render_with_auto_split(
        input_path,
        template=template,
        output_dir=output_dir,
        options=render_options if isinstance(render_options, dict) else {},
        export_formats=request.get("exports"),
        request=request,
    )
    _write_render_report(output_dir, request=request, result=result)
    return RequestRenderResult(
        route="render",
        final_recipe=None,
        result=result,
        plotted_data_source=input_path,
    )


def _render_auto_request(
    *,
    request: dict[str, Any],
    semantic: dict[str, Any],
    study_model: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    base_dir: Path,
    transform_steps: list[dict[str, Any]],
) -> RequestRenderResult:
    final_recipe = semantic.get("recommended_recipe")
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
    _write_auto_report(
        output_dir,
        request=request,
        result=result,
        semantic=semantic,
        final_recipe=final_recipe,
    )
    return RequestRenderResult(
        route="auto",
        final_recipe=final_recipe,
        result=result,
        plotted_data_source=plotted_data_source,
    )
