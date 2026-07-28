"""Public workflow API and first-party compatibility facade."""

from __future__ import annotations

from sciplot_core.workflow.request_io import (  # noqa: F401
    _MANAGED_OUTPUT_DIRECTORIES,
    _MANAGED_OUTPUT_FILES,
    _load_request,
    _resolve_request_path,
    _resolve_optional_request_path,
    _bind_result_data_snapshots,
    _extend_runtime_transform_steps,
    _managed_output_transaction,
    _request_options,
    _archive_raw_input,
    _figures_from_result,
)
from sciplot_core.workflow.reports import (  # noqa: F401
    _write_render_report,
    _write_auto_report,
    _write_review_html,
    _layout_quality_from_result,
    _layout_summary_height_mm,
)
from sciplot_core.workflow.bundle_exports import (  # noqa: F401
    _SHARED_FIGURE_STYLE_KEYS,
    _metric_token,
    _rename_metric_exports,
)
from sciplot_core.workflow.rheology_bundle import (  # noqa: F401
    _RHEOLOGY_METRIC_LABELS,
    _sweep_prefix_for_request,
    _sweep_metric_sources,
    _render_veusz_sweep_bundle,
)
from sciplot_core.workflow.mechanical_bundle import (  # noqa: F401
    _MECHANICAL_FIGURE_CONTRACTS,
    _mechanical_summary_sources,
    _render_veusz_mechanical_bundle,
)
from pathlib import Path
from typing import Any

from sciplot_core.render import render_to_dir as render_to_dir
from sciplot_core.semantic import classify_source as classify_source
from sciplot_core.workflow.impact_bundle import (
    _impact_condition_sources,
    _render_veusz_impact_bundle as _render_veusz_impact_bundle_impl,
)
from sciplot_core.workflow.dsc_bundle import (  # noqa: F401
    _dsc_phase_sources,
    _render_veusz_dsc_bundle,
)
from sciplot_core.workflow.performance_bundle import (  # noqa: F401
    _render_veusz_performance_bundle,
)
from sciplot_core.workflow.auto_split import (  # noqa: F401
    _auto_split_policy_for_result,
    _render_with_auto_split,
    _compact_auto_split_options,
)
from sciplot_core.workflow.project_state import (  # noqa: F401
    _write_one_step_status,
    _next_run_dir,
    _one_step_project_dir,
    _write_revision_brief,
    _update_intake_project_after_run,
)
from sciplot_core.workflow.request_run import (
    _run_request_in_managed_output as _run_request_in_managed_output,
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
    template: str | None = None,
) -> dict[str, Any]:
    """Run the one-step route through the facade's current request runner."""

    return _run_one_step_impl(
        input_path,
        output_root=output_root,
        project_name=project_name,
        delivery_root=delivery_root,
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
    )


__all__ = ["run_one_step", "run_request"]
