"""Focused changed-owner mapping for shared axis and presentation policy."""

from __future__ import annotations

from sciplot_core.verification.owner_model import ChangedOwner


GENERIC_AXIS_OWNERS = (
    ChangedOwner(
        owner_id="generic_axis_policy",
        exact_paths=frozenset(
            {
                "src/sciplot_core/source_inspection/intent_recognition.py",
                "src/sciplot_core/source_inspection/header_matching.py",
                "src/sciplot_core/source_tables/parsing.py",
                "src/sciplot_core/render/inspection.py",
                "src/sciplot_core/studio_core/request_overrides.py",
                "src/sciplot_core/studio_core/veusz_axis_apply.py",
                "src/sciplot_core/studio_core/veusz_graph_setup.py",
                "src/sciplot_core/studio_core/veusz_apply.py",
                "src/sciplot_core/studio_core/veusz_canvas_finish.py",
                "src/sciplot_core/studio_render/axis_contract.py",
                "src/sciplot_core/studio_render/axis_extent.py",
                "src/sciplot_core/studio_render/axis_limits.py",
                "src/sciplot_core/studio_render/domain_defaults.py",
                "src/sciplot_core/studio_render/template_resolution.py",
                "src/sciplot_core/studio_render/series_option_context.py",
                "src/sciplot_core/studio_render/spectral_axis_display.py",
                "src/sciplot_core/studio_render/metric_columns.py",
                "src/sciplot_core/studio_render/table_io.py",
                "src/sciplot_core/studio_render/replicate_distribution_contract.py",
                "src/sciplot_core/studio_render/categorical_layout.py",
                "src/sciplot_core/studio_render/categorical_series.py",
                "src/sciplot_core/veusz_worker/axis_matchers.py",
                "src/sciplot_core/studio_render/readability_defaults.py",
                "src/sciplot_core/studio_render/legend_placement.py",
            }
        ),
        owned_test_paths=frozenset(
            {
                "tests/test_generic_axis_policy.py",
                "tests/test_template_override_contract.py",
                "tests/test_compatibility_facades.py",
                "tests/test_legacy_core_migration.py",
                "tests/test_source_numeric_encodings.py",
                "tests/test_replicate_distribution_contract.py",
                "tests/test_task_ordinary_raw_points.py",
                "tests/test_task_ordinary_raw_points_native.py",
                "tests/test_marker_axis_extent.py",
                "tests/test_registered_single_curve_figure_plan.py",
                "tests/test_semantic_validation.py",
                "tests/test_source_recognition_contract.py",
                "tests/test_spectral_axis_display.py",
                "tests/test_spectral_axis_display_native.py",
                "tests/test_studio_request_overrides.py",
                "tests/test_temperature_figure_plan_activation.py",
            }
        ),
        pytest_targets=(
            "tests/test_task_control.py",
            "tests/test_compatibility_facades.py",
            "tests/test_legacy_core_migration.py",
            "tests/test_source_numeric_encodings.py",
            "tests/test_generic_prepared_terminal_source.py",
            "tests/test_maintenance_integrity.py::test_studio_directory_read_fails_closed_on_one_unreadable_table",
            "tests/test_managed_document_science.py",
            "tests/test_scalar_field_rendering.py",
            "tests/test_replicate_distribution_contract.py",
            "tests/test_task_ordinary_raw_points.py",
            "tests/test_task_ordinary_raw_points_native.py",
            "tests/test_plan_preview.py",
            "tests/test_generic_axis_policy.py",
            "tests/test_template_override_contract.py",
            "tests/test_marker_axis_extent.py",
            "tests/test_mechanical_rendering_profile_native.py",
            "tests/test_registered_single_curve_figure_plan.py",
            "tests/test_semantic_validation.py",
            "tests/test_source_recognition_contract.py",
            "tests/test_spectral_axis_display.py",
            "tests/test_spectral_axis_display_native.py",
            "tests/test_studio_request_overrides.py",
            "tests/test_temperature_figure_plan_activation.py",
        ),
        release_gates=("full_pytest",),
    ),
)


__all__ = ["GENERIC_AXIS_OWNERS"]
