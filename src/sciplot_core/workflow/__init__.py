"""Public workflow API and first-party compatibility facade."""

from __future__ import annotations

from sciplot_core.workflow.request_io import (  # noqa: F401
    _managed_output_transaction,
)
from sciplot_core.workflow.mechanical_bundle import (  # noqa: F401
    _mechanical_summary_sources,
)
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.render import render_to_dir as render_to_dir
from sciplot_core.semantic import classify_source as classify_source
from sciplot_core.workflow.impact_bundle import (
    _impact_condition_sources,
    _render_veusz_impact_bundle as _render_veusz_impact_bundle_impl,
)
from sciplot_core.workflow.project_state import (  # noqa: F401
    _next_run_dir,
)
from sciplot_core.workflow.request_run import (
    run_request as _run_request_impl,
)
from sciplot_core.workflow.one_step_entry import (
    run_one_step as _run_one_step_impl,
)


def run_request(request_path: Path) -> dict[str, Any]:
    """Run a request through the stable facade and injectable classifier seam."""

    return _run_request_impl(request_path, _classifier=classify_source)


def run_one_step(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
) -> dict[str, Any]:
    """Run the one-step route through the facade's current request runner."""

    return _run_one_step_impl(
        input_path,
        output_root=output_root,
        project_name=project_name,
        delivery_root=delivery_root,
        rule_id=rule_id,
        template=template,
        _request_runner=run_request,
    )


def _render_veusz_impact_bundle(
    source_input: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> dict[str, Any] | None:
    """Render impact figures with explicit source and renderer dependencies."""

    return _render_veusz_impact_bundle_impl(
        source_input,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
        _source_builder=_impact_condition_sources,
        _renderer=render_to_dir,
        _resolved_figure_plan=_resolved_figure_plan,
    )


__all__ = ["run_one_step", "run_request"]
