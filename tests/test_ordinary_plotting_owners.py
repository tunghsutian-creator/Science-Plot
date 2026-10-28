"""Bounded public plotting owners retain scientific and shared gateway coverage."""

from pathlib import Path
import sys
import tomllib

import pytest

from sciplot_core.verification import build_changed_verification_plan
from sciplot_core.verification.ordinary_plotting_owners import (
    APPEND_IDENTITY_LEAF_PATH,
    CATEGORICAL_EDIT_TESTS,
    CATEGORICAL_PRESENTATION_EDIT_OWNER,
    CATEGORICAL_SOURCE_OWNER,
    CURVE_TESTS,
    ORDINARY_CURVE_OWNER,
    ORDINARY_PLOTTING_OWNERS,
    ORDINARY_TASK_LEAF_PATHS,
    PERFORMANCE_SELECTION_OWNER,
    PERFORMANCE_TESTS,
    REPLICATE_DISCLOSURE_OWNER,
    REPLICATE_TESTS,
)
from sciplot_core.verification.owners import CHANGED_OWNERS
from sciplot_core.verification.project_core_owners import (
    PROJECT_CORE_OWNERS, PROJECT_COMMAND_TESTS, PROJECT_STORE_TESTS,
    PROJECT_RUNTIME_TESTS, ATTACHED_PROJECT_TESTS, NATIVE_PROJECT_CONSUMERS,
)
from sciplot_core.verification.type_gate_owners import (
    ARCHITECTURE_CORE_TARGETS,
    SCIENTIFIC_TRANSACTION_TYPE_PATHS,
)


ROOT = Path(__file__).resolve().parents[1]
# Expected additions to the preserved 195-file residual scope. Production still
# derives the complete strict gate solely from pyproject.toml.
ROUND2_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/task_semantic_axes.py",
        "src/sciplot_core/task_semantic_curve_bindings.py",
        "src/sciplot_core/task_missing_values.py",
        "src/sciplot_core/task_replicate_summary.py",
        "src/sciplot_core/semantic_sources/impact_replicate_disclosure.py",
        "src/sciplot_core/source_coverage/replicate_disclosure.py",
        "src/sciplot_core/plan_source_options.py",
        "src/sciplot_core/plot_data/spec_tables.py",
        "src/sciplot_core/plot_data/exports.py",
        "src/sciplot_core/plan_preview_contract.py",
        "src/sciplot_core/performance_comparison/metadata.py",
        "src/sciplot_core/performance_comparison/selection.py",
        "src/sciplot_core/performance_comparison/selection_rows.py",
        "src/sciplot_core/performance_comparison/selected_scatter.py",
        "src/sciplot_core/performance_comparison/source_tables.py",
        "src/sciplot_core/performance_comparison/public_api.py",
        "src/sciplot_core/performance_comparison/scatter.py",
        "src/sciplot_core/performance_comparison/models.py",
        "src/sciplot_core/performance_comparison/layout.py",
        "src/sciplot_core/performance_comparison/source_loading.py",
        "src/sciplot_core/performance_veusz/spec_builder.py",
        "src/sciplot_core/performance_veusz/style.py",
        "src/sciplot_core/performance_veusz/contracts.py",
        "src/sciplot_core/performance_veusz/apply.py",
        "src/sciplot_core/performance_veusz/widget_apply.py",
        "src/sciplot_core/veusz_worker/spec_audit/labels.py",
        "src/sciplot_core/veusz_worker/spec_audit/series.py",
        "src/sciplot_core/categorical_plan.py",
        "src/sciplot_core/categorical_disclosure.py",
        "src/sciplot_core/mapping_contract/categorical.py",
        "src/sciplot_core/studio_render/categorical_bindings.py",
        "src/sciplot_core/studio_render/categorical_bound_series.py",
        "src/sciplot_core/task_categorical_contract.py",
        "src/sciplot_core/task_categorical_creation.py",
        "src/sciplot_core/studio_render/categorical_groups.py",
        "src/sciplot_core/studio_render/categorical_legend.py",
        "src/sciplot_core/studio_core/veusz_spec_labels.py",
        "src/sciplot_core/verification/ordinary_plotting_owners.py",
    }
)
CATEGORICAL_EDIT_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/studio_core/categorical_display.py",
        "src/sciplot_core/studio_core/categorical_display_schema.py",
        "src/sciplot_core/studio_core/categorical_display_errors.py",
        "src/sciplot_core/studio_core/categorical_display_preflight.py",
        "src/sciplot_core/veusz_worker/categorical_display.py",
        "src/sciplot_core/veusz_worker/categorical_rejection.py",
        "src/sciplot_core/source_coverage/document_audit.py",
    }
)
SUMMARY_LEGEND_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/studio_render/component_legend.py",
        "src/sciplot_core/studio_render/segmented_legend_clearance.py",
        "src/sciplot_core/veusz_audit/segmented_legend_geometry.py",
        "src/sciplot_core/studio_core/current_layout_review.py",
    }
)
ZERO_SD_STRICT_ADDITIONS = frozenset(
    {"src/sciplot_core/studio_core/guide_contracts.py"}
)
SOURCE_FACT_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/data_mapping/plan_binding.py",
        "src/sciplot_core/data_mapping/original_tables.py",
        "src/sciplot_core/semantic_sources/instrument_regions.py",
        "src/sciplot_core/semantic_sources/numeric_separators.py",
    }
)
SOURCE_DOMAIN_STRICT_ADDITIONS = frozenset(
    {"src/sciplot_core/task_semantic_stages.py"}
)
SOURCE_IDENTITY_STRICT_ADDITIONS = frozenset(
    {"src/sciplot_core/mapping_contract/source_identity.py",
     "src/sciplot_core/mapping_contract/categorical_identity.py",
     "src/sciplot_core/studio_render/categorical_source_identity.py",
     "src/sciplot_core/veusz_worker/spec_audit/categorical_identity.py",
     "src/sciplot_core/data_mapping/source_projection.py",
     "src/sciplot_core/data_mapping/pair_choice.py",
     "src/sciplot_core/studio_render/paired_source_identity.py",
     "src/sciplot_core/studio_render/series_option_context.py",
     "src/sciplot_core/studio_render/source_group_series.py"}
)
NATIVE_PRESENTATION_STRICT_ADDITIONS = frozenset(
    {"src/sciplot_core/veusz_worker/style_projection.py",
     "src/sciplot_core/source_coverage/spec_units.py",
     "src/sciplot_core/studio_core/style_transfer_storage.py",
     "src/sciplot_core/studio_core/axis_presentation.py",
     "src/sciplot_core/studio_core/series_encoding_contract.py",
     "src/sciplot_core/studio_render/spectral_axis_display.py"}
)
VERIFICATION_CAPTURE_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/verification/evidence_runtime.py",
        "src/sciplot_core/verification/native_exit_boundary.py",
        "src/sciplot_core/verification/private_audit_runtime.py",
        "src/sciplot_core/verification/private_socket_ports.py",
        "src/sciplot_core/verification/private_exclusion_boundary.py",
        "src/sciplot_core/verification/private_native_exit_port.py",
        "src/sciplot_core/verification/process_private_exclusion.py",
        "src/sciplot_core/verification/process_private_launch.py",
    }
)
NATIVE_BATCH_ISOLATION_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_gui/studio_assistant/native_batch.py",
        "src/sciplot_gui/studio_assistant/native_batch_window.py",
    }
)
HOST_EXECUTOR_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/cli/dispatch/host.py",
        "src/sciplot_core/cli/parsers/host.py",
        "src/sciplot_core/host_grants/__init__.py",
        "src/sciplot_core/host_grants/__main__.py",
        "src/sciplot_core/host_grants/administration.py",
        "src/sciplot_core/host_grants/authorization.py",
        "src/sciplot_core/host_grants/context.py",
        "src/sciplot_core/host_grants/models.py",
        "src/sciplot_core/host_grants/registry.py",
    }
)
PROJECT_COMMAND_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/project_commands/__init__.py",
        "src/sciplot_core/project_commands/application.py",
        "src/sciplot_core/project_commands/contracts.py",
        "src/sciplot_core/project_commands/errors.py",
        "src/sciplot_core/project_commands/generated_outputs.py",
        "src/sciplot_core/project_commands/native_suite_projections.py",
        "src/sciplot_core/project_commands/ports.py",
        "src/sciplot_core/project_commands/read_projections.py",
        "src/sciplot_core/project_commands/resources.py",
    }
)
PROJECT_STORAGE_STRICT_ADDITIONS = frozenset(
    {
        'src/sciplot_core/intake/archive_storage.py',
        'src/sciplot_core/intake/packaging.py',
        'src/sciplot_core/project_host_factory.py',
        'src/sciplot_core/project_manifest.py',
        'src/sciplot_core/project_manifest_locations.py',
        'src/sciplot_core/project_store/__init__.py',
        'src/sciplot_core/project_store/adapters.py',
        'src/sciplot_core/project_store/candidate_resources.py',
        'src/sciplot_core/project_store/command_records.py',
        'src/sciplot_core/project_store/commands.py',
        'src/sciplot_core/project_store/committed_outcomes.py',
        'src/sciplot_core/project_store/directories.py',
        'src/sciplot_core/project_store/errors.py',
        'src/sciplot_core/project_store/generated_output_owners.py',
        'src/sciplot_core/project_store/generated_outputs.py',
        'src/sciplot_core/project_store/incoming_sources.py',
        'src/sciplot_core/project_store/io.py',
        'src/sciplot_core/project_store/locators.py',
        'src/sciplot_core/project_store/membership.py',
        'src/sciplot_core/project_store/namespace_io.py',
        'src/sciplot_core/project_store/namespace_transfers.py',
        'src/sciplot_core/project_store/native_artifacts.py',
        'src/sciplot_core/project_store/native_work.py',
        'src/sciplot_core/project_store/paths.py',
        'src/sciplot_core/project_store/physical_projection.py',
        'src/sciplot_core/project_store/portable.py',
        'src/sciplot_core/project_store/preconditions.py',
        'src/sciplot_core/project_store/prepared_inputs.py',
        'src/sciplot_core/project_store/produced_sources.py',
        'src/sciplot_core/project_store/projection.py',
        'src/sciplot_core/project_store/publication.py',
        'src/sciplot_core/project_store/repository.py',
        'src/sciplot_core/project_store/resources.py',
        'src/sciplot_core/project_store/root_bindings.py',
        'src/sciplot_core/project_store/runtime.py',
        'src/sciplot_core/project_store/source_observations.py',
        'src/sciplot_core/project_store/source_tree_io.py',
        'src/sciplot_core/project_store/source_trees.py',
        'src/sciplot_core/project_store/state.py',
        'src/sciplot_core/project_store/worker_binding.py',
        'src/sciplot_core/studio_core/native_save_storage.py',
        'src/sciplot_core/studio_core/native_serialization.py',
        'src/sciplot_core/studio_core/persistence.py',
        'src/sciplot_core/studio_core/veusz_save.py',
        'src/sciplot_core/workflow/project_state.py',
        'src/sciplot_core/workflow/request_publish.py',
        "src/sciplot_core/project_store/source_inspection.py",
        "src/sciplot_core/project_store/input_reads.py",
    }
)
SOURCE_LOCATOR_STRICT_ADDITIONS = frozenset(
    {
        'src/sciplot_core/data_mapping/raw_tables.py',
        'src/sciplot_core/delivery/file_set_validation.py',
        'src/sciplot_core/delivery/runtime_evidence.py',
        'src/sciplot_core/ingest.py',
        'src/sciplot_core/project_store/candidate_runtime.py',
        'src/sciplot_core/project_store/sealed_source_trees.py',
        'src/sciplot_core/project_store/source_resolver.py',
        'src/sciplot_core/semantic_sources/impact_sources.py',
        'src/sciplot_core/semantic_sources/prepare_rheology.py',
        'src/sciplot_core/semantic_sources/rheology_sweep_domain.py',
        'src/sciplot_core/semantic_sources/rheology_sweep_sources.py',
        'src/sciplot_core/semantic_sources/table_candidate_sources.py',
        'src/sciplot_core/semantic_sources/table_source_files.py',
        'src/sciplot_core/source_coverage/artifacts.py',
        'src/sciplot_core/source_coverage/file_snapshots.py',
        'src/sciplot_core/source_coverage/native_file_snapshots.py',
        'src/sciplot_core/source_coverage/inventory_paths.py',
        'src/sciplot_core/source_coverage/verify.py',
        'src/sciplot_core/source_tables/raw_readers.py',
        'src/sciplot_core/studio_core/source_snapshots.py',
        'src/sciplot_core/veusz_worker/cli.py',
        "src/sciplot_core/source_coverage/derivation.py",
        "src/sciplot_core/data_mapping/contracts.py",
        "src/sciplot_core/data_mapping/execution_loading.py",
        "src/sciplot_core/data_mapping/execution_inputs.py",
        "src/sciplot_core/data_mapping/numeric_readset_proof.py",
        "src/sciplot_core/data_mapping/execution_directories.py",
        "src/sciplot_core/data_mapping/request_resolution.py",
        "src/sciplot_core/studio_core/request_overrides.py",
    }
)
NATIVE_PROJECT_COMMAND_STRICT_ADDITIONS = frozenset(
    {
        'src/sciplot_core/studio_core/delivery_recovery_commands.py',
        'src/sciplot_core/studio_core/document_edit_commands.py',
        'src/sciplot_core/studio_core/observed_figure_binding.py',
        'src/sciplot_core/studio_core/document_edit_review.py',
        'src/sciplot_core/task_native_edit.py',
        'src/sciplot_core/studio_core/document_edit_legacy.py',
        'src/sciplot_core/studio_core/export_execution.py',
        'src/sciplot_core/studio_core/export_projection.py',
        'src/sciplot_core/studio_core/export_replay.py',
        'src/sciplot_core/studio_core/external_native_export.py',
        'src/sciplot_core/studio_core/native_export_adapter.py',
        'src/sciplot_core/studio_core/native_export_commands.py',
        'src/sciplot_core/studio_core/native_scientific_audit.py',
        'src/sciplot_core/studio_core/project_command_scope.py',
        'src/sciplot_core/studio_core/project_publication_commands.py',
        'src/sciplot_core/studio_core/project_query_sources.py',
        'src/sciplot_core/studio_core/publication_candidates.py',
        'src/sciplot_core/studio_core/publication_prepare.py',
        'src/sciplot_core/studio_core/qt_window.py',
        'src/sciplot_core/studio_core/series_revision_persistence.py',
        'src/sciplot_core/studio_core/source_update_commands.py',
        'src/sciplot_core/studio_core/source_update_files.py',
        'src/sciplot_core/studio_core/source_update_replay.py',
        'src/sciplot_core/studio_core/source_update_sources.py',
        'src/sciplot_core/studio_core/source_update_state.py',
        'src/sciplot_core/studio_core/source_update_styles.py',
        'src/sciplot_core/studio_core/studio_command.py',
        'src/sciplot_gui/studio_project/export_helpers.py',
    }
)
STUDIO_PREPARATION_STRICT_ADDITIONS = frozenset(
    {
        'src/sciplot_core/studio_core/figure_member_prepare.py',
        'src/sciplot_core/studio_core/preparation_artifacts.py',
        'src/sciplot_core/studio_core/preparation_candidate.py',
        'src/sciplot_core/studio_core/preparation_commands.py',
        'src/sciplot_core/studio_core/preparation_lineage.py',
        'src/sciplot_core/studio_core/preparation_original_sources.py',
        'src/sciplot_core/studio_core/preparation_source_runtime.py',
        'src/sciplot_core/studio_core/studio_prepare_core.py',
    }
)
RHEOLOGY_PROJECT_COMMAND_STRICT_ADDITIONS = frozenset(
    {
        'src/sciplot_core/rheology_tts_creation_bindings.py',
        'src/sciplot_core/rheology_tts_native_invocation.py',
        'src/sciplot_core/workflow/native_suite_admission.py',
        'src/sciplot_core/workflow/native_suite_command_records.py',
        'src/sciplot_core/workflow/native_suite_creation.py',
        'src/sciplot_core/workflow/native_suite_creation_facts.py',
        'src/sciplot_core/workflow/native_suite_creation_inspection.py',
        'src/sciplot_core/workflow/native_suite_creation_projection.py',
        'src/sciplot_core/workflow/native_suite_generation.py',
        'src/sciplot_core/workflow/native_suite_receipts.py',
        'src/sciplot_core/workflow/native_suite_review_exports.py',
        'src/sciplot_core/workflow/native_suite_runtime.py',
        'src/sciplot_core/workflow/native_suite_transactions.py',
        'src/sciplot_core/workflow/native_suite_patch_contract.py',
        'src/sciplot_core/workflow/native_suite_patch_phases.py',
        'src/sciplot_core/workflow/rheology_tts_creation_history.py',
        'src/sciplot_core/workflow/rheology_tts_creation_inputs.py',
        'src/sciplot_core/workflow/rheology_tts_delivery_files.py',
        'src/sciplot_core/workflow/rheology_tts_saved_state.py',
        "src/sciplot_core/workflow/native_suite_legacy_publication.py",
        "src/sciplot_core/workflow/native_suite_preview.py",
        "src/sciplot_core/workflow/native_suite_storage.py",
        "src/sciplot_core/workflow/rheology_tts_publication_recovery.py",
        "src/sciplot_core/workflow/rheology_tts_style_update.py",
        "src/sciplot_core/workflow/rheology_tts_suite.py",
    }
)
WORKFLOW_PROJECT_STRICT_ADDITIONS = frozenset(
    {
        'src/sciplot_core/workflow/errors.py',
        'src/sciplot_core/workflow/one_step_entry.py',
        'src/sciplot_core/workflow/project_failures.py',
        'src/sciplot_core/workflow/project_output.py',
        'src/sciplot_core/workflow/project_requests.py',
        'src/sciplot_core/workflow/project_results.py',
        'src/sciplot_core/workflow/request_io.py',
        'src/sciplot_core/workflow/run_projection.py',
    }
)
SOURCE_ARTIFACT_STRICT_ADDITIONS = frozenset(
    {
        "src/sciplot_core/studio_render/source_artifacts.py",
        "src/sciplot_core/studio_render/categorical_components.py",
        "src/sciplot_core/studio_render/frame_series.py",
        "src/sciplot_core/studio_render/scalar_series.py",
        "src/sciplot_core/studio_core/series_request.py",
        "src/sciplot_core/studio_core/impact_series.py",
        "src/sciplot_core/studio_render/series_options.py",
        "src/sciplot_core/task_paper_publication.py",
        "src/sciplot_core/task_paper_selection.py",
        "src/sciplot_core/workflow/rheology_terminal_validation.py",
    }
)
VERIFICATION_PROJECT_CORE_STRICT_ADDITIONS = frozenset(
    {
        'src/sciplot_core/verification/project_core_owners.py',
        'src/sciplot_core/verification/project_core_paths.py',
        'src/sciplot_core/verification/project_core_targets.py',
    }
)
FINAL_STRICT_ADDITIONS = (
    ROUND2_STRICT_ADDITIONS
    | CATEGORICAL_EDIT_STRICT_ADDITIONS
    | SUMMARY_LEGEND_STRICT_ADDITIONS
    | ZERO_SD_STRICT_ADDITIONS
    | SOURCE_FACT_STRICT_ADDITIONS
    | SOURCE_DOMAIN_STRICT_ADDITIONS
    | SOURCE_IDENTITY_STRICT_ADDITIONS
    | NATIVE_PRESENTATION_STRICT_ADDITIONS
    | VERIFICATION_CAPTURE_STRICT_ADDITIONS
    | NATIVE_BATCH_ISOLATION_STRICT_ADDITIONS
    | HOST_EXECUTOR_STRICT_ADDITIONS
    | PROJECT_COMMAND_STRICT_ADDITIONS
    | PROJECT_STORAGE_STRICT_ADDITIONS
    | SOURCE_LOCATOR_STRICT_ADDITIONS
    | NATIVE_PROJECT_COMMAND_STRICT_ADDITIONS
    | WORKFLOW_PROJECT_STRICT_ADDITIONS
    | RHEOLOGY_PROJECT_COMMAND_STRICT_ADDITIONS
    | STUDIO_PREPARATION_STRICT_ADDITIONS
    | SOURCE_ARTIFACT_STRICT_ADDITIONS
    | VERIFICATION_PROJECT_CORE_STRICT_ADDITIONS
)


def _plan(paths):
    return build_changed_verification_plan(paths, repo_root=ROOT)


def _targets(plan):
    return set(
        next(
            check["command"]
            for check in plan["checks"]
            if check["check_id"] == "pytest_changed_owners"
        )[6:]
    )


@pytest.mark.parametrize(
    "owner", ORDINARY_PLOTTING_OWNERS, ids=lambda owner: owner.owner_id
)
def test_each_domain_has_exact_existing_paths_and_generated_native_controls(owner):
    assert not owner.path_prefixes
    assert owner.owned_test_paths
    assert owner.mypy_required
    assert set(ARCHITECTURE_CORE_TARGETS) <= set(owner.pytest_targets)
    assert "smoke" in owner.final_milestone_gates
    assert "full_pytest" in owner.release_gates
    for path in owner.exact_paths | owner.owned_test_paths:
        assert (ROOT / path).is_file(), path
        plan = _plan([path])
        assert not plan["unowned_paths"]
        assert owner.owner_id in {item["owner_id"] for item in plan["owners"]}
        assert set(owner.owned_test_paths) <= _targets(plan)
    for target in owner.pytest_targets:
        assert (ROOT / target.split("::", 1)[0]).is_file(), target


@pytest.mark.parametrize("path", sorted(ORDINARY_TASK_LEAF_PATHS))
def test_new_task_leaves_keep_public_native_controls_without_unrelated_task_gate(path):
    plan = _plan([path])
    owners = {item["owner_id"] for item in plan["owners"]}
    assert "local_task_control" not in owners
    assert not plan["unowned_paths"]
    assert "tests/test_task_saved_work.py" not in _targets(plan)
    assert "tests/test_task_groups.py" not in _targets(plan)
    assert any("native" in target for target in _targets(plan))
    assert "full_pytest" in plan["required_later"]["release"]


def test_new_append_identity_leaf_retains_append_and_curve_native_consumers():
    plan = _plan([APPEND_IDENTITY_LEAF_PATH])
    owners = {item["owner_id"] for item in plan["owners"]}
    assert ORDINARY_CURVE_OWNER.owner_id in owners
    assert "semantic_plot_engine" not in owners
    assert set(CURVE_TESTS) | {
        "tests/test_managed_source_append.py",
        "tests/test_managed_source_append_native.py",
    } <= _targets(plan)
    assert "tests/test_plot_recovery.py" not in _targets(plan)


@pytest.mark.parametrize(
    "path,original_owner,original_targets",
    [
        (
            "src/sciplot_core/task_control.py",
            "local_task_control",
            {"tests/test_task_saved_work.py", "tests/test_task_source_control.py"},
        ),
        (
            "src/sciplot_core/task_contract.py",
            "local_task_control",
            {"tests/test_task_groups.py", "tests/test_task_papers.py"},
        ),
        (
            "src/sciplot_core/cli/dispatch/tasks.py",
            "local_task_control",
            {"tests/test_task_column_mapping_native.py", "tests/test_task_recovery.py"},
        ),
        (
            "src/sciplot_core/plot_engine/managed_source_append.py",
            "semantic_plot_engine",
            {
                "tests/test_managed_source_append_native.py",
                "tests/test_plot_recovery.py",
            },
        ),
        (
            "src/sciplot_core/source_coverage/managed_documents.py",
            "managed_document_science",
            {
                "tests/test_managed_document_science.py",
                "tests/test_native_numeric_precision.py",
            },
        ),
        (
            "src/sciplot_core/veusz_worker/spec_audit/series.py",
            "managed_document_science",
            {
                "tests/test_managed_document_science.py",
                "tests/test_document_audit_transport.py",
            },
        ),
        (
            "src/sciplot_core/cli/parsers/diagnostics.py",
            "changed_verification",
            {"tests/test_changed_verification.py", "tests/test_cli_surface.py"},
        ),
        (
            "src/sciplot_core/studio_core/annotation_operations.py",
            "native_annotations",
            {"tests/test_annotation_operations.py", "tests/test_annotation_validation.py"},
        ),
        (
            "src/sciplot_core/studio_core/document_edit_state.py",
            "native_document_edit",
            {"tests/test_document_edit.py", "tests/test_document_edit_native.py"},
        ),
        (
            "src/sciplot_core/veusz_worker/__main__.py",
            "generic_terminal_preparation",
            {"tests/test_render_worker_rejection.py", "tests/test_generic_single_task_plan.py"},
        ),
        (
            "src/sciplot_core/veusz_worker/persistent.py",
            "semantic_plot_engine",
            {"tests/test_plot_recovery.py", "tests/test_managed_backend_native.py"},
        ),
        (
            "src/sciplot_core/studio_core/current_layout_review.py",
            "current_native_legend_layout",
            {"tests/test_current_layout_review.py", "tests/test_current_layout_review_native.py"},
        ),
        (
            "src/sciplot_core/studio_core/guide_contracts.py",
            "managed_document_science",
            {"tests/test_managed_document_science.py", "tests/test_native_numeric_precision.py"},
        ),
    ],
)
def test_critical_gateways_retain_original_broad_owners_and_targets(
    path,
    original_owner,
    original_targets,
):
    plan = _plan([path])
    assert original_owner in {item["owner_id"] for item in plan["owners"]}
    assert original_targets <= _targets(plan)
    assert "full_pytest" in plan["required_later"]["release"]


def test_shared_plan_option_selects_all_source_contract_consumers_once():
    plan = _plan(["src/sciplot_core/plan_source_options.py"])
    assert {
        REPLICATE_DISCLOSURE_OWNER.owner_id,
        PERFORMANCE_SELECTION_OWNER.owner_id,
        CATEGORICAL_SOURCE_OWNER.owner_id,
    } <= {item["owner_id"] for item in plan["owners"]}
    expected = set(REPLICATE_TESTS) | set(PERFORMANCE_TESTS)
    expected |= set(CATEGORICAL_SOURCE_OWNER.owned_test_paths)
    assert expected <= _targets(plan)
    checks = [check["command"] for check in plan["checks"]]
    assert checks.count([sys.executable, "-m", "mypy"]) == 1
    assert (
        len(
            [
                check
                for check in plan["checks"]
                if check["check_id"] == "pytest_changed_owners"
            ]
        )
        == 1
    )


def test_future_task_file_keeps_broad_owner_and_unknown_metric_leaf_fails_closed():
    task = _plan(["src/sciplot_core/task_future_ordinary_probe.py"])
    assert "local_task_control" in {item["owner_id"] for item in task["owners"]}
    assert "tests/test_task_recovery.py" in _targets(task)
    unknown = "src/sciplot_core/performance_comparison/future_metric_probe.py"
    blocked = _plan([unknown])
    assert blocked["status"] == "failed"
    assert blocked["unowned_paths"] == [unknown]
    assert blocked["checks"] == []


@pytest.mark.parametrize(
    "path",
    [
        "skill/references/performance-selection.md",
        "skill/references/ordinary-categorical.md",
        "skill/references/categorical-presentation-edit.md",
    ],
)
def test_public_workflow_references_have_an_exact_documentation_owner(path):
    plan = _plan([path])
    assert "documentation_contract" in {item["owner_id"] for item in plan["owners"]}
    assert "tests/test_documentation_contract.py" in _targets(plan)


def test_reviewed_strict_additions_extend_the_preserved_residual_scope_once():
    configured = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["mypy"][
        "files"
    ]
    additions = (
        ROUND2_STRICT_ADDITIONS,
        CATEGORICAL_EDIT_STRICT_ADDITIONS,
        SUMMARY_LEGEND_STRICT_ADDITIONS,
        ZERO_SD_STRICT_ADDITIONS,
        SOURCE_FACT_STRICT_ADDITIONS,
        SOURCE_DOMAIN_STRICT_ADDITIONS,
        SOURCE_IDENTITY_STRICT_ADDITIONS,
        NATIVE_PRESENTATION_STRICT_ADDITIONS,
        VERIFICATION_CAPTURE_STRICT_ADDITIONS,
        NATIVE_BATCH_ISOLATION_STRICT_ADDITIONS,
        HOST_EXECUTOR_STRICT_ADDITIONS,
        PROJECT_COMMAND_STRICT_ADDITIONS,
        PROJECT_STORAGE_STRICT_ADDITIONS,
        SOURCE_LOCATOR_STRICT_ADDITIONS,
        NATIVE_PROJECT_COMMAND_STRICT_ADDITIONS,
        WORKFLOW_PROJECT_STRICT_ADDITIONS,
        RHEOLOGY_PROJECT_COMMAND_STRICT_ADDITIONS,
        STUDIO_PREPARATION_STRICT_ADDITIONS,
        SOURCE_ARTIFACT_STRICT_ADDITIONS,
        VERIFICATION_PROJECT_CORE_STRICT_ADDITIONS,
    )
    assert all(
        scope.isdisjoint(other)
        for index, scope in enumerate(additions)
        for other in additions[index + 1 :]
    )
    assert len(configured) == len(set(configured))
    assert ROUND2_STRICT_ADDITIONS <= SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert FINAL_STRICT_ADDITIONS <= SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert all(configured.count(path) == 1 for path in FINAL_STRICT_ADDITIONS)
    assert len(SCIENTIFIC_TRANSACTION_TYPE_PATHS - FINAL_STRICT_ADDITIONS) == 195
    for path in FINAL_STRICT_ADDITIONS:
        assert (ROOT / path).is_file()
        owners = [owner for owner in CHANGED_OWNERS if owner.matches(path)]
        assert any(owner.mypy_required for owner in owners)


def test_categorical_native_helper_selects_real_tests_without_an_empty_pytest_target():
    helper = "tests/categorical_display_native_helpers.py"
    plan = _plan([helper])
    assert CATEGORICAL_PRESENTATION_EDIT_OWNER.owner_id in {
        item["owner_id"] for item in plan["owners"]
    }
    assert set(CATEGORICAL_EDIT_TESTS) <= _targets(plan)
    assert helper not in _targets(plan)


@pytest.mark.parametrize(
    "path",
    [
        "src/sciplot_core/studio_core/categorical_display_future_probe.py",
        "src/sciplot_core/veusz_worker/categorical_future_probe.py",
        "src/sciplot_core/studio_render/segmented_future_probe.py",
        "tests/categorical_display_future_helpers.py",
        "skill/references/categorical-future-probe.md",
    ],
)
def test_future_categorical_neighbors_remain_unowned_and_fail_closed(path):
    blocked = _plan([path])
    assert blocked["status"] == "failed"
    assert blocked["unowned_paths"] == [path]
    assert blocked["checks"] == []


def test_project_core_domains_retain_all_owned_inputs_and_real_native_consumers():
    for owner in PROJECT_CORE_OWNERS:
        assert owner.mypy_required and "full_pytest" in owner.release_gates
        assert owner.owned_test_paths <= set(owner.pytest_targets)
        for target in owner.pytest_targets:
            assert (ROOT / target.split("::", 1)[0]).is_file(), target
        for path in owner.exact_paths | owner.owned_test_paths:
            assert (ROOT / path).is_file(), path
            plan = _plan([path])
            assert not plan["unowned_paths"]
            assert owner.owner_id in {row["owner_id"] for row in plan["owners"]}
            selected = _targets(plan)
            # The existing selector owner folds exact nodes into a selected full
            # module. That preserves their bodies without duplicate execution.
            assert all(target in selected or target.split("::", 1)[0] in selected
                       for target in owner.pytest_targets)
    shared = _plan(["src/sciplot_core/project_commands/contracts.py"])
    assert set(PROJECT_COMMAND_TESTS + PROJECT_STORE_TESTS + PROJECT_RUNTIME_TESTS
               + ATTACHED_PROJECT_TESTS + NATIVE_PROJECT_CONSUMERS) <= _targets(shared)


def test_project_core_unknown_neighbor_does_not_inherit_an_empty_type_only_plan():
    unknown = "src/sciplot_core/unregistered_project_authority.py"
    blocked = _plan([unknown])
    assert blocked["status"] == "failed" and blocked["unowned_paths"] == [unknown]
    assert blocked["checks"] == []
