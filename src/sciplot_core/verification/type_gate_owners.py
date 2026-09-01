"""Changed owners and shared targets for the scoped strict type gate."""

from __future__ import annotations

import tomllib
from pathlib import Path

from sciplot_core.verification.owner_model import ChangedOwner


ARCHITECTURE_CORE_TARGETS = (
    "tests/test_architecture_boundaries.py::test_ordinary_source_files_stay_within_the_size_boundary",
    "tests/test_architecture_boundaries.py::test_first_party_import_graph_is_acyclic",
)

CHANGED_VERIFICATION_OWNER = ChangedOwner(
    owner_id="changed_verification",
    path_prefixes=("src/sciplot_core/verification/",),
    exact_paths=frozenset(
        {
            "src/sciplot_core/cli/parsers/diagnostics.py",
            "src/sciplot_core/cli/parsers/builder.py",
            "src/sciplot_core/cli/dispatch/diagnostics.py",
            "src/sciplot_core/doctor/payload.py",
        }
    ),
    owned_test_paths=frozenset(
        {
            "tests/test_changed_verification.py",
            "tests/test_architecture_boundaries.py",
            "tests/test_cli_surface.py",
            "tests/test_doctor_contract_topology.py",
        }
    ),
    pytest_targets=(
        "tests/test_changed_verification.py",
        "tests/test_cli_surface.py",
        "tests/test_doctor_contract_topology.py",
        "tests/test_architecture_boundaries.py::test_non_probe_source_has_no_exact_duplicate_function_implementations",
        "tests/test_architecture_boundaries.py::test_scoped_type_gate_has_one_strict_owned_scope_and_ci_entrypoint",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    handoff_gates=("doctor",),
    release_gates=("full_pytest",),
)

VERIFICATION_POLICY_OWNER = ChangedOwner(
    owner_id="verification_policy",
    exact_paths=frozenset(
        {
            "pyproject.toml",
            "skill/SKILL.md",
            "tests/conftest.py",
        }
    ),
    pytest_targets=(
        "tests/test_documentation_contract.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    handoff_gates=("doctor",),
    release_gates=("full_pytest",),
)

TYPED_CORE_CONTRACT_OWNER = ChangedOwner(
    owner_id="typed_core_contracts",
    path_prefixes=(
        "src/sciplot_core/figure_plan/",
        "src/sciplot_core/foundation/",
    ),
    exact_paths=frozenset(
        {
            "src/sciplot_core/autoplot/evidence.py",
            "src/sciplot_core/autoplot/publish_integrity.py",
            "src/sciplot_core/autoplot/summary.py",
            "src/sciplot_core/delivery/package_builder.py",
            "src/sciplot_core/delivery/package_validation.py",
            "src/sciplot_core/delivery/plan_binding.py",
            "src/sciplot_core/json_contract.py",
            "src/sciplot_core/publish_state.py",
            "src/sciplot_core/study_model/experiment_plans.py",
            "src/sciplot_core/study_model/run_artifacts.py",
            "src/sciplot_core/study_model/package_contract.py",
        }
    ),
    owned_test_paths=frozenset(
        {
            "tests/test_autoplot_evidence.py",
            "tests/test_foundation_text_values.py",
            "tests/test_output_package_contract.py",
            "tests/test_publish_state.py",
            "tests/test_dsc_adapter_dispatch.py",
            "tests/test_resolved_figure_plan.py",
            "tests/test_resolved_mechanical_figure_plan.py",
            "tests/test_resolved_performance_figure_plan.py",
            "tests/test_resolved_temperature_figure_plan.py",
            "tests/test_study_model_artifact_binding.py",
        }
    ),
    pytest_targets=(
        "tests/test_autoplot_evidence.py",
        "tests/test_foundation_text_values.py",
        "tests/test_output_package_contract.py",
        "tests/test_publish_state.py",
        "tests/test_dsc_adapter_dispatch.py",
        "tests/test_resolved_figure_plan.py",
        "tests/test_resolved_mechanical_figure_plan.py",
        "tests/test_resolved_performance_figure_plan.py",
        "tests/test_resolved_temperature_figure_plan.py",
        "tests/test_study_model_artifact_binding.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    release_gates=("full_pytest",),
)

STUDIO_PROJECT_REGISTRY_TYPE_PATHS = frozenset(
    {
        "src/sciplot_core/studio_core/prepare_existing.py",
        "src/sciplot_core/studio_core/registry_state.py",
        "src/sciplot_core/studio_core/registry_writes.py",
        "src/sciplot_core/studio_core/studio_prepare.py",
    }
)
STUDIO_PROJECT_REGISTRY_TYPE_OWNER = ChangedOwner(
    owner_id="studio_project_registry_type",
    exact_paths=STUDIO_PROJECT_REGISTRY_TYPE_PATHS,
    owned_test_paths=frozenset(
        {
            "tests/test_figure_plan_entrypoint_state.py",
            "tests/test_studio_presentation_identity.py",
            "tests/test_studio_single_prepare.py",
        }
    ),
    pytest_targets=(
        "tests/test_figure_plan_entrypoint_state.py",
        "tests/test_intake_atomic_packaging.py",
        "tests/test_studio_presentation_identity.py",
        "tests/test_studio_rule_contract_prepare.py",
        "tests/test_studio_single_prepare.py",
        "tests/test_studio_snapshot_binding.py",
    ),
    mypy_required=True,
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)

WORKFLOW_EXPORT_FORMAT_TYPE_PATHS = frozenset(
    {
        "src/sciplot_core/workflow/auto_split.py",
        "src/sciplot_core/workflow/dma_temperature_bundle.py",
        "src/sciplot_core/workflow/impact_bundle.py",
        "src/sciplot_core/workflow/mechanical_bundle.py",
        "src/sciplot_core/workflow/performance_bundle.py",
        "src/sciplot_core/workflow/rheology_bundle.py",
        "src/sciplot_core/workflow/single_task_bundle.py",
    }
)
WORKFLOW_EXPORT_FORMAT_TYPE_OWNER = ChangedOwner(
    owner_id="workflow_export_format_type",
    exact_paths=WORKFLOW_EXPORT_FORMAT_TYPE_PATHS,
    owned_test_paths=frozenset(
        {
            "tests/test_mechanical_workflow_bundle.py",
            "tests/test_performance_figure_plan_activation.py",
            "tests/test_temperature_workflow_repair.py",
        }
    ),
    pytest_targets=(
        "tests/test_workflow_bundle_dispatch.py",
        "tests/test_generic_single_task_plan.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_impact_condition_figure_set.py",
        "tests/test_mechanical_workflow_bundle.py",
        "tests/test_temperature_workflow_repair.py",
        "tests/test_temperature_terminal_source_binding.py",
    ),
    mypy_required=True,
    handoff_gates=("doctor",),
    final_milestone_gates=("smoke",),
    release_gates=("full_pytest",),
)

STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS = frozenset(
    {
        "src/sciplot_core/studio_figure_set_contract.py",
        "src/sciplot_core/studio_core/figure_task_evidence.py",
        "src/sciplot_core/studio_core/figure_registry_entry.py",
        "src/sciplot_core/studio_core/figure_set_registry.py",
        "src/sciplot_core/studio_core/figure_set_snapshot.py",
        "src/sciplot_core/studio_core/figure_set_state.py",
        "src/sciplot_core/studio_core/figure_set_storage.py",
        "src/sciplot_core/studio_core/figure_set_primary_stage.py",
        "src/sciplot_core/studio_core/figure_set_prepare.py",
        "src/sciplot_core/studio_core/prepare_generated_transaction.py",
    }
)
STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER = ChangedOwner(
    owner_id="studio_figure_set_lifecycle_type",
    exact_paths=STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS,
    owned_test_paths=frozenset(
        {
            "tests/test_mechanical_studio_task_sources.py",
            "tests/test_studio_figure_task_chain.py",
        }
    ),
    pytest_targets=(
        "tests/test_studio_figure_task_chain.py",
        "tests/test_mechanical_studio_task_sources.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_studio_rule_contract_prepare.py",
        "tests/test_studio_single_prepare.py",
        "tests/test_studio_publish_inventory.py",
        "tests/test_veusz_series_revision.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)

STUDIO_FIGURE_SET_PUBLICATION_TYPE_PATHS = frozenset(
    {
        "src/sciplot_core/studio_core/figure_set_publication_scope.py",
        "src/sciplot_core/studio_core/publish_finalize.py",
        "src/sciplot_core/studio_core/publish_inventory.py",
        "src/sciplot_core/studio_core/publish_run.py",
        "src/sciplot_core/studio_core/request_paths.py",
    }
)
STUDIO_FIGURE_SET_PUBLICATION_TYPE_OWNER = ChangedOwner(
    owner_id="studio_figure_set_publication_type",
    exact_paths=STUDIO_FIGURE_SET_PUBLICATION_TYPE_PATHS,
    pytest_targets=(
        "tests/test_studio_publish_inventory.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)

STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS = frozenset(
    {
        "src/sciplot_core/studio_core/figure_registry_geometry.py",
        "src/sciplot_core/studio_core/figure_requests.py",
        "src/sciplot_core/studio_core/figure_source_request.py",
        "src/sciplot_core/studio_core/impact_task_sources.py",
        "src/sciplot_core/studio_core/mechanical_task_source_lifecycle.py",
    }
)
STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER = ChangedOwner(
    owner_id="studio_figure_set_execution_type",
    exact_paths=STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS,
    pytest_targets=(
        "tests/test_resolved_frequency_figure_plan.py",
        "tests/test_impact_condition_figure_set.py",
        "tests/test_mechanical_studio_task_sources.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_studio_figure_task_chain.py",
        *ARCHITECTURE_CORE_TARGETS,
    ),
    mypy_required=True,
    final_milestone_gates=("smoke",),
    release_gates=("acceptance_rules", "full_pytest"),
)


def _configured_additional_mypy_scope() -> tuple[frozenset[str], tuple[str, ...]]:
    repo_root = Path(__file__).resolve().parents[3]
    project_path = repo_root / "pyproject.toml"
    if not project_path.is_file():
        return frozenset(), ()
    project = tomllib.loads(project_path.read_text(encoding="utf-8"))
    configured_value: object = project["tool"]["mypy"]["files"]
    if not isinstance(configured_value, list):
        raise ValueError("[tool.mypy].files must be a list of paths")
    configured: list[str] = []
    for value in configured_value:
        if not isinstance(value, str):
            raise ValueError("[tool.mypy].files must be a list of paths")
        configured.append(value)
    additional_files: set[str] = set()
    additional_prefixes: set[str] = set()
    for value in configured:
        target = repo_root / value
        if not target.exists():
            raise ValueError(f"Configured mypy path does not exist: {value}")
        if target.is_dir():
            prefix = f"{value.rstrip('/')}/"
            probe = f"{prefix}__configured_mypy_file__.py"
            if not any(
                owner.matches(probe)
                for owner in (
                    TYPED_CORE_CONTRACT_OWNER,
                    STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER,
                    STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER,
                    STUDIO_FIGURE_SET_PUBLICATION_TYPE_OWNER,
                    STUDIO_PROJECT_REGISTRY_TYPE_OWNER,
                    WORKFLOW_EXPORT_FORMAT_TYPE_OWNER,
                )
            ):
                additional_prefixes.add(prefix)
            continue
        if not any(
            owner.matches(value)
            for owner in (
                TYPED_CORE_CONTRACT_OWNER,
                STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER,
                STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER,
                STUDIO_FIGURE_SET_PUBLICATION_TYPE_OWNER,
                STUDIO_PROJECT_REGISTRY_TYPE_OWNER,
                WORKFLOW_EXPORT_FORMAT_TYPE_OWNER,
            )
        ):
            additional_files.add(value)
    return frozenset(additional_files), tuple(sorted(additional_prefixes))


(
    SCIENTIFIC_TRANSACTION_TYPE_PATHS,
    SCIENTIFIC_TRANSACTION_TYPE_PREFIXES,
) = _configured_additional_mypy_scope()
SCIENTIFIC_TRANSACTION_TYPE_OWNER = ChangedOwner(
    owner_id="scientific_transaction_type_gate",
    path_prefixes=SCIENTIFIC_TRANSACTION_TYPE_PREFIXES,
    exact_paths=SCIENTIFIC_TRANSACTION_TYPE_PATHS,
    pytest_targets=(),
    mypy_required=True,
)

MYPY_SCOPE_CONFIGURATION_OWNER = ChangedOwner(
    owner_id="mypy_scope_configuration",
    exact_paths=frozenset({"pyproject.toml"}),
    pytest_targets=(),
    mypy_required=True,
)

__all__ = [
    "ARCHITECTURE_CORE_TARGETS",
    "CHANGED_VERIFICATION_OWNER",
    "MYPY_SCOPE_CONFIGURATION_OWNER",
    "SCIENTIFIC_TRANSACTION_TYPE_OWNER",
    "SCIENTIFIC_TRANSACTION_TYPE_PATHS",
    "SCIENTIFIC_TRANSACTION_TYPE_PREFIXES",
    "STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER",
    "STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS",
    "STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER",
    "STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS",
    "STUDIO_FIGURE_SET_PUBLICATION_TYPE_OWNER",
    "STUDIO_FIGURE_SET_PUBLICATION_TYPE_PATHS",
    "STUDIO_PROJECT_REGISTRY_TYPE_OWNER",
    "STUDIO_PROJECT_REGISTRY_TYPE_PATHS",
    "TYPED_CORE_CONTRACT_OWNER",
    "VERIFICATION_POLICY_OWNER",
    "WORKFLOW_EXPORT_FORMAT_TYPE_OWNER",
    "WORKFLOW_EXPORT_FORMAT_TYPE_PATHS",
]
