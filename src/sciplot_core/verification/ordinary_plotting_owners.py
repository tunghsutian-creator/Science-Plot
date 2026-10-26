"""Exact ordinary plotting leaves and their public scientific regressions.

Shared task, plan, source-audit and native gateways retain their existing broad
owners. These additional selectors ensure each new front door reaches its own
generated pure and native controls without claiming future neighboring files.
"""

from sciplot_core.verification.owner_model import ChangedOwner
from sciplot_core.verification.type_gate_owners import ARCHITECTURE_CORE_TARGETS


ORDINARY_TASK_LEAF_PATHS = frozenset(
    {
        "src/sciplot_core/task_semantic_axes.py",
        "src/sciplot_core/task_semantic_curve_bindings.py",
        "src/sciplot_core/task_missing_values.py",
        "src/sciplot_core/task_replicate_summary.py",
        "src/sciplot_core/task_categorical_contract.py",
        "src/sciplot_core/task_categorical_creation.py",
    }
)
APPEND_IDENTITY_LEAF_PATH = (
    "src/sciplot_core/plot_engine/append_measurement_identity.py"
)

CURVE_TESTS = (
    "tests/test_ordinary_curve_intent.py",
    "tests/test_ordinary_curve_intent_native.py",
    "tests/test_semantic_source_regions.py",
)
REPLICATE_TESTS = (
    "tests/test_task_replicate_count.py",
    "tests/test_task_replicate_count_native.py",
    "tests/test_replicate_disclosure_audit.py",
)
PERFORMANCE_TESTS = (
    "tests/test_performance_metric_selection.py",
    "tests/test_performance_selection_cli.py",
    "tests/test_performance_source_numeric_modes.py",
    "tests/test_performance_metadata_boundaries.py",
)
CATEGORICAL_TESTS = (
    "tests/test_categorical_source_identity.py",
    "tests/test_source_group_consumers.py",
    "tests/test_task_ordinary_categorical.py",
    "tests/test_task_ordinary_categorical_native.py",
    "tests/test_categorical_legend_boundary.py",
    "tests/test_segmented_summary_legend.py",
    "tests/test_segmented_summary_legend_native.py",
    "tests/test_zero_sd_bar_outline.py",
        "tests/test_grouped_bar_mark_contract.py",
    )
CATEGORICAL_EDIT_TESTS = (
    "tests/test_categorical_display.py",
    "tests/test_categorical_display_failures.py",
    "tests/test_categorical_display_native.py",
)

ORDINARY_CURVE_OWNER = ChangedOwner(
    owner_id="ordinary_curve_source_bindings",
    exact_paths=frozenset(
        {
            "src/sciplot_core/task_semantic_axes.py",
            "src/sciplot_core/task_semantic_curve_bindings.py",
            "src/sciplot_core/task_semantic_contract.py",
            "src/sciplot_core/task_semantic_creation.py",
            "src/sciplot_core/task_semantic_figure.py",
            "src/sciplot_core/task_semantic_frequency.py",
            "src/sciplot_core/task_semantic_plan.py",
            "src/sciplot_core/task_contract.py",
            "src/sciplot_core/task_control.py",
            "src/sciplot_core/cli/parsers/tasks.py",
            "src/sciplot_core/cli/dispatch/tasks.py",
            APPEND_IDENTITY_LEAF_PATH,
            "src/sciplot_core/plot_engine/managed_source_append.py",
            "src/sciplot_core/plot_grammar/ir.py",
            "src/sciplot_core/plot_grammar/schema.py",
            "src/sciplot_core/plot_grammar/validation.py",
        }
    ),
    owned_test_paths=frozenset(CURVE_TESTS),
    pytest_targets=(
        *CURVE_TESTS,
        "tests/test_task_semantic_creation.py",
        "tests/test_managed_source_append.py",
        "tests/test_managed_source_append_units.py",
        "tests/test_managed_source_append_regions.py",
        "tests/test_managed_source_append_native.py",
        "tests/test_task_semantic_selection.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("full_pytest",),
)

REPLICATE_DISCLOSURE_OWNER = ChangedOwner(
    owner_id="replicate_count_disclosure",
    exact_paths=frozenset(
        {
            "src/sciplot_core/task_missing_values.py",
            "src/sciplot_core/task_replicate_summary.py",
            "src/sciplot_core/semantic_sources/impact_replicate_disclosure.py",
            "src/sciplot_core/source_coverage/replicate_disclosure.py",
            "src/sciplot_core/materials_rules/impact_presentation.py",
            "src/sciplot_core/task_capabilities.py",
            "src/sciplot_core/task_contract.py",
            "src/sciplot_core/task_control.py",
            "src/sciplot_core/task_planning.py",
            "src/sciplot_core/cli/parsers/tasks.py",
            "src/sciplot_core/cli/dispatch/tasks.py",
            "src/sciplot_core/plan_preview.py",
            "src/sciplot_core/plan_preview_contract.py",
            "src/sciplot_core/plan_source_options.py",
            "src/sciplot_core/plot_data/spec_tables.py",
            "src/sciplot_core/plot_data/exports.py",
            "src/sciplot_core/studio_core/publish_sources.py",
            "src/sciplot_core/source_coverage/managed_documents.py",
        }
    ),
    owned_test_paths=frozenset(REPLICATE_TESTS),
    pytest_targets=(
        *REPLICATE_TESTS,
        "tests/test_impact_condition_figure_set.py",
        "tests/test_plan_preview.py",
        "tests/test_replicate_distribution_contract.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)

PERFORMANCE_SELECTION_OWNER = ChangedOwner(
    owner_id="performance_metric_selection",
    exact_paths=frozenset(
        {
            "src/sciplot_core/performance_comparison/__init__.py",
            "src/sciplot_core/performance_comparison/metadata.py",
            "src/sciplot_core/performance_comparison/selection.py",
            "src/sciplot_core/performance_comparison/selection_rows.py",
            "src/sciplot_core/performance_comparison/selected_scatter.py",
            "src/sciplot_core/performance_comparison/layout.py",
            "src/sciplot_core/performance_comparison/models.py",
            "src/sciplot_core/performance_comparison/public_api.py",
            "src/sciplot_core/performance_comparison/scatter.py",
            "src/sciplot_core/performance_comparison/source_loading.py",
            "src/sciplot_core/performance_comparison/source_rows.py",
            "src/sciplot_core/performance_comparison/source_tables.py",
            "src/sciplot_core/performance_veusz/spec_builder.py",
            "src/sciplot_core/performance_veusz/style.py",
            "src/sciplot_core/performance_veusz/contracts.py",
            "src/sciplot_core/performance_veusz/apply.py",
            "src/sciplot_core/performance_veusz/widget_apply.py",
            "src/sciplot_core/veusz_worker/spec_audit/labels.py",
            "src/sciplot_core/veusz_worker/spec_audit/series.py",
            "src/sciplot_core/source_coverage/managed_documents.py",
            "src/sciplot_core/studio_core/series_request.py",
            "src/sciplot_core/figure_plan/performance_resolution.py",
            "src/sciplot_core/plan_preview.py",
            "src/sciplot_core/plan_preview_contract.py",
            "src/sciplot_core/plan_source_options.py",
            "src/sciplot_core/cli/parsers/diagnostics.py",
            "src/sciplot_core/cli/dispatch/diagnostics.py",
        }
    ),
    owned_test_paths=frozenset(PERFORMANCE_TESTS),
    pytest_targets=(
        *PERFORMANCE_TESTS,
        "tests/test_performance_comparison.py",
        "tests/test_performance_veusz.py",
        "tests/test_resolved_figure_plan.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)

CATEGORICAL_SOURCE_OWNER = ChangedOwner(
    owner_id="ordinary_categorical_sources",
    exact_paths=frozenset(
        {
            "src/sciplot_core/mapping_contract/categorical_identity.py",
            "src/sciplot_core/studio_render/categorical_source_identity.py",
            "src/sciplot_core/veusz_worker/spec_audit/categorical_identity.py",
            "src/sciplot_core/categorical_plan.py",
            "src/sciplot_core/categorical_disclosure.py",
            "src/sciplot_core/mapping_contract/categorical.py",
            "src/sciplot_core/task_categorical_contract.py",
            "src/sciplot_core/task_categorical_creation.py",
            "src/sciplot_core/studio_render/categorical_bindings.py",
            "src/sciplot_core/studio_render/categorical_components.py",
            "src/sciplot_core/studio_render/categorical_plot_spec.py",
            "src/sciplot_core/studio_render/categorical_bound_series.py",
            "src/sciplot_core/studio_render/source_group_series.py",
            "src/sciplot_core/studio_render/paired_source_identity.py",
            "src/sciplot_core/studio_render/categorical_legend.py",
            "src/sciplot_core/studio_render/component_legend.py",
            "src/sciplot_core/studio_render/segmented_legend_clearance.py",
            "src/sciplot_core/veusz_audit/segmented_legend_geometry.py",
            "src/sciplot_core/veusz_audit/document.py",
            "src/sciplot_core/studio_core/current_layout_review.py",
            "src/sciplot_core/studio_core/legend_specs.py",
            "src/sciplot_core/studio_core/review_artifacts.py",
            "src/sciplot_core/studio_core/guide_contracts.py",
            "src/sciplot_core/studio_render/categorical_groups.py",
            "src/sciplot_core/studio_render/frame_series.py",
            "src/sciplot_core/studio_render/replicate_distribution_contract.py",
            "src/sciplot_core/studio_render/series_options.py",
            "src/sciplot_core/studio_render/table_io.py",
            "src/sciplot_core/studio_render/domain_defaults.py",
            "src/sciplot_core/studio_render/legend_clearance.py",
            "src/sciplot_core/studio_render/legend_placement.py",
            "src/sciplot_core/studio_render/legend_visibility.py",
            "src/sciplot_core/studio_render/readability_defaults.py",
            "src/sciplot_core/studio_render/series_option_context.py",
            "src/sciplot_core/studio_core/project_receipt.py",
            "src/sciplot_core/studio_core/project_query_evidence.py",
            "src/sciplot_core/studio_core/series_request.py",
            "src/sciplot_core/studio_core/veusz_spec_labels.py",
            "src/sciplot_core/studio_core/semantic_validation.py",
            "src/sciplot_core/studio_core/veusz_document.py",
            "src/sciplot_core/studio_core/veusz_spec_layout.py",
            "src/sciplot_core/studio_core/veusz_spec_series.py",
            "src/sciplot_core/task_contract.py",
            "src/sciplot_core/task_control.py",
            "src/sciplot_core/task_execution.py",
            "src/sciplot_core/task_next_step.py",
            "src/sciplot_core/task_capabilities.py",
            "src/sciplot_core/task_scientific_presentation.py",
            "src/sciplot_core/plan_preview.py",
            "src/sciplot_core/plan_source_options.py",
            "src/sciplot_core/source_coverage/replicate_disclosure.py",
            "src/sciplot_core/veusz_worker/spec_audit/series.py",
        }
    ),
    owned_test_paths=frozenset(CATEGORICAL_TESTS),
    pytest_targets=(
        *CATEGORICAL_TESTS,
        "tests/test_source_numeric_encodings.py::test_component_numeric_encoding_preserves_its_original_v1_pipeline",
        *REPLICATE_TESTS,
        "tests/test_replicate_distribution_contract.py",
        "tests/test_column_choice.py",
        "tests/test_rendering_contract.py",
        *ARCHITECTURE_CORE_TARGETS,
        "tests/test_grouped_bar_mark_contract.py",
    ),
    mypy_required=True,
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)

CATEGORICAL_PRESENTATION_EDIT_OWNER = ChangedOwner(
    owner_id="categorical_presentation_edit",
    exact_paths=frozenset(
        {
            "src/sciplot_core/source_coverage/document_audit.py",
            "src/sciplot_core/studio_core/annotation_batch.py",
            "src/sciplot_core/studio_core/annotation_operations.py",
            "src/sciplot_core/studio_core/annotation_schema.py",
            "src/sciplot_core/studio_core/categorical_display.py",
            "src/sciplot_core/studio_core/categorical_display_errors.py",
            "src/sciplot_core/studio_core/categorical_display_preflight.py",
            "src/sciplot_core/studio_core/categorical_display_schema.py",
            "src/sciplot_core/studio_core/document_edit_state.py",
            "src/sciplot_core/studio_core/project_export.py",
            "src/sciplot_core/task_edit_context.py",
            "src/sciplot_core/veusz_worker/__main__.py",
            "src/sciplot_core/veusz_worker/annotations.py",
            "src/sciplot_core/veusz_worker/categorical_display.py",
            "src/sciplot_core/veusz_worker/categorical_rejection.py",
            "src/sciplot_core/veusz_worker/persistent.py",
            "src/sciplot_core/veusz_worker/spec_audit/categorical_axis.py",
            "src/sciplot_core/veusz_worker/spec_audit/coordinator.py",
            "tests/categorical_display_native_helpers.py",
        }
    ),
    owned_test_paths=frozenset(CATEGORICAL_EDIT_TESTS),
    pytest_targets=(
        *CATEGORICAL_EDIT_TESTS,
        *CATEGORICAL_TESTS,
        "tests/test_annotation_operations.py",
        "tests/test_annotation_operations_native.py",
        "tests/test_annotation_validation.py",
        "tests/test_task_edit_context.py",
        "tests/test_project_export_use_case.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)

ORDINARY_PLOTTING_OWNERS = (
    ORDINARY_CURVE_OWNER,
    REPLICATE_DISCLOSURE_OWNER,
    PERFORMANCE_SELECTION_OWNER,
    CATEGORICAL_SOURCE_OWNER,
    CATEGORICAL_PRESENTATION_EDIT_OWNER,
)
