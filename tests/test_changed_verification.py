from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

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


@pytest.mark.parametrize(("path", "target"), [
    ("src/sciplot_core/studio_render/categorical_layout.py", "tests/test_task_ordinary_raw_points.py"),
    ("src/sciplot_core/task_series_edits.py", "tests/test_series_display.py"),
    ("src/sciplot_core/studio_core/series_display.py", "tests/test_series_display.py"),
    ("src/sciplot_core/plot_engine/managed_source_append.py", "tests/test_managed_source_append.py"),
])
def test_source_bound_display_and_append_owners_keep_discriminating_evidence(path, target):
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    checks = {check["check_id"]: check["command"] for check in plan["checks"]}
    assert target in checks["pytest_changed_owners"]
    assert checks["mypy_owned_scope"] == [sys.executable, "-m", "mypy"]
    assert "full_pytest" in plan["required_later"]["release"]


@pytest.mark.parametrize("path", [
    "src/sciplot_core/plot_document/patch.py",
    "src/sciplot_core/native_process/session.py", "src/sciplot_core/veusz_worker/persistent.py",
    "src/sciplot_core/plot_backends/veusz.py",
    "src/sciplot_core/plot_engine/storage.py",
    "src/sciplot_core/plot_protocol/rpc.py",
    "src/sciplot_core/cli/parsers/plots.py",
    "src/sciplot_core/cli/dispatch/plots.py",
    "tests/test_plot_document.py", "tests/test_plot_cache.py", "tests/test_plot_content_store.py", "tests/test_plot_backend.py", "tests/test_plot_backend_native.py",
    "tests/test_plot_backend_semantics.py", "tests/test_plot_backend_semantics_native.py",
    "tests/test_native_process.py", "tests/test_native_process_native.py",
    "tests/test_plot_protocol.py", "tests/test_plot_typed_intent_recovery.py",
    "tests/test_managed_rebuild_explanation.py", "tests/test_figure_qa_renderer_lifetime.py",
    "tests/test_plot_engine.py", "tests/test_plot_engine_native.py",
])
def test_semantic_plot_sources_and_tests_select_transaction_and_native_evidence(path):
    payload = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert payload["unowned_paths"] == []
    checks = {check["check_id"]: check["command"] for check in payload["checks"]}
    assert checks["mypy_owned_scope"] == [sys.executable, "-m", "mypy"]
    if path == "tests/test_plot_typed_intent_recovery.py":
        assert {"tests/test_plot_typed_intent.py", "tests/test_plot_typed_intent_recovery.py",
                "tests/test_figure_document.py"} <= set(checks["pytest_changed_owners"])
    else:
        assert {"tests/test_plot_document.py", "tests/test_plot_backend.py", "tests/test_plot_backend_native.py", "tests/test_plot_protocol.py",
                "tests/test_plot_typed_intent_recovery.py",
                "tests/test_managed_rebuild_explanation.py",
                "tests/test_plot_engine.py", "tests/test_plot_engine_native.py"} <= set(checks["pytest_changed_owners"])
    assert payload["required_later"]["handoff"] == ["doctor"]
    assert payload["required_later"]["final_milestone"] == ["smoke"]


def test_tavotto_ui_license_selects_documentation_contract() -> None:
    path = "third_party/tavotto-ui/LICENSE"
    assert (REPO_ROOT / path).is_file()
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    assert [owner["owner_id"] for owner in plan["owners"]] == ["documentation_contract"]
    check = next(item for item in plan["checks"] if item["check_id"] == "pytest_changed_owners")
    assert "tests/test_documentation_contract.py" in check["command"]


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
        if list(command[:2]) == ["git", "rev-parse"]:
            return _completed(command, stdout="a" * 40 + "\n")
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
        ["git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"],
        ["git", "diff", "--name-only", "--no-renames", "-z", "--cached", "a" * 40, "--"],
        ["git", "diff", "--name-only", "--no-renames", "-z", "--"],
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
    from sciplot_core.verification.owners import CHANGED_OWNERS

    wrapper_owner = next(owner for owner in CHANGED_OWNERS if owner.owner_id == "skill_wrapper")
    assert "tests/test_skill_wrapper_cwd.py" in wrapper_owner.exact_paths
    assert "tests/test_skill_wrapper_cwd.py" in wrapper_owner.owned_test_paths
    payload = build_changed_verification_plan(
        ["skill/scripts/sciplot"],
        repo_root=REPO_ROOT,
    )

    assert payload["status"] == "planned"
    assert payload["owners"] == [
        {
            "owner_id": "skill_wrapper",
            "changed_paths": ["skill/scripts/sciplot"],
            "pytest_targets": ["tests/test_skill_wrapper_contract.py", "tests/test_skill_wrapper_framework.py"],
        }
    ]
    pytest_check = next(
        check
        for check in payload["checks"]
        if check["check_id"] == "pytest_changed_owners"
    )
    assert "tests/test_skill_wrapper_contract.py" in pytest_check["command"]
    assert "tests/test_skill_wrapper_framework.py" in pytest_check["command"]
    assert ["-m", "focused"] == pytest_check["command"][4:6]
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

    coordinate_path = "src/sciplot_core/task_semantic_coordinates.py"
    assert project["tool"]["mypy"]["files"].count(coordinate_path) == 1
    assert coordinate_path in SCIENTIFIC_TRANSACTION_TYPE_OWNER.exact_paths
    assert SCIENTIFIC_TRANSACTION_TYPE_PATHS
    round_trip_paths = {
        "src/sciplot_core/task_series_edits.py",
        "src/sciplot_core/studio_core/series_display.py",
        "src/sciplot_core/data_mapping/table_choice.py",
        "src/sciplot_core/data_mapping/table_metadata.py",
        "src/sciplot_core/data_mapping/plan_binding.py",
        "src/sciplot_core/data_mapping/original_tables.py",
        "src/sciplot_core/semantic_sources/instrument_regions.py",
        "src/sciplot_core/semantic_sources/numeric_separators.py",
        "src/sciplot_core/materials_rules/analysis.py",
        "src/sciplot_core/materials_rules/impact_presentation.py",
        "src/sciplot_core/materials_rules/mechanical_rules.py",
        "src/sciplot_core/studio_core/publish_sources.py",
        "src/sciplot_core/studio_core/veusz_data_import.py",
        "src/sciplot_core/studio_render/categorical_layout.py",
        "src/sciplot_core/studio_render/categorical_series.py",
        "src/sciplot_core/studio_render/replicate_distribution_contract.py",
        "src/sciplot_core/task_scientific_presentation.py",
        "src/sciplot_core/veusz_worker/spec_audit/categorical_axis.py",
        "src/sciplot_core/veusz_worker/axis_matchers.py",
    }
    assert round_trip_paths <= SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert all(project["tool"]["mypy"]["files"].count(path) == 1 for path in round_trip_paths)
    assert {
        "src/sciplot_core/task_semantic_contract.py",
        coordinate_path,
        "src/sciplot_core/task_semantic_plan.py",
        "src/sciplot_core/task_semantic_figure.py",
        "src/sciplot_core/task_semantic_frequency.py",
        "src/sciplot_core/task_semantic_creation.py",
        "src/sciplot_core/task_semantic_delivery.py",
        "src/sciplot_core/task_semantic_next_step.py",
        "src/sciplot_core/task_errors.py",
        "src/sciplot_core/source_inspection/input_errors.py",
        "src/sciplot_core/source_inspection/model_recognition.py",
        "src/sciplot_core/source_inspection/inspection.py",
        "src/sciplot_core/source_inspection/semantic_evidence.py",
    } <= SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert {"src/sciplot_core/panel_assembly/document.py",
            "src/sciplot_core/panel_assembly/native_styles.py",
            "src/sciplot_core/panel_assembly/service.py"} <= SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert "src/sciplot_core/task_edit_context.py" in SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert "src/sciplot_core/task_shortcuts.py" in SCIENTIFIC_TRANSACTION_TYPE_PATHS
    assert {
        "src/sciplot_core/verification/evidence_identity.py",
        "src/sciplot_core/verification/evidence_scope.py",
        "src/sciplot_core/verification/input_scope.py",
        "src/sciplot_core/verification/public_input_guard.py",
        "src/sciplot_core/verification/public_stage.py",
        "src/sciplot_core/verification/public_control_boundary.py",
        "src/sciplot_core/verification/public_guard_bootstrap/sitecustomize.py",
        "src/sciplot_core/verification/private_observer.py",
        "src/sciplot_core/verification/private_observer_pytest.py",
        "src/sciplot_core/verification/private_capture.py",
        "src/sciplot_core/verification/private_process_boundaries.py",
        "src/sciplot_core/verification/native_probe_boundary.py",
        "src/sciplot_core/verification/evidence_environment.py",
        "src/sciplot_core/setting_catalog/specs/key.py",
        "src/sciplot_core/studio_core/control_results.py",
        "src/sciplot_core/studio_core/sample_style.py",
        "src/sciplot_core/data_mapping/curve_support.py",
        "src/sciplot_core/data_mapping/table_diagnostics.py",
        "src/sciplot_core/data_mapping/table_candidates.py",
        "src/sciplot_core/task_common_edits.py",
        "src/sciplot_core/native_font_catalog.py",
        "src/sciplot_core/veusz_worker/font_catalog.py",
        "src/sciplot_core/cli/parsers/common_edits.py",
        "src/sciplot_core/cli/dispatch/common_edits.py",
        "src/sciplot_core/task_saved_work.py",
        "src/sciplot_core/task_saved_work_evidence.py",
        "src/sciplot_core/task_papers.py",
        "src/sciplot_core/task_paper_contract.py",
        "src/sciplot_core/task_paper_delivery.py",
        "src/sciplot_core/task_paper_native.py",
        "src/sciplot_core/task_paper_sources.py",
        "src/sciplot_core/cli/task_paper.py",
        "src/sciplot_core/delivery/install.py",
        "src/sciplot_core/render/target_paths.py",
        "src/sciplot_core/veusz_worker/__main__.py",
        "src/sciplot_core/task_capabilities.py",
        "src/sciplot_core/task_repair.py",
        "src/sciplot_core/task_error_feedback.py",
        "src/sciplot_core/task_recovery_policy.py",
        "src/sciplot_core/style_values.py",
        "src/sciplot_core/cli/parser_errors.py",
        "src/sciplot_core/task_output_choice.py",
        "src/sciplot_core/cli/parsers/plots.py",
        "src/sciplot_core/cli/dispatch/plots.py",
        "src/sciplot_core/veusz_worker/managed.py",
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


def test_no_changes_reports_no_tests_without_running_an_empty_focused_tier() -> None:
    calls: list[list[str]] = []

    result = run_changed_verification(
        repo_root=REPO_ROOT,
        changed_paths=[],
        command_runner=lambda command, _cwd: (
            calls.append(list(command)) or _completed(command)
        ),
    )

    assert result["status"] == "NO_TESTS"
    assert result["checks"] == []
    assert result["checks_executed"] == 0
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


def _scope_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        cwd=repo, text=True,
    ).strip()


@pytest.fixture
def scope_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "verification-repo"
    repo.mkdir()
    _scope_git(repo, "init", "-q")
    _scope_git(repo, "config", "user.name", "Verification Test")
    _scope_git(repo, "config", "user.email", "verification@example.invalid")
    (repo / "README.md").write_text("base\n")
    _scope_git(repo, "add", "README.md")
    _scope_git(repo, "commit", "-qm", "base")
    base = _scope_git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("changed\n")
    source = repo / "src/sciplot_core/foundation/file_hashing.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n")
    _scope_git(repo, "add", ".")
    _scope_git(repo, "commit", "-qm", "shared interface")
    middle = _scope_git(repo, "rev-parse", "HEAD")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    _scope_git(repo, "add", "pyproject.toml")
    _scope_git(repo, "commit", "-qm", "configuration")
    return repo, base, middle, _scope_git(repo, "rev-parse", "HEAD")


def test_clean_committed_delta_requires_a_base_and_records_resolved_commits(scope_repo) -> None:
    repo, base, _middle, head = scope_repo
    empty = run_changed_verification(repo_root=repo, plan_only=True)
    assert empty["status"] == "NO_TESTS" and empty["checks"] == []
    assert empty["comparison"]["resolved_base"] == head
    assert "committed" not in empty["comparison"]["includes"]
    calls: list[list[str]] = []

    def git_only(command, cwd):
        calls.append(list(command))
        assert command[0] == "git", "Plan-only executed a non-Git verification gate"
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True)

    plan = run_changed_verification(
        repo_root=repo, base="HEAD~2", plan_only=True, command_runner=git_only,
    )
    assert plan["status"] == "planned" and plan["checks_executed"] == 0
    assert plan["changed_paths"] == [
        "README.md", "pyproject.toml", "src/sciplot_core/foundation/file_hashing.py",
    ]
    assert plan["comparison"] == {
        "base": "HEAD~2", "resolved_base": base, "resolved_head": head,
        "includes": ["committed", "staged", "unstaged", "untracked"], "source": "git",
    }
    assert all(check["status"] == "planned" for check in plan["checks"])
    assert sum(check["check_id"] == "mypy_owned_scope" for check in plan["checks"]) == 1
    assert {"documentation_contract", "typed_core_contracts", "verification_policy", "mypy_scope_configuration"} <= {
        owner["owner_id"] for owner in plan["owners"]
    }
    whitespace = next(check for check in plan["checks"] if check["check_id"] == "diff_whitespace")
    assert whitespace["command"] == ["git", "diff", "--check", base, "--"]
    assert ["git", "diff", "--name-only", "--no-renames", "-z", base, head, "--"] in calls


def test_different_bases_select_their_distinct_committed_paths(scope_repo) -> None:
    repo, base, middle, _head = scope_repo
    assert collect_changed_paths(repo, base=middle) == ["pyproject.toml"]
    assert collect_changed_paths(repo, base=base) == [
        "README.md", "pyproject.toml", "src/sciplot_core/foundation/file_hashing.py",
    ]


def test_base_execution_runs_each_planned_gate_once_with_the_resolved_scope(scope_repo) -> None:
    repo, _base, middle, head = scope_repo
    executed = []

    def runner(command, cwd):
        if command[0] == "git" and "--check" not in command:
            return subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        executed.append(list(command))
        return _completed(command)

    result = run_changed_verification(repo_root=repo, base=middle, command_runner=runner)
    assert result["status"] == "passed"
    assert result["changed_paths"] == ["pyproject.toml"]
    assert result["comparison"]["resolved_head"] == head
    assert result["comparison"]["resolved_base"] == middle
    assert result["checks_executed"] == len(executed) == 3
    assert [item["command"] for item in result["checks"]] == executed
    assert sum("pytest" in command for command in executed) == 1
    assert executed[-1] == ["git", "diff", "--check", middle, "--"]


def test_base_scope_unions_staged_unstaged_and_untracked_even_if_net_diff_cancels(scope_repo) -> None:
    repo, _base, _middle, head = scope_repo
    readme = repo / "README.md"
    readme.write_text("staged change\n")
    _scope_git(repo, "add", "README.md")
    readme.write_text("changed\n")  # Worktree matches HEAD; index still differs.
    (repo / "src/sciplot_core/foundation/file_hashing.py").write_text("VALUE = 2\n")
    name = "docs/ leading \n验证.md "
    untracked = repo / name
    untracked.parent.mkdir()
    untracked.write_text("untracked\n")
    assert collect_changed_paths(repo, base=head) == [
        "README.md", name, "src/sciplot_core/foundation/file_hashing.py",
    ]
    assert collect_changed_paths(repo) == [
        "README.md", name, "src/sciplot_core/foundation/file_hashing.py",
    ]


@pytest.mark.parametrize("registered", [True, False])
def test_committed_rename_and_delete_keep_both_owner_endpoints(scope_repo, registered) -> None:
    repo, _base, _middle, head = scope_repo
    old = "src/sciplot_core/foundation/file_hashing.py"
    new = "src/sciplot_core/foundation/new_values.py" if registered else "src/sciplot_core/unowned.py"
    _scope_git(repo, "mv", old, new)
    _scope_git(repo, "rm", "README.md")
    _scope_git(repo, "commit", "-qm", "rename and delete")
    plan = run_changed_verification(repo_root=repo, base=head, plan_only=True)
    assert plan["changed_paths"] == sorted(["README.md", old, new])
    if registered:
        assert plan["status"] == "planned"
        ruff = next(check for check in plan["checks"] if check["check_id"] == "ruff_changed_python")
        assert new in ruff["command"] and old not in ruff["command"]
    else:
        assert plan["status"] == "failed" and plan["unowned_paths"] == [new]
        assert plan["checks"] == [] and plan["checks_executed"] == 0


@pytest.mark.parametrize("revision", ["missing-ref", "--all", "", "HEAD:README.md"])
def test_invalid_base_fails_before_any_verification_gate(scope_repo, revision) -> None:
    repo, _base, _middle, _head = scope_repo
    calls: list[list[str]] = []

    def git_only(command, cwd):
        calls.append(list(command))
        assert command[:2] == ["git", "rev-parse"]
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True)

    result = run_changed_verification(repo_root=repo, base=revision, command_runner=git_only)
    assert result["status"] == "failed" and result["checks"] == []
    assert result["checks_executed"] == 0
    assert result["error"]["reason_code"] == "invalid_verification_scope"
    assert all("--end-of-options" in call for call in calls)


def test_git_collection_failure_is_not_an_empty_success() -> None:
    calls = []

    def runner(command, _cwd):
        calls.append(list(command))
        if command[1] == "rev-parse":
            return _completed(command, stdout="a" * 40)
        assert command[:2] == ["git", "diff"]
        return _completed(command, returncode=1)

    result = run_changed_verification(repo_root=REPO_ROOT, command_runner=runner)
    assert result["status"] == "failed" and result["checks"] == []
    assert result["error"]["reason_code"] == "invalid_verification_scope"
    assert len(calls) == 2 and result["checks_executed"] == 0


@pytest.mark.parametrize("paths", [[], ["DEVELOPMENT_LOG.md"]])
def test_empty_or_ignored_scope_is_not_pass_evidence_in_plan_or_execution(paths) -> None:
    for plan_only in (False, True):
        result = run_changed_verification(
            repo_root=REPO_ROOT, changed_paths=paths, plan_only=plan_only,
            command_runner=lambda *_args: pytest.fail("Empty scope executed a gate"),
        )
        assert result["status"] == "NO_TESTS" and result["checks"] == []
        assert result["checks_executed"] == 0


def test_explicit_path_scope_cannot_misrepresent_an_unresolved_git_base() -> None:
    result = run_changed_verification(
        repo_root=REPO_ROOT, changed_paths=["README.md"], base="HEAD~1",
        command_runner=lambda *_args: pytest.fail("Invalid scope executed a gate"),
    )
    assert result["status"] == "failed" and result["checks"] == []
    assert result["error"]["reason_code"] == "invalid_verification_scope"


@pytest.mark.parametrize("status,plan_only,expected_exit", [
    ("NO_TESTS", False, 2), ("NO_TESTS", True, 2),
    ("planned", True, 0), ("failed", True, 1),
])
def test_verify_cli_projects_plan_and_empty_scope_without_pass(status, plan_only, expected_exit, monkeypatch, capsys):
    from sciplot_core import cli, verification

    payload = build_changed_verification_plan([], repo_root=REPO_ROOT)
    payload["status"] = status
    calls = []

    def verify(**kwargs):
        calls.append(kwargs)
        return payload

    monkeypatch.setattr(verification, "run_changed_verification", verify)
    arguments = ["verify", "--changed", "--base", "HEAD~2", "--json"]
    if plan_only:
        arguments.append("--plan-only")
    assert cli.main(arguments) == expected_exit
    assert json.loads(capsys.readouterr().out) == payload
    assert calls == [{"base": "HEAD~2", **({"plan_only": True} if plan_only else {})}]


@pytest.mark.parametrize("path", ["src/sciplot_core/plot_engine/typed_intent.py",
                                  "tests/test_plot_typed_intent.py",
                                  "tests/test_plot_typed_intent_recovery.py"])
def test_typed_intent_leaf_selects_its_contract_and_preserves_later_gates(path):
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    owner_ids = {owner["owner_id"] for owner in plan["owners"]}
    assert "typed_plot_intent" in owner_ids and "semantic_plot_engine" not in owner_ids
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert {"tests/test_plot_typed_intent.py", "tests/test_plot_typed_intent_recovery.py",
            "tests/test_figure_document.py",
            "tests/test_plot_document.py::test_presentation_intent_cannot_change_scientific_binding",
            "tests/test_plot_engine.py::test_safe_patch_automatically_commits_and_exports_once_with_science_preserved",
            *ARCHITECTURE_CORE_TARGETS} <= set(command)
    assert "tests/test_plot_transforms.py" not in command
    assert plan["required_later"] == {"handoff": ["doctor"],
                                      "final_milestone": ["smoke"], "release": ["full_pytest"]}
    assert any(check["check_id"] == "mypy_owned_scope" for check in plan["checks"])


def test_mixed_leaf_and_backend_changes_keep_broad_native_evidence():
    from sciplot_core.verification.plot_owners import PLOT_OWNER

    assert not PLOT_OWNER.matches("src/sciplot_core/plot_engine/typed_intent.py")
    assert PLOT_OWNER.matches("src/sciplot_core/plot_engine/future_contract.py")
    plan = build_changed_verification_plan(["src/sciplot_core/plot_engine/typed_intent.py",
                                            "src/sciplot_core/plot_backends/veusz.py"], repo_root=REPO_ROOT)
    assert {"semantic_plot_engine", "typed_plot_intent"} <= {owner["owner_id"] for owner in plan["owners"]}
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_plot_backend_native.py" in command
    assert "tests/test_plot_transforms.py" in command


def test_quick_smoke_dispatch_keeps_full_default_and_rejects_unknown_profile(tmp_path, monkeypatch):
    from sciplot_core.smoke import runtime

    assert runtime.run_runtime_smoke.__kwdefaults__["profile"] == "full"
    monkeypatch.setattr(runtime, "_run_quick_runtime_smoke", lambda *, output_root: {"profile": "quick"})
    assert runtime.run_runtime_smoke(output_root=tmp_path, profile="quick") == {"profile": "quick"}
    with pytest.raises(ValueError, match="Unknown runtime smoke profile"):
        runtime.run_runtime_smoke(output_root=tmp_path, profile="unknown")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("fault", ["ready", "doctor", "source", "document", "export", "qa"])
def test_quick_smoke_fails_closed_on_native_and_artifact_evidence(tmp_path, monkeypatch, fault):
    import json
    from sciplot_core import studio
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.smoke import runtime

    calls = []
    monkeypatch.setattr("sciplot_core.doctor.doctor_payload",
                        lambda: {"status": "blocked" if fault == "doctor" else "ready"})

    def prepare(source, *, output_root, project_name):
        calls.append("prepare")
        output_root.mkdir()
        document = output_root / "document.vsz"
        document.write_bytes(b"native fixture")
        if fault == "source":
            source.write_bytes(b"changed coordinates")
        return {"project_dir": str(output_root), "document": str(document),
                "request": str(output_root / "request.json"), "series_count": 1}

    def export(document, *, formats, audit_spec_path):
        calls.append("export")
        assert formats == ["pdf", "tiff_300"] and audit_spec_path
        exports = []
        for fmt in formats:
            path = document.parent / fmt
            path.write_bytes(b"exported artifact")
            exports.append({"path": str(path), "format": fmt, "sha256": file_sha256(path)})
        return {"exports": exports, "document_sha256": file_sha256(document),
                "document_audit": {"status": "passed"}}

    def publish(**kwargs):
        calls.append("publish")
        assert kwargs["primary_native_audit"] == {"status": "passed"}
        document = kwargs["document_path"]
        if fault == "document":
            document.write_bytes(b"changed native bytes")
        if fault == "export":
            Path(kwargs["exports"][0]["path"]).write_bytes(b"changed artifact")
        manifest = document.parent / "manifest.json"
        manifest.write_text(json.dumps({"semantic": {"rule_id": "ftir_spectrum"},
            "exported_document_hash": kwargs["export_document_sha256"],
            "qa": {"status": "failed" if fault == "qa" else "passed"},
            "delivery_package": {"complete": True, "editable_vsz": {"hash_matches_export": True},
                                 "artifacts": [{"id": "qa_artifact_hashes_match_delivery", "exists": True}]}}))
        return {"manifest": str(manifest)}

    monkeypatch.setattr(studio, "prepare_studio_document", prepare)
    monkeypatch.setattr(studio, "export_studio_document", export)
    monkeypatch.setattr(studio, "publish_studio_export_run", publish)
    monkeypatch.setattr(runtime, "_scalar_field_render_probe", lambda *_: pytest.fail("quick invoked full scalar matrix"))
    result = runtime.run_runtime_smoke(output_root=tmp_path, profile="quick")
    assert result["status"] == ("passed" if fault == "ready" else "failed")
    assert result["profile"] == "quick" and result["elapsed_seconds"] >= 0
    assert result["coverage"]["deferred_to_full"]
    assert Path(result["artifacts"]["summary"]).is_file()
    assert calls == ([] if fault == "doctor" else ["prepare", "export", "publish"])


@pytest.mark.parametrize("path,owner,target", [
    ("src/sciplot_core/source_inspection/header_matching.py", "generic_axis_policy", "tests/test_source_recognition_contract.py"),
    ("src/sciplot_core/source_tables/parsing.py", "generic_axis_policy", "tests/test_legacy_core_migration.py"),
    ("src/sciplot_core/openai_provider/provider.py", "openai_assistant_provider", "tests/test_assistant_contract.py"),
    ("src/sciplot_core/openai_provider/environment.py", "openai_assistant_provider", "tests/test_assistant_contract.py"),
    ("src/sciplot_core/assistant_provider/text_validation.py", "openai_assistant_provider", "tests/test_assistant_contract.py"),
    ("src/sciplot_core/style_contract/template_contracts.py", "presentation_style_contract", "tests/test_style_template_contract.py"),
    ("src/sciplot_core/style_contract/template_validation.py", "presentation_style_contract", "tests/test_style_template_contract.py"),
    ("src/sciplot_core/presentation_identity.py", "presentation_style_contract", "tests/test_studio_presentation_identity.py"),
])
def test_consolidated_contract_owners_bind_current_and_removed_paths(path, owner, target):
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    assert owner in {item["owner_id"] for item in plan["owners"]}
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert target in command
    assert "full_pytest" in plan["required_later"]["release"]
    if owner != "generic_axis_policy":
        assert plan["required_later"]["handoff"] == ["doctor"]
        assert plan["required_later"]["final_milestone"] == ["smoke"]
    if path == "src/sciplot_core/source_tables/parsing.py":
        # Studio's independent terminal reread must select the same numeric
        # owner, including its binary64 and downstream source/series controls.
        terminal = build_changed_verification_plan(
            ["src/sciplot_core/studio_render/table_io.py"], repo_root=REPO_ROOT,
        )
        assert terminal["unowned_paths"] == []
        assert [item["owner_id"] for item in terminal["owners"]] == [
            "ordinary_categorical_sources", "generic_axis_policy",
        ]
        checks = {check["check_id"]: check["command"] for check in terminal["checks"]}
        assert {
            "tests/test_legacy_core_migration.py",
            "tests/test_generic_prepared_terminal_source.py",
            "tests/test_maintenance_integrity.py::test_studio_directory_read_fails_closed_on_one_unreadable_table",
            "tests/test_managed_document_science.py",
            "tests/test_scalar_field_rendering.py",
        } <= set(checks["pytest_changed_owners"])
        assert checks["pytest_changed_owners"].count("focused") == 1
        assert "full_pytest" in terminal["required_later"]["release"]
        assert "tests" not in checks["pytest_changed_owners"]
        unknown = build_changed_verification_plan(
            ["src/sciplot_core/studio_render/unregistered_table_reader.py"], repo_root=REPO_ROOT,
        )
        assert unknown["unowned_paths"] == ["src/sciplot_core/studio_render/unregistered_table_reader.py"]
        assert unknown["checks"] == []


def test_compatibility_facades_select_every_consolidated_contract():
    plan = build_changed_verification_plan(["tests/test_compatibility_facades.py"], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    assert {"generic_axis_policy", "openai_assistant_provider", "presentation_style_contract"} <= {
        owner["owner_id"] for owner in plan["owners"]}
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_compatibility_facades.py" in command
    assert {"acceptance_rules", "full_pytest"} <= set(plan["required_later"]["release"])
