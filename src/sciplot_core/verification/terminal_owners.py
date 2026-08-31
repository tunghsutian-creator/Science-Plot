"""Changed-owner evidence for terminal preparation and Studio registry seams."""

from __future__ import annotations

from sciplot_core.verification.owner_model import ChangedOwner


GENERIC_TERMINAL_PREPARATION_OWNER = ChangedOwner(
    owner_id="generic_terminal_preparation",
    exact_paths=frozenset(
        {
            "src/sciplot_core/data_mapping/request_rebinding.py",
            "src/sciplot_core/render/panel_render.py",
            "src/sciplot_core/render/public_api.py",
            "src/sciplot_core/render/target_paths.py",
            "src/sciplot_core/studio_core/prepare_generated.py",
            "src/sciplot_core/studio_core/publish_finalize.py",
            "src/sciplot_core/studio_core/publish_inventory.py",
            "src/sciplot_core/studio_core/publish_run.py",
            "src/sciplot_core/studio_core/publish_sources.py",
            "src/sciplot_core/studio_core/prepare_generated_transaction.py",
            "src/sciplot_core/studio_core/prepare_existing.py",
            "src/sciplot_core/studio_core/presentation_evidence.py",
            "src/sciplot_core/studio_core/figure_task_evidence.py",
            "src/sciplot_core/studio_core/registry_state.py",
            "src/sciplot_core/studio_core/series_request.py",
            "src/sciplot_core/studio_core/studio_prepare.py",
            "src/sciplot_core/preparation_source_attestation.py",
            "src/sciplot_core/terminal_source_attestation.py",
            "src/sciplot_core/terminal_source_binding.py",
            "src/sciplot_core/terminal_source_binding_wire.py",
            "src/sciplot_core/veusz_worker/operations.py",
            "src/sciplot_core/workflow/auto_split.py",
            "src/sciplot_core/workflow/request_rendering.py",
            "src/sciplot_core/workflow/single_task_bundle.py",
            "src/sciplot_core/qa/artifacts.py",
        }
    ),
    owned_test_paths=frozenset(
        {
            "tests/test_generic_prepared_terminal_source.py",
            "tests/test_generic_single_task_plan.py",
            "tests/test_preparation_source_attestation.py",
            "tests/test_temperature_terminal_source_binding.py",
            "tests/test_artifact_raster_visibility.py",
            "tests/test_dsc_figure_plan_activation.py",
            "tests/test_impact_condition_figure_set.py",
            "tests/test_performance_workflow_activation.py",
            "tests/test_studio_publish_inventory.py",
            "tests/test_studio_rule_contract_prepare.py",
            "tests/test_studio_snapshot_binding.py",
        }
    ),
    pytest_targets=(
        "tests/test_generic_prepared_terminal_source.py",
        "tests/test_artifact_raster_visibility.py",
        "tests/test_generic_single_task_plan.py",
        "tests/test_dsc_figure_plan_activation.py",
        "tests/test_impact_condition_figure_set.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_performance_workflow_activation.py",
        "tests/test_studio_figure_task_chain.py",
        "tests/test_studio_publish_inventory.py",
        "tests/test_studio_rule_contract_prepare.py",
        "tests/test_studio_snapshot_binding.py",
        "tests/test_preparation_source_attestation.py",
        "tests/test_temperature_terminal_source_binding.py::test_public_request_cannot_claim_prepared_terminal_source",
        "tests/test_temperature_terminal_source_binding.py::test_worker_binding_is_verified_once_at_worker_entry",
        "tests/test_temperature_terminal_source_binding.py::test_panel_seal_owns_single_parent_binding_validation",
        "tests/test_architecture_boundaries.py::test_terminal_source_binding_wire_has_only_two_runtime_importers",
        "tests/test_architecture_boundaries.py::test_veusz_worker_does_not_depend_on_the_studio_compatibility_facade",
        "tests/test_architecture_boundaries.py::test_veusz_worker_uses_named_studio_core_ports",
    ),
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)


__all__ = ["GENERIC_TERMINAL_PREPARATION_OWNER"]
