"""Ancestor reduction retains the same pytest selection without touching options."""
from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core.verification import build_changed_verification_plan
from sciplot_core.verification.changed import _deduplicated_targets, _planned_checks


def test_whole_module_subsumes_leaf_nodes_without_absorbing_neighbor_modules():
    targets = [
        "tests/test_plot_document.py::test_patch[a::b]",
        "tests/test_plot_document.py", "tests/test_plot_document.py::test_patch",
        "tests/test_plot_document_extra.py::test_patch",
        "tests/test_plot_document.pyx::test_other",
    ]
    assert _deduplicated_targets(targets) == [
        "tests/test_plot_document.py", "tests/test_plot_document_extra.py::test_patch",
        "tests/test_plot_document.pyx::test_other",
    ]


def test_class_ancestor_is_literal_and_preserves_other_parameterized_nodes():
    targets = [
        "tests/test_example.py::Group::test_one[raw::parameter]",
        "tests/test_example.py::Group", "tests/test_example.py::GroupExtra::test_two",
        "tests/test_example.py::test_one[alpha::beta]",
        "tests/test_example.py::test_one[other]",
    ]
    assert _deduplicated_targets(targets) == targets[1:]


def test_option_arguments_are_not_treated_as_node_ancestors_or_reordered():
    targets = ["--override-ini=foo.py", "--override-ini=foo.py::value", "-k",
               "parameter::value", "-k", "parameter", "tests/test_example.py::test_one"]
    assert _deduplicated_targets(targets) == targets


def test_mixed_owner_command_reduces_selectors_but_keeps_all_module_coverage():
    checks = _planned_checks(
        python_paths=[], pytest_targets=["tests/test_plot_document.py::test_patch",
                                         "tests/test_plot_document.py",
                                         "tests/test_plot_engine.py::test_recovery"],
        mypy_required=False, has_changes=True,
    )
    pytest = next(check for check in checks if check["check_id"] == "pytest_changed_owners")
    assert pytest["command"][6:] == ["tests/test_plot_document.py", "tests/test_plot_engine.py::test_recovery"]


@pytest.mark.parametrize("path", [
    "src/sciplot_core/task_groups.py", "src/sciplot_core/task_group_contract.py",
    "src/sciplot_core/task_group_storage.py", "src/sciplot_core/task_group_review.py",
    "src/sciplot_core/task_group_gallery.py", "tests/test_task_groups.py",
])
def test_group_leaf_retains_creation_revision_and_public_consumer_regressions(path):
    plan = build_changed_verification_plan([path], repo_root=Path(__file__).resolve().parents[1])
    owners = {owner["owner_id"] for owner in plan["owners"]}
    assert "task_group_orchestration" in owners and "local_task_control" not in owners
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert {"tests/test_task_groups.py", "tests/test_task_groups_native.py",
            "tests/test_task_prepared_creation.py", "tests/test_task_revision_guards.py",
            "tests/test_task_control.py", "tests/test_task_papers.py",
            "tests/test_task_paper_selection.py", "tests/test_product_task_entries.py"} <= set(command)
    assert "tests/test_task_saved_work.py" not in command
    assert "full_pytest" in plan["required_later"]["release"]
    assert "smoke" in plan["required_later"]["final_milestone"]


@pytest.mark.parametrize("path", [
    "src/sciplot_core/task_papers.py", "src/sciplot_core/task_paper_contract.py",
    "src/sciplot_core/task_paper_sources.py", "src/sciplot_core/task_paper_native.py",
    "src/sciplot_core/task_paper_delivery.py", "src/sciplot_core/cli/task_paper.py",
    "tests/test_task_papers.py",
    "src/sciplot_core/task_paper_selection.py", "src/sciplot_core/task_paper_publication.py",
    "src/sciplot_core/task_paper_status.py", "tests/test_task_paper_selection.py",
    "tests/test_task_paper_publication.py",
])
def test_paper_leaf_retains_selection_package_install_and_public_regressions(path):
    plan = build_changed_verification_plan([path], repo_root=Path(__file__).resolve().parents[1])
    owners = {owner["owner_id"] for owner in plan["owners"]}
    assert "task_paper_publication" in owners and "local_task_control" not in owners
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert {"tests/test_task_papers.py", "tests/test_task_papers_native.py",
            "tests/test_task_groups.py", "tests/test_product_task_entries.py",
            "tests/test_output_package_contract.py", "tests/test_delivery_install.py",
            "tests/test_task_saved_work.py", "tests/test_task_paper_selection.py",
            "tests/test_task_paper_publication.py"} <= set(command)
    assert "tests/test_task_column_mapping.py" not in command
    assert "full_pytest" in plan["required_later"]["release"]


@pytest.mark.parametrize("path", [
    "src/sciplot_core/task_control.py", "src/sciplot_core/task_contract.py",
    "src/sciplot_core/task_storage.py", "src/sciplot_core/cli/parsers/tasks.py",
    "src/sciplot_core/cli/dispatch/tasks.py",
])
def test_shared_task_and_parser_changes_keep_broad_existing_consumers(path):
    plan = build_changed_verification_plan([path], repo_root=Path(__file__).resolve().parents[1])
    assert "local_task_control" in {owner["owner_id"] for owner in plan["owners"]}
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert {"tests/test_task_groups.py", "tests/test_task_papers.py",
            "tests/test_task_recovery.py", "tests/test_task_column_mapping.py",
            "tests/test_task_source_control.py", "tests/test_task_saved_work.py",
            "tests/test_task_paper_selection.py", "tests/test_task_paper_publication.py"} <= set(command)


@pytest.mark.parametrize("path", ["src/sciplot_core/plot_engine/recovery.py", "tests/test_plot_recovery.py"])
def test_recovery_source_and_generated_contracts_keep_semantic_engine_consumers(path):
    plan = build_changed_verification_plan([path], repo_root=Path(__file__).resolve().parents[1])
    assert not plan["unowned_paths"]
    assert "semantic_plot_engine" in {owner["owner_id"] for owner in plan["owners"]}
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert {"tests/test_plot_recovery.py", "tests/test_plot_protocol.py",
            "tests/test_plot_typed_intent_recovery.py", "tests/test_plot_protocol_native.py"} <= set(command)
    assert "full_pytest" in plan["required_later"]["release"]


def test_mcp_adapter_retains_new_public_recovery_schema_and_forwarding_contract():
    plan = build_changed_verification_plan(["src/sciplot_core/mcp_server/schemas.py"],
                                           repo_root=Path(__file__).resolve().parents[1])
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert {"tests/test_mcp_server.py", "tests/test_plot_protocol.py"} <= set(command)
