"""Ancestor reduction retains the same pytest selection without touching options."""
from __future__ import annotations

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
