"""Focused owners for scientific metrics, current documents, and delivery."""

from __future__ import annotations

from sciplot_core.verification.owner_model import ChangedOwner


PROJECT_INTEGRITY_OWNERS = (
    ChangedOwner(
        owner_id="native_assistant_dock",
        exact_paths=frozenset({"src/sciplot_gui/studio_assistant/dock.py"}),
        pytest_targets=("tests/test_assistant_contract.py",),
        handoff_gates=("doctor",),
        final_milestone_gates=("smoke",),
    ),
    ChangedOwner(
        owner_id="material_metric_integrity",
        exact_paths=frozenset(
            {
                "src/sciplot_core/materials_rules/metric_tables.py",
                "src/sciplot_core/materials_rules/curve_extrema_metrics.py",
                "src/sciplot_core/materials_rules/mechanical_metrics.py",
                "src/sciplot_core/materials_rules/mechanical_rules.py",
                "src/sciplot_core/semantic_sources/mechanical_fact_derivation.py",
                "src/sciplot_core/semantic_sources/mechanical_materialization.py",
            }
        ),
        owned_test_paths=frozenset(
            {
                "tests/test_mechanical_source_facts.py",
                "tests/test_mechanical_figure_plan_activation.py",
            }
        ),
        pytest_targets=(
            "tests/test_mechanical_source_facts.py",
            "tests/test_mechanical_figure_plan_activation.py",
            "tests/test_tensile_workbook_directory.py",
            "tests/test_tga_scientific_transform.py",
            "tests/test_resolved_mechanical_figure_plan.py",
        ),
        final_milestone_gates=("smoke",),
        release_gates=("acceptance_rules", "full_pytest"),
    ),
    ChangedOwner(
        owner_id="delivery_project_integrity",
        path_prefixes=(
            "src/sciplot_core/delivery/",
            "src/sciplot_core/launchers/",
        ),
        exact_paths=frozenset(
            {
                "src/sciplot_core/studio_core/delivery_target.py",
                "src/sciplot_core/studio_core/project_export.py",
                "src/sciplot_core/studio_core/studio_command.py",
                "src/sciplot_core/cli/dispatch/interfaces.py",
                "src/sciplot_core/plot_data/exports.py",
                "src/sciplot_core/plot_data/spec_tables.py",
                "src/sciplot_gui/studio_project/export_helpers.py",
            }
        ),
        owned_test_paths=frozenset(
            {
                "tests/test_delivery_project_documents.py",
                "tests/test_delivery_project_continuation.py",
                "tests/test_delivery_studio_lifecycle.py",
                "tests/test_project_export_use_case.py",
            }
        ),
        pytest_targets=(
            "tests/test_delivery_project_documents.py",
            "tests/test_delivery_project_continuation.py",
            "tests/test_delivery_studio_lifecycle.py",
            "tests/test_project_export_use_case.py",
            "tests/test_mechanical_figure_plan_activation.py",
            "tests/test_managed_document_science.py",
        ),
        handoff_gates=("doctor",),
        final_milestone_gates=("smoke",),
        release_gates=("acceptance_rules", "full_pytest"),
    ),
    ChangedOwner(
        owner_id="managed_document_science",
        path_prefixes=(
            "src/sciplot_core/source_coverage/",
            "src/sciplot_core/veusz_worker/spec_audit/",
        ),
        exact_paths=frozenset(
            {
                "src/sciplot_core/veusz_worker/cli.py",
                "src/sciplot_core/studio_core/publish_manifest.py",
                "src/sciplot_core/studio_core/guide_contracts.py",
            }
        ),
        owned_test_paths=frozenset({"tests/test_managed_document_science.py"}),
        pytest_targets=("tests/test_managed_document_science.py",),
        handoff_gates=("doctor",),
        final_milestone_gates=("smoke",),
        release_gates=("acceptance_rules", "full_pytest"),
    ),
)


__all__ = ["PROJECT_INTEGRITY_OWNERS"]
