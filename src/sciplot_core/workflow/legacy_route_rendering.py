"""Execute unplanned legacy recipe and direct-render workflow routes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.workflow.request_io import _request_options
from sciplot_core.workflow.route_intent import WorkflowRouteIntent

RenderResultT = TypeVar("RenderResultT")


def _render_legacy_recipe_request(
    *,
    route_intent: WorkflowRouteIntent,
    final_recipe: str,
    request: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    transform_steps: list[dict[str, Any]],
    recipe_runner: Callable[..., dict[str, Any]],
    result_factory: Callable[..., RenderResultT],
) -> RenderResultT:
    """Run one recipe that has no selected FigurePlan or scientific snapshot."""

    result = recipe_runner(
        final_recipe,
        input_path,
        output_dir=output_dir,
        options=_request_options(request),
    )
    transform_steps.extend(
        step for step in result.get("transform_steps", []) if isinstance(step, dict)
    )
    return result_factory(
        route_intent=route_intent,
        final_recipe=final_recipe,
        result=result,
        plotted_data_source=Path(str(result.get("processed_source") or input_path)),
        selected_figure_plan=None,
    )


def _render_legacy_direct_request(
    *,
    route_intent: WorkflowRouteIntent,
    template: str,
    request: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    selected_figure_plan: ResolvedFigurePlan | None,
    render_with_auto_split: Callable[..., dict[str, Any]],
    result_factory: Callable[..., RenderResultT],
    write_render_report: Callable[..., None],
) -> RenderResultT:
    """Render one direct request after scientific and source-bound routes exit."""

    render_options = request.get("render_options")
    effective_render_request = (
        {
            **request,
            "rule_id": selected_figure_plan.rule_id,
        }
        if selected_figure_plan is not None
        else request
    )
    result = render_with_auto_split(
        input_path,
        template=template,
        output_dir=output_dir,
        options=render_options if isinstance(render_options, dict) else {},
        export_formats=request.get("exports"),
        request=effective_render_request,
        _resolved_figure_plan=selected_figure_plan,
    )
    rendered = result_factory(
        route_intent=route_intent,
        final_recipe=None,
        result=result,
        plotted_data_source=input_path,
        selected_figure_plan=selected_figure_plan,
    )
    write_render_report(output_dir, request=request, result=rendered.result)
    return rendered
