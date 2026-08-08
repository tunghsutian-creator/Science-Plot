"""Stable public and first-party compatibility facade for SciPlot Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.studio_render.models import (
    IMPACT_POINT_LINE_MARKER_KIND as IMPACT_POINT_LINE_MARKER_KIND,
    IMPACT_POINT_LINE_RAW_KIND as IMPACT_POINT_LINE_RAW_KIND,
    IMPACT_POINT_LINE_SUMMARY_KIND as IMPACT_POINT_LINE_SUMMARY_KIND,
    StudioPreparationBlocked as StudioPreparationBlocked,
    StudioSeries as StudioSeries,
    StudioSourceFrame as StudioSourceFrame,
    _VeuszAxisContract as _VeuszAxisContract,
    _VeuszStyleContract as _VeuszStyleContract,
)
from sciplot_core.studio_render.categorical_layout import (
    _apply_categorical_box_aspect_width as _apply_categorical_box_aspect_width,
)
from sciplot_core.studio_render.domain_defaults import (
    _apply_domain_render_defaults as _apply_domain_render_defaults,
)
from sciplot_core.studio_render.readability_defaults import (
    _apply_readability_render_defaults as _apply_readability_render_defaults,
)
from sciplot_core.studio_render.series_domain import (
    _apply_series_domain_contract_defaults as _apply_series_domain_contract_defaults,
    _resolved_domain_render_options as _resolved_domain_render_options,
    _validate_log_domain_series as _validate_log_domain_series,
)
from sciplot_core.studio_render.series_options import (
    _apply_series_options as _apply_series_options,
    resolve_series_encodings as resolve_series_encodings,
)
from sciplot_core.studio_core.request_overrides import (
    _apply_studio_request_overrides as _apply_studio_request_overrides,
)
from sciplot_core.studio_render.axes_spec import (
    _categorical_axis_label_contracts as _categorical_axis_label_contracts,
    _reference_guides_contract as _reference_guides_contract,
)
from sciplot_core.studio_core.legend_contracts import (
    _categorical_component_legend_label_contracts as _categorical_component_legend_label_contracts,
    _categorical_component_legend_rect_contracts as _categorical_component_legend_rect_contracts,
    _categorical_grouped_bar_fill_rect_contracts as _categorical_grouped_bar_fill_rect_contracts,
    _curve_factor_legend_condition_rect_contracts as _curve_factor_legend_condition_rect_contracts,
    _curve_factor_legend_label_contracts as _curve_factor_legend_label_contracts,
    _curve_factor_legend_line_contracts as _curve_factor_legend_line_contracts,
)
from sciplot_core.studio_core.guide_contracts import (
    _categorical_line_contracts as _categorical_line_contracts,
    _reference_guide_line_contracts as _reference_guide_line_contracts,
    _reference_guide_rect_contracts as _reference_guide_rect_contracts,
)
from sciplot_core.studio_render.categorical_plot_spec import (
    _categorical_plot_contract as _categorical_plot_contract,
)
from sciplot_core.studio_render.table_io import (
    _coerced_numeric_frame as _coerced_numeric_frame,
    _read_source_frame_records as _read_source_frame_records,
)
from sciplot_core.studio_core.qt_window import (
    _create_veusz_window as _create_veusz_window,
    configure_studio_window_presentation as configure_studio_window_presentation,
)
from sciplot_core.studio_render.categorical_values import (
    _deterministic_category_positions as _deterministic_category_positions,
    _veusz_axis_label as _veusz_axis_label,
)
from sciplot_core.studio_core.qt_compat import (
    _ensure_veusz_loader_compat as _ensure_veusz_loader_compat,
    ensure_veusz_qsettings_compat as ensure_veusz_qsettings_compat,
)
from sciplot_core.studio_core.runtime import (
    _ensure_veusz_on_path as _ensure_veusz_on_path,
    _qt_framework_paths as _qt_framework_paths,
    _split_formats as _split_formats,
    maybe_reexec_with_qt_runtime as maybe_reexec_with_qt_runtime,
    upstream_status as upstream_status,
)
from sciplot_core.studio_render.axis_extent import (
    _expand_axis_for_visual_extents as _expand_axis_for_visual_extents,
)
from sciplot_core.studio_core.figure_requests import (
    _impact_condition_figure_queue as _impact_condition_figure_queue,
    _impact_condition_figure_request as _impact_condition_figure_request,
)
from sciplot_core.studio_core.impact_series import (
    _impact_point_line_series_from_source as _impact_point_line_series_from_source,
)
from sciplot_core.studio_render.template_resolution import (
    _looks_like_frequency_axis as _looks_like_frequency_axis,
    _request_template as _request_template,
)
from sciplot_core.studio_core.series_request import (
    _mapping_series_coverage as _mapping_series_coverage,
    _marker_thin_factor as _marker_thin_factor,
    _series_from_request as _series_from_request,
    _veusz_literal_text as _veusz_literal_text,
)
from sciplot_core.studio_core.figure_set_state import (
    _read_studio_figure_set as _read_studio_figure_set,
    _replace_studio_figure_set_path as _replace_studio_figure_set_path,
    _studio_figure_set_export_scope as _studio_figure_set_export_scope,
    build_studio_figure_set_export_scope as build_studio_figure_set_export_scope,
)
from sciplot_core.studio_core.veusz_save import (
    _save_veusz_document_from_spec as _save_veusz_document_from_spec,
)
from sciplot_core.studio_render.scalar_series import (
    _scalar_field_from_frames as _scalar_field_from_frames,
)
from sciplot_core.studio_render.scalar_plot_spec import (
    _scalar_field_plot_contract as _scalar_field_plot_contract,
)
from sciplot_core.studio_core.axis_identity import (
    _semantic_payload_with_exact_current_axes as _semantic_payload_with_exact_current_axes,
)
from sciplot_core.studio_core.semantic_payloads import (
    _semantic_payload_with_terminal_axes as _semantic_payload_with_terminal_axes,
    _studio_export_semantic_payload as _studio_export_semantic_payload,
)
from sciplot_core.studio_render.frame_series import (
    _series_from_frame_records as _series_from_frame_records,
)
from sciplot_core.studio_render.metric_columns import (
    _series_label_from_column as _series_label_from_column,
)
from sciplot_core.studio_render.series_transforms import (
    _apply_template_series_transforms as _apply_template_series_transforms,
    _stack_studio_series as _stack_studio_series,
)
from sciplot_core.studio_figure_set_contract import (
    is_primary_figure_set_export_scope as _is_primary_figure_set_export_scope,  # noqa: F401
)
from sciplot_core.studio_core.persistence import (
    _standalone_export_artifact_root as _standalone_export_artifact_root,
    _validate_staged_veusz_document as _validate_staged_veusz_document,
    atomic_save_veusz_document as _atomic_save_veusz_document,
    migrate_studio_document_unit_labels as migrate_studio_document_unit_labels,
)
from sciplot_core.studio_core.source_snapshots import (
    _studio_snapshot_sources as _studio_snapshot_sources,
)
from sciplot_core.studio_render.axis_contract import (
    _veusz_axis_contract as _veusz_axis_contract,
)
from sciplot_core.studio_core.registry_state import (
    _studio_document_state as _studio_document_state,
    _veusz_spec_path as _veusz_spec_path,
)
from sciplot_core.studio_core.document_archive import (
    _archive_manual_document_if_needed as _archive_manual_document_if_needed,
)
from sciplot_core.studio_render.style_contract import (
    _veusz_style_contract as _veusz_style_contract,
)
from sciplot_core.studio_core.veusz_document import (
    _write_veusz_document as _write_veusz_document,
)
from sciplot_core.studio_render.terminal_contract import (
    derive_terminal_render_data_contract as derive_terminal_render_data_contract,
)
from sciplot_core.studio_core.export_execution import (
    export_studio_document as export_studio_document,
)
from sciplot_core.studio_core.studio_prepare import (
    prepare_studio_document as _prepare_studio_document,
)
from sciplot_core.studio_core.standalone_receipt import (
    publish_standalone_export_receipt as publish_standalone_export_receipt,
)
from sciplot_core.studio_core.publish_run import (
    publish_studio_export_run as publish_studio_export_run,
)
from sciplot_core.studio_core.qt_launch import (
    qt_smoke_payload as qt_smoke_payload,
)
from sciplot_core.studio_core.context import (
    resolve_studio_project_context as resolve_studio_project_context,
)
from sciplot_core.studio_core.studio_command import (
    run_studio_command as run_studio_command,
)


def atomic_save_veusz_document(document: Any, target: Path) -> dict[str, Any]:
    """Save through the split persistence module while preserving patch seams."""

    return _atomic_save_veusz_document(
        document,
        target,
        staged_validator=_validate_staged_veusz_document,
    )


def prepare_studio_document(
    target: str | Path,
    *,
    output_root: Path | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    regenerate_generated: bool = False,
) -> dict[str, Any]:
    """Prepare through the split core while preserving transaction patch seams."""

    return _prepare_studio_document(
        target,
        output_root=output_root,
        delivery_root=delivery_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
        regenerate_generated=regenerate_generated,
        figure_set_path_replacer=_replace_studio_figure_set_path,
    )


def read_studio_figure_set(project_dir: Path) -> dict[str, Any] | None:
    """Return the validated, canonical-path Studio figure-set registry."""

    return _read_studio_figure_set(project_dir.expanduser().resolve())


__all__ = [
    "atomic_save_veusz_document",
    "build_studio_figure_set_export_scope",
    "configure_studio_window_presentation",
    "ensure_veusz_qsettings_compat",
    "export_studio_document",
    "maybe_reexec_with_qt_runtime",
    "migrate_studio_document_unit_labels",
    "prepare_studio_document",
    "publish_standalone_export_receipt",
    "publish_studio_export_run",
    "qt_smoke_payload",
    "read_studio_figure_set",
    "resolve_series_encodings",
    "resolve_studio_project_context",
    "run_studio_command",
    "upstream_status",
]
