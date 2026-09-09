from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Sequence

import pytest

from sciplot_core.verification import (
    build_changed_verification_plan,
    collect_changed_paths,
    run_changed_verification,
)
from sciplot_core.verification.type_gate_owners import (
    ARCHITECTURE_CORE_TARGETS,
    SCIENTIFIC_TRANSACTION_TYPE_OWNER,
    SCIENTIFIC_TRANSACTION_TYPE_PATHS,
    STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER,
    STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS,
    STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER,
    STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS,
    STUDIO_FIGURE_SET_PUBLICATION_TYPE_OWNER,
    STUDIO_FIGURE_SET_PUBLICATION_TYPE_PATHS,
    STUDIO_PROJECT_REGISTRY_TYPE_OWNER,
    STUDIO_PROJECT_REGISTRY_TYPE_PATHS,
    TYPED_CORE_CONTRACT_OWNER,
    WORKFLOW_EXPORT_FORMAT_TYPE_OWNER,
    WORKFLOW_EXPORT_FORMAT_TYPE_PATHS,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_rheology_workbook_materialization_selects_shared_source_stability() -> None:
    for path in (
        "src/sciplot_core/semantic_sources/rheology_workbooks.py",
        "tests/test_rheology_workbook_stability.py",
    ):
        plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
        assert plan["unowned_paths"] == []
        check = next(
            item for item in plan["checks"]
            if item["check_id"] == "pytest_changed_owners"
        )
        assert "tests/test_rheology_workbook_stability.py" in check["command"]
        assert "acceptance_rules" in plan["required_later"]["release"]


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (
            "src/sciplot_core/delivery/package_transaction.py",
            "tests/test_delivery_project_documents.py",
        ),
        (
            "src/sciplot_core/launchers/delivery_binding.py",
            "tests/test_delivery_project_continuation.py",
        ),
        (
            "src/sciplot_core/studio_core/delivery_target.py",
            "tests/test_delivery_project_continuation.py",
        ),
        (
            "src/sciplot_core/studio_core/project_export.py",
            "tests/test_project_export_use_case.py",
        ),
        (
            "src/sciplot_core/semantic_sources/table_selection.py",
            "tests/test_intake_review_recovery.py",
        ),
        (
            "src/sciplot_core/source_coverage/managed_documents.py",
            "tests/test_managed_document_science.py",
        ),
        (
            "src/sciplot_core/source_coverage/managed_task_sources.py",
            "tests/test_managed_document_science.py",
        ),
        (
            "src/sciplot_core/veusz_worker/spec_audit/scientific_geometry.py",
            "tests/test_managed_document_science.py",
        ),
        (
            "src/sciplot_core/veusz_worker/spec_audit/bar_error.py",
            "tests/test_managed_document_science.py",
        ),
        (
            "src/sciplot_core/studio_render/terminal_contract.py",
            "tests/test_impact_terminal_data_contract.py",
        ),
    ],
)
def test_integrity_modules_select_behavior_regressions_and_strict_type_gate(
    source: str,
    target: str,
) -> None:
    plan = build_changed_verification_plan([source], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    checks = {check["check_id"]: check["command"] for check in plan["checks"]}
    assert target in checks["pytest_changed_owners"]
    assert checks["mypy_owned_scope"] == [sys.executable, "-m", "mypy"]
    assert checks["pytest_changed_owners"].count("focused") == 1


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_delivery_project_documents.py",
        "tests/test_delivery_project_continuation.py",
        "tests/test_delivery_studio_lifecycle.py",
        "tests/test_project_export_use_case.py",
        "tests/test_intake_review_recovery.py",
        "tests/test_managed_document_science.py",
        "tests/test_mechanical_source_facts.py",
        "tests/test_impact_terminal_data_contract.py",
        "tests/test_mechanical_figure_plan_activation.py",
        "tests/test_human_daily_use_validation.py",
    ],
)
def test_integrity_regression_files_have_owners_and_are_selected(path: str) -> None:
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    checks = {check["check_id"]: check["command"] for check in plan["checks"]}
    assert path in checks["pytest_changed_owners"]


@pytest.mark.parametrize(
    "path",
    [
        "src/sciplot_core/plot_data/exports.py",
        "src/sciplot_core/plot_data/spec_tables.py",
    ],
)
def test_plot_data_exports_select_complete_figure_plan_delivery_regression(
    path: str,
) -> None:
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    checks = {check["check_id"]: check["command"] for check in plan["checks"]}
    assert (
        "tests/test_mechanical_figure_plan_activation.py"
        in checks["pytest_changed_owners"]
    )
    assert "tests/test_managed_document_science.py" in checks["pytest_changed_owners"]


def _completed(
    command: Sequence[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        list(command),
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_changed_snapshot_merges_tracked_and_untracked_once() -> None:
    calls: list[list[str]] = []

    def runner(
        command: Sequence[str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == REPO_ROOT
        calls.append(list(command))
        if list(command[:2]) == ["git", "diff"]:
            return _completed(
                command,
                stdout=(
                    "README.md\0"
                    "src/sciplot_core/intake/session.py\0"
                    "docs/验证.md\0"
                    "docs/line\nbreak.md\0"
                ),
            )
        return _completed(
            command,
            stdout=(
                "tests/test_changed_verification.py\0"
                "README.md\0"
                "docs/ leading and trailing.md \0"
            ),
        )

    assert collect_changed_paths(REPO_ROOT, command_runner=runner) == [
        "README.md",
        "docs/ leading and trailing.md ",
        "docs/line\nbreak.md",
        "docs/验证.md",
        "src/sciplot_core/intake/session.py",
        "tests/test_changed_verification.py",
    ]
    assert calls == [
        ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]


def test_changed_owners_build_one_deduplicated_focused_pass() -> None:
    payload = build_changed_verification_plan(
        [
            "README.md",
            "src/sciplot_core/verification/changed.py",
            "src/sciplot_core/verification/owners.py",
            "src/sciplot_core/intake/session.py",
            "tests/test_changed_verification.py",
        ],
        repo_root=REPO_ROOT,
    )

    assert payload["status"] == "planned"
    assert payload["unowned_paths"] == []
    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "documentation_contract",
        "changed_verification",
        "intake_project",
    ]
    checks = {check["check_id"]: check for check in payload["checks"]}
    pytest_command = checks["pytest_changed_owners"]["command"]
    assert pytest_command[:6] == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "focused",
    ]
    assert pytest_command.count("tests/test_changed_verification.py") == 1
    assert set(checks) == {
        "ruff_changed_python",
        "pytest_changed_owners",
        "diff_whitespace",
    }
    assert payload["required_later"] == {
        "handoff": ["doctor"],
        "final_milestone": ["smoke"],
        "release": ["full_pytest"],
    }
    generated = " ".join(
        part for check in payload["checks"] for part in check["command"]
    )
    assert "smoke" not in generated
    assert "acceptance" not in generated
    assert "comprehensive" not in generated


def test_automation_baseline_has_one_focused_evidence_owner() -> None:
    payload = build_changed_verification_plan(
        [
            "src/sciplot_core/automation_baseline.py",
            "src/sciplot_core/automation_baseline_identity_validation.py",
            "src/sciplot_core/automation_baseline_probe.py",
            "src/sciplot_core/automation_baseline_schema.py",
            "src/sciplot_core/automation_baseline_validation.py",
            "src/sciplot_core/automation_baseline_validation_utils.py",
            "tests/test_automation_baseline.py",
        ],
        repo_root=REPO_ROOT,
    )

    assert payload["owners"] == [
        {
            "owner_id": "automation_baseline_evidence",
            "changed_paths": [
                "src/sciplot_core/automation_baseline.py",
                "src/sciplot_core/automation_baseline_identity_validation.py",
                "src/sciplot_core/automation_baseline_probe.py",
                "src/sciplot_core/automation_baseline_schema.py",
                "src/sciplot_core/automation_baseline_validation.py",
                "src/sciplot_core/automation_baseline_validation_utils.py",
                "tests/test_automation_baseline.py",
            ],
            "pytest_targets": [
                "tests/test_automation_baseline.py",
                "tests/test_automation_states.py",
                "tests/test_rule_invocation_contract.py::test_rules_plan_and_autoplot_share_one_stale_rule_decision",
                "tests/test_plan_preview.py::test_plan_preview_blocks_uncertified_rule_before_source_inspection",
                "tests/test_autoplot_run.py::test_run_autoplot_returns_v2_rule_repair_without_project_or_write",
                "tests/test_publish_state.py::test_publish_state_preserves_a_scientific_confirmation_blocker",
                "tests/test_frontend_topology.py::test_package_has_one_cli_and_no_standalone_frontend_entrypoint",
                *ARCHITECTURE_CORE_TARGETS,
            ],
        }
    ]
    assert payload["unowned_paths"] == []
    assert payload["required_later"] == {
        "handoff": ["doctor"],
        "final_milestone": ["smoke"],
        "release": ["full_pytest"],
    }


def test_cli_parser_builder_is_owned_with_the_diagnostics_surface() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/cli/parsers/builder.py"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "changed_verification", "external_project_control_cli",
    ]
    assert payload["unowned_paths"] == []


def test_skill_wrapper_defers_runtime_gates_without_selecting_comprehensive() -> None:
    payload = build_changed_verification_plan(
        ["skill/scripts/sciplot"],
        repo_root=REPO_ROOT,
    )

    assert payload["status"] == "planned"
    assert payload["owners"] == [
        {
            "owner_id": "skill_wrapper",
            "changed_paths": ["skill/scripts/sciplot"],
            "pytest_targets": ["tests/test_skill_wrapper_contract.py"],
        }
    ]
    pytest_check = next(
        check
        for check in payload["checks"]
        if check["check_id"] == "pytest_changed_owners"
    )
    assert "tests/test_skill_wrapper_contract.py" in pytest_check["command"]
    assert "tests/test_skill_wrapper_cwd.py" not in pytest_check["command"]
    assert payload["required_later"] == {
        "handoff": ["doctor"],
        "final_milestone": ["smoke"],
        "release": ["full_pytest"],
    }


def test_typed_owner_adds_the_existing_mypy_scope_once() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/foundation/text_values.py"],
        repo_root=REPO_ROOT,
    )

    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1


def test_scientific_transaction_type_owner_has_the_exact_scoped_paths() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured_files = frozenset(
        value
        for value in project["tool"]["mypy"]["files"]
        if (REPO_ROOT / value).is_file()
    )

    assert SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert len(SCIENTIFIC_TRANSACTION_TYPE_PATHS) == 91
    assert {
        "src/sciplot_core/studio_core/control_results.py",
        "src/sciplot_core/studio_core/sample_style.py",
    } <= SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert SCIENTIFIC_TRANSACTION_TYPE_PATHS == frozenset(
        path
        for path in configured_files
        if not any(
            owner.matches(path)
            for owner in (
                TYPED_CORE_CONTRACT_OWNER,
                STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER,
                STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER,
                STUDIO_FIGURE_SET_PUBLICATION_TYPE_OWNER,
                STUDIO_PROJECT_REGISTRY_TYPE_OWNER,
                WORKFLOW_EXPORT_FORMAT_TYPE_OWNER,
            )
        )
    )
    for value in project["tool"]["mypy"]["files"]:
        target = REPO_ROOT / value
        probe = value if target.is_file() else f"{value.rstrip('/')}/scope_probe.py"
        assert (
            sum(
                owner.matches(probe)
                for owner in (
                    TYPED_CORE_CONTRACT_OWNER,
                    STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER,
                    STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER,
                    STUDIO_FIGURE_SET_PUBLICATION_TYPE_OWNER,
                    STUDIO_PROJECT_REGISTRY_TYPE_OWNER,
                    WORKFLOW_EXPORT_FORMAT_TYPE_OWNER,
                    SCIENTIFIC_TRANSACTION_TYPE_OWNER,
                )
            )
            == 1
        )


@pytest.mark.parametrize("path", sorted(SCIENTIFIC_TRANSACTION_TYPE_PATHS))
def test_scientific_transaction_type_owner_adds_mypy_once(path: str) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    type_owner = next(
        owner
        for owner in payload["owners"]
        if owner["owner_id"] == "scientific_transaction_type_gate"
    )
    assert type_owner == {
        "owner_id": "scientific_transaction_type_gate",
        "changed_paths": [path],
        "pytest_targets": [],
    }
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1


def test_unrelated_scientific_transform_path_does_not_add_mypy() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/semantic_sources/rheology_confirmation.py"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "scientific_transform"
    ]
    assert all(check["check_id"] != "mypy_owned_scope" for check in payload["checks"])


def test_studio_registry_state_selects_snapshot_binding_evidence() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/studio_core/registry_state.py"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "generic_terminal_preparation",
        "studio_project_registry_type",
    ]
    pytest_check = next(
        check
        for check in payload["checks"]
        if check["check_id"] == "pytest_changed_owners"
    )
    assert "tests/test_studio_snapshot_binding.py" in pytest_check["command"]
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1


def test_studio_project_registry_type_owner_has_the_exact_scoped_paths() -> None:
    assert STUDIO_PROJECT_REGISTRY_TYPE_PATHS == frozenset(
        {
            "src/sciplot_core/studio_core/prepare_existing.py",
            "src/sciplot_core/studio_core/registry_state.py",
            "src/sciplot_core/studio_core/registry_writes.py",
            "src/sciplot_core/studio_core/studio_prepare.py",
        }
    )


def test_studio_single_prepare_test_has_one_registry_owner() -> None:
    payload = build_changed_verification_plan(
        ["tests/test_studio_single_prepare.py"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "studio_project_registry_type"
    ]
    assert payload["unowned_paths"] == []


@pytest.mark.parametrize("path", sorted(STUDIO_PROJECT_REGISTRY_TYPE_PATHS))
def test_studio_project_registry_type_owner_adds_mypy_once(path: str) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    type_owner = next(
        owner
        for owner in payload["owners"]
        if owner["owner_id"] == "studio_project_registry_type"
    )
    assert type_owner["changed_paths"] == [path]
    assert {
        "tests/test_figure_plan_entrypoint_state.py",
        "tests/test_intake_atomic_packaging.py",
        "tests/test_studio_presentation_identity.py",
        "tests/test_studio_rule_contract_prepare.py",
        "tests/test_studio_single_prepare.py",
        "tests/test_studio_snapshot_binding.py",
    }.issubset(type_owner["pytest_targets"])
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1
    assert payload["required_later"] == {
        "handoff": [],
        "final_milestone": ["smoke"],
        "release": ["acceptance_rules", "full_pytest"],
    }


@pytest.mark.parametrize(
    ("path", "expected_owner_ids"),
    [
        (
            "src/sciplot_core/studio_core/publish_inventory.py",
            [
                "generic_terminal_preparation",
                "studio_figure_set_publication_type",
            ],
        ),
        (
            "src/sciplot_core/studio_core/request_paths.py",
            ["studio_figure_set_publication_type"],
        ),
        (
            "src/sciplot_core/studio_core/figure_set_publication_scope.py",
            ["studio_figure_set_publication_type"],
        ),
        (
            "src/sciplot_core/studio_core/publish_finalize.py",
            [
                "generic_terminal_preparation",
                "studio_figure_set_publication_type",
            ],
        ),
        (
            "src/sciplot_core/studio_core/publish_run.py",
            [
                "generic_terminal_preparation",
                "studio_figure_set_publication_type",
            ],
        ),
    ],
)
def test_studio_figure_set_publication_paths_add_mypy_once(
    path: str,
    expected_owner_ids: list[str],
) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    assert [owner["owner_id"] for owner in payload["owners"]] == expected_owner_ids
    type_owner = next(
        owner
        for owner in payload["owners"]
        if owner["owner_id"] == "studio_figure_set_publication_type"
    )
    assert type_owner == {
        "owner_id": "studio_figure_set_publication_type",
        "changed_paths": [path],
        "pytest_targets": [
            "tests/test_studio_publish_inventory.py",
            *ARCHITECTURE_CORE_TARGETS,
        ],
    }
    assert payload["unowned_paths"] == []
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1
    assert payload["required_later"] == {
        "handoff": [],
        "final_milestone": ["smoke"],
        "release": ["acceptance_rules", "full_pytest"],
    }


def test_workflow_export_format_type_owner_has_the_exact_scoped_paths() -> None:
    assert WORKFLOW_EXPORT_FORMAT_TYPE_PATHS == frozenset(
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


def test_workflow_facade_selects_impact_export_compatibility_evidence() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/workflow/__init__.py"],
        repo_root=REPO_ROOT,
    )

    ai_owner = next(
        owner
        for owner in payload["owners"]
        if owner["owner_id"] == "ai_autoplot_invocation"
    )
    assert (
        "tests/test_impact_condition_figure_set.py::"
        "test_impact_bundle_renders_the_same_semantic_source_with_selected_template"
        in ai_owner["pytest_targets"]
    )


@pytest.mark.parametrize("path", sorted(WORKFLOW_EXPORT_FORMAT_TYPE_PATHS))
def test_workflow_export_format_type_owner_adds_mypy_once(path: str) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    type_owner = next(
        owner
        for owner in payload["owners"]
        if owner["owner_id"] == "workflow_export_format_type"
    )
    assert type_owner["changed_paths"] == [path]
    assert {
        "tests/test_generic_single_task_plan.py",
        "tests/test_impact_condition_figure_set.py",
        "tests/test_mechanical_workflow_bundle.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_temperature_workflow_repair.py",
        "tests/test_workflow_bundle_dispatch.py",
    }.issubset(type_owner["pytest_targets"])
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_mechanical_workflow_bundle.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_temperature_workflow_repair.py",
    ],
)
def test_workflow_export_format_tests_have_one_type_owner(path: str) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "workflow_export_format_type"
    ]
    assert payload["unowned_paths"] == []


def test_unrelated_workflow_path_does_not_add_export_format_mypy() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/workflow/legacy_route_rendering.py"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "scientific_transform"
    ]
    assert all(check["check_id"] != "mypy_owned_scope" for check in payload["checks"])


def test_studio_figure_set_lifecycle_type_owner_has_exact_unique_config() -> None:
    expected = frozenset(
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
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured = project["tool"]["mypy"]["files"]

    assert STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS == expected
    assert len(STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS) == 10
    assert all(configured.count(path) == 1 for path in expected)


def test_studio_figure_set_publication_type_owner_has_exact_unique_config() -> None:
    expected = frozenset(
        {
            "src/sciplot_core/studio_core/figure_set_publication_scope.py",
            "src/sciplot_core/studio_core/publish_finalize.py",
            "src/sciplot_core/studio_core/publish_inventory.py",
            "src/sciplot_core/studio_core/publish_run.py",
            "src/sciplot_core/studio_core/request_paths.py",
        }
    )
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured = project["tool"]["mypy"]["files"]

    assert STUDIO_FIGURE_SET_PUBLICATION_TYPE_PATHS == expected
    assert len(STUDIO_FIGURE_SET_PUBLICATION_TYPE_PATHS) == 5
    assert all(configured.count(path) == 1 for path in expected)


def test_studio_figure_set_execution_type_owner_has_exact_unique_config() -> None:
    expected = frozenset(
        {
            "src/sciplot_core/studio_core/figure_registry_geometry.py",
            "src/sciplot_core/studio_core/figure_requests.py",
            "src/sciplot_core/studio_core/figure_source_request.py",
            "src/sciplot_core/studio_core/impact_task_sources.py",
            "src/sciplot_core/studio_core/mechanical_task_source_lifecycle.py",
        }
    )
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    configured = project["tool"]["mypy"]["files"]

    assert STUDIO_FIGURE_SET_EXECUTION_TYPE_OWNER.exact_paths == expected
    assert STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS == expected
    assert len(STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS) == 5
    assert all(configured.count(path) == 1 for path in expected)


def test_explicit_type_gate_scopes_are_pairwise_disjoint() -> None:
    scopes = (
        SCIENTIFIC_TRANSACTION_TYPE_PATHS,
        STUDIO_PROJECT_REGISTRY_TYPE_PATHS,
        WORKFLOW_EXPORT_FORMAT_TYPE_PATHS,
        STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS,
        STUDIO_FIGURE_SET_PUBLICATION_TYPE_PATHS,
        STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS,
    )

    assert tuple(map(len, scopes)) == (91, 4, 7, 10, 5, 5)
    assert all(
        scope.isdisjoint(other)
        for index, scope in enumerate(scopes)
        for other in scopes[index + 1 :]
    )


@pytest.mark.parametrize("path", sorted(STUDIO_FIGURE_SET_LIFECYCLE_TYPE_PATHS))
def test_studio_figure_set_lifecycle_type_owner_adds_mypy_once(path: str) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    type_owner = next(
        owner
        for owner in payload["owners"]
        if owner["owner_id"] == "studio_figure_set_lifecycle_type"
    )
    assert type_owner["changed_paths"] == [path]
    assert {
        "tests/test_mechanical_studio_task_sources.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_studio_figure_task_chain.py",
        "tests/test_studio_publish_inventory.py",
        "tests/test_studio_rule_contract_prepare.py",
        "tests/test_studio_single_prepare.py",
        "tests/test_veusz_series_revision.py",
        *ARCHITECTURE_CORE_TARGETS,
    }.issubset(type_owner["pytest_targets"])
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1
    assert payload["required_later"] == {
        "handoff": [],
        "final_milestone": ["smoke"],
        "release": ["acceptance_rules", "full_pytest"],
    }


@pytest.mark.parametrize(
    ("path", "expected_owner_ids"),
    [
        (
            "src/sciplot_core/studio_core/figure_task_evidence.py",
            ["generic_terminal_preparation", "studio_figure_set_lifecycle_type"],
        ),
        (
            "src/sciplot_core/studio_core/prepare_generated_transaction.py",
            ["generic_terminal_preparation", "studio_figure_set_lifecycle_type"],
        ),
        (
            "src/sciplot_core/studio_core/figure_set_storage.py",
            ["studio_figure_set_lifecycle_type", "native_series_revision"],
        ),
    ],
)
def test_studio_figure_set_lifecycle_owner_overlap_order(
    path: str,
    expected_owner_ids: list[str],
) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    assert [owner["owner_id"] for owner in payload["owners"]] == expected_owner_ids


def test_studio_figure_task_chain_test_has_one_lifecycle_owner() -> None:
    payload = build_changed_verification_plan(
        ["tests/test_studio_figure_task_chain.py"],
        repo_root=REPO_ROOT,
    )

    assert STUDIO_FIGURE_SET_LIFECYCLE_TYPE_OWNER.owned_test_paths == frozenset(
        {
            "tests/test_mechanical_studio_task_sources.py",
            "tests/test_studio_figure_task_chain.py",
        }
    )
    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "studio_figure_set_lifecycle_type"
    ]
    assert payload["unowned_paths"] == []


def test_mechanical_studio_task_source_test_has_one_lifecycle_owner() -> None:
    payload = build_changed_verification_plan(
        ["tests/test_mechanical_studio_task_sources.py"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "studio_figure_set_lifecycle_type"
    ]
    assert payload["unowned_paths"] == []


def test_presentation_evidence_selects_terminal_preparation_owner() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/studio_core/presentation_evidence.py"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "generic_terminal_preparation"
    ]
    pytest_check = next(
        check
        for check in payload["checks"]
        if check["check_id"] == "pytest_changed_owners"
    )
    assert {
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_studio_figure_task_chain.py",
        "tests/test_studio_publish_inventory.py",
    }.issubset(pytest_check["command"])


@pytest.mark.parametrize(
    "path",
    sorted(STUDIO_FIGURE_SET_EXECUTION_TYPE_PATHS),
)
def test_stage49_execution_paths_add_mypy_once(path: str) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "studio_figure_set_execution_type"
    ]
    type_owner = payload["owners"][0]
    assert {
        "tests/test_resolved_frequency_figure_plan.py",
        "tests/test_impact_condition_figure_set.py",
        "tests/test_mechanical_studio_task_sources.py",
        "tests/test_performance_figure_plan_activation.py",
        "tests/test_studio_figure_task_chain.py",
        *ARCHITECTURE_CORE_TARGETS,
    }.issubset(type_owner["pytest_targets"])
    assert payload["unowned_paths"] == []
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1
    assert payload["required_later"] == {
        "handoff": [],
        "final_milestone": ["smoke"],
        "release": ["acceptance_rules", "full_pytest"],
    }


@pytest.mark.parametrize(
    ("path", "expected_owner_id"),
    [
        (
            "src/sciplot_core/studio_core/figure_set_prepare.py",
            "studio_figure_set_lifecycle_type",
        ),
        (
            "src/sciplot_core/studio_core/figure_set_publication_scope.py",
            "studio_figure_set_publication_type",
        ),
        (
            "src/sciplot_core/studio_core/request_paths.py",
            "studio_figure_set_publication_type",
        ),
        (
            "src/sciplot_core/studio_core/source_bound_prepare.py",
            "scientific_transaction_type_gate",
        ),
    ],
)
def test_stage49_execution_owner_does_not_absorb_existing_type_scopes(
    path: str,
    expected_owner_id: str,
) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    owner_ids = [owner["owner_id"] for owner in payload["owners"]]

    assert expected_owner_id in owner_ids
    assert "studio_figure_set_execution_type" not in owner_ids
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1


@pytest.mark.parametrize(
    "path",
    [
        "src/sciplot_core/mechanical_task_sources.py",
        "src/sciplot_core/studio_core/impact_series.py",
        "src/sciplot_core/studio_core/json_files.py",
    ],
)
def test_stage49_adjacent_untyped_paths_do_not_add_execution_mypy(path: str) -> None:
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)

    assert all(
        owner["owner_id"] != "studio_figure_set_execution_type"
        for owner in payload["owners"]
    )
    assert all(check["check_id"] != "mypy_owned_scope" for check in payload["checks"])


def test_mypy_scope_configuration_adds_mypy_once() -> None:
    payload = build_changed_verification_plan(
        ["pyproject.toml"],
        repo_root=REPO_ROOT,
    )

    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "verification_policy",
        "mypy_scope_configuration",
    ]
    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1


def test_deleted_owned_source_selects_owner_evidence_but_not_ruff() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/intake/deleted_owner.py"],
        repo_root=REPO_ROOT,
    )

    assert payload["status"] == "planned"
    assert [owner["owner_id"] for owner in payload["owners"]] == ["intake_project"]
    assert [check["check_id"] for check in payload["checks"]] == [
        "pytest_changed_owners",
        "diff_whitespace",
    ]


def test_no_changes_passes_without_running_an_empty_focused_tier() -> None:
    calls: list[list[str]] = []

    result = run_changed_verification(
        repo_root=REPO_ROOT,
        changed_paths=[],
        command_runner=lambda command, _cwd: (
            calls.append(list(command)) or _completed(command)
        ),
    )

    assert result["status"] == "passed"
    assert result["checks"] == []
    assert calls == []


@pytest.mark.parametrize(
    "path",
    ["src/sciplot_core/unowned.py", "tests/test_deleted_owner.py"],
)
def test_unowned_or_deleted_path_fails_without_broad_fallback(path: str) -> None:
    calls: list[list[str]] = []

    result = run_changed_verification(
        repo_root=REPO_ROOT,
        changed_paths=[path],
        command_runner=lambda command, _cwd: (
            calls.append(list(command)) or _completed(command)
        ),
    )

    assert result["status"] == "failed"
    assert result["unowned_paths"] == [path]
    assert result["checks"] == []
    assert calls == []


def test_check_failure_is_projected_without_retry_or_gate_expansion() -> None:
    calls: list[list[str]] = []

    def runner(
        command: Sequence[str],
        _cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return _completed(
            command,
            returncode=1 if "pytest" in command else 0,
            stderr="focused failure" if "pytest" in command else "",
        )

    result = run_changed_verification(
        repo_root=REPO_ROOT,
        changed_paths=["tests/test_changed_verification.py"],
        command_runner=runner,
    )

    assert result["status"] == "failed"
    assert [check["status"] for check in result["checks"]] == [
        "passed",
        "failed",
        "passed",
    ]
    assert len(calls) == 3
    pytest_calls = [command for command in calls if "pytest" in command]
    assert len(pytest_calls) == 1
    assert pytest_calls[0].count("tests/test_changed_verification.py") == 1
    assert "tests/test_skill_wrapper_cwd.py" not in pytest_calls[0]
