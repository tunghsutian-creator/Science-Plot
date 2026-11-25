"""Select exact public nodes and verify actual execution reports."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest


TARGETED_SCOPES = {"public-affected": "public-focused", "public-affected-native": "public-comprehensive"}


def target_modules(targets: Sequence[str]) -> frozenset[str]:
    return frozenset(target.split("::", 1)[0] for target in targets)


def match_targets(nodes: Iterable[str], targets: Sequence[str]) -> set[str]:
    """A function selector includes its parameters, not similarly named functions."""
    selected: set[str] = set()
    candidates: dict[str, list[str]] = {}
    for node in nodes:
        candidates.setdefault(node.split("::", 1)[0], []).append(node)
    for target in targets:
        module = target.split("::", 1)[0]
        matches = {node for node in candidates.get(module, ())
                   if node == target or node.startswith((target + "::", target + "["))}
        if not matches:
            raise ValueError("Affected selector must bind a current tracked test in its public tier.")
        selected.update(matches)
    return selected


def selected_public_nodes(manifest: dict[str, Any], source: dict[str, str], profile: str, targets: list[str] | None) -> set[str]:
    scope = TARGETED_SCOPES.get(profile, profile)
    expected = set(manifest["scopes"]["public"])
    if scope != "public-all":
        expected.intersection_update(manifest["tiers"][scope.removeprefix("public-")])
    if targets is None:
        return expected
    if any(not filename.startswith("tests/") or filename not in source for filename in target_modules(targets)):
        raise ValueError("Affected selector must bind a current tracked test in its public tier.")
    return match_targets(expected, targets)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--sciplot-public-target", action="append", default=[],
                     help="Exact public feedback selectors admitted against complete collection of their test modules.")


PLATFORM_SKIPS = {
    "tests/test_macos_distribution.py::test_build_refuses_existing_output_before_copying": ("call", "Skipped: macOS builder"),
    "tests/test_verification_evidence_runtime.py::test_runtime_keeps_logical_roots_and_missing_enabled_usersite": ("setup", "Skipped: default runtime policy binds the actual macOS build"),
    "tests/test_verification_evidence_runtime.py::test_relative_runtime_environment_binds_real_child_inputs": ("setup", "Skipped: default runtime policy binds the actual macOS build"),
    "tests/test_private_observer_native.py::test_actual_mac_qt_reexec_is_sealed_and_continued": ("call", "Skipped: The actual Qt framework reexec path belongs to macOS."),
    "tests/test_native_probe_boundary.py::test_actual_clt_inspector_uses_closed_environment_and_bound_native_target": ("setup", "Skipped: finite CLT inspector is macOS-specific"),
    'tests/test_process_private_exclusion_generated.py::test_actual_close_fds_and_devnull_do_not_inherit_generated_raw_descriptor': ("setup", "Skipped: Actual Mac process boundary control"),
    'tests/test_process_private_exclusion_generated.py::test_actual_nonzero_and_signal_outcomes_are_retained[import os,signal;os.kill(os.getpid(),signal.SIGTERM)--15]': ("setup", "Skipped: Actual Mac process boundary control"),
    'tests/test_process_private_exclusion_generated.py::test_actual_nonzero_and_signal_outcomes_are_retained[import os;os._exit(79)-79]': ("setup", "Skipped: Actual Mac process boundary control"),
    'tests/test_process_private_exclusion_generated.py::test_actual_pipe_protocol_and_post_kernel_environment_projection': ("setup", "Skipped: Actual Mac process boundary control"),
    'tests/test_process_private_exclusion_generated.py::test_actual_strong_boundary_blocks_namespace_alias_and_evidence_mutations': ("setup", "Skipped: Actual Mac process boundary control"),
    'tests/test_process_private_exclusion_generated.py::test_pinned_interpreter_loader_environment_is_preserved': ("setup", "Skipped: Actual Mac process boundary control"),
    "tests/test_process_private_exclusion_generated.py::test_actual_same_launch_composition_preserves_two_finite_socket_endpoints": ("setup", "Skipped: Actual Mac process boundary control"),
    "tests/test_native_exit_boundary.py::test_late_and_wrong_identity_do_not_register": ("setup", "Skipped: Darwin public kqueue/libproc capability"),
    "tests/test_native_exit_boundary.py::test_missing_event_and_closed_watcher_remain_unknown": ("setup", "Skipped: Darwin public kqueue/libproc capability"),
    "tests/test_native_exit_boundary.py::test_real_nonparent_status_matches_original_parent_wait[0-0-0]": ("setup", "Skipped: Darwin public kqueue/libproc capability"),
    "tests/test_native_exit_boundary.py::test_real_nonparent_status_matches_original_parent_wait[79-20224-79]": ("setup", "Skipped: Darwin public kqueue/libproc capability"),
    "tests/test_native_exit_boundary.py::test_real_nonparent_status_matches_original_parent_wait[sigterm-15--15]": ("setup", "Skipped: Darwin public kqueue/libproc capability"),
}
_reports: list[dict[str, Any]] = []


def review_stage_reports(marker: dict[str, Any], reports: dict[str, Any], *, platform: str) -> list[str]:
    """Every selected node needs actual successful reports or an exact OS skip."""
    selected = marker.get("selected_tests")
    if (marker.get("complete") is not True or marker.get("exit_code") != 0 or not isinstance(selected, list)
            or not selected or not all(isinstance(node, str) for node in selected)
            or len(selected) != len(set(selected)) or reports.get("selected_tests") != selected
            or reports.get("exit_code") != 0):
        return ["Actual public stage session finish is absent, incomplete or mismatched."]
    rows = reports.get("reports")
    if not isinstance(rows, list):
        return ["Unknown public stage report scope."]
    by_node: dict[str, list[dict[str, Any]]] = {node: [] for node in selected}
    passed: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("when") not in ("setup", "call", "teardown"):
            return ["Unknown public stage report scope."]
        node = row.get("nodeid")
        if not isinstance(node, str) or node not in by_node:
            return ["Unknown public stage report scope."]
        by_node[node].append(row)
        if row["when"] == "call" and row.get("outcome") == "passed":
            passed.append(node)
    passed_nodes = set(passed)
    if passed != marker.get("executed_tests") or len(passed) != len(passed_nodes):
        return ["Actual public call reports differ from successful body finish."]
    for node, actual in by_node.items():
        setup = [row for row in actual if row.get("when") == "setup"]
        call = [row for row in actual if row.get("when") == "call"]
        teardown = [row for row in actual if row.get("when") == "teardown"]
        skips = [row for row in actual if row.get("outcome") == "skipped"]
        if (len(setup) != 1 or len(teardown) != 1 or teardown[0].get("outcome") != "passed"
                or any(row.get("outcome") not in {"passed", "skipped"} for row in actual)):
            return ["Public stage setup/teardown/failure reports are incomplete."]
        if skips:
            expected = PLATFORM_SKIPS.get(node) if platform != "darwin" else None
            if (len(skips) != 1 or expected != (skips[0].get("when"), skips[0].get("skip_reason"))
                    or len(call) != (1 if skips[0].get("when") == "call" else 0)):
                return ["Unexpected public stage skip or omitted body."]
        elif len(call) != 1 or node not in passed_nodes or setup[0].get("outcome") != "passed":
            return ["A selected public body did not execute successfully."]
    return []


def reset_reports(session: Any) -> None:
    _reports.clear()


def record_report(report: Any) -> None:
    reason = str(report.longrepr[2]) if report.skipped and isinstance(report.longrepr, tuple) else None
    _reports.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome, "skip_reason": reason})


def write_reports(session: Any, exitstatus: Any) -> None:
    from sciplot_core.verification.evidence import atomic_json

    destination = os.environ.get("SCIPLOT_PUBLIC_STAGE_REPORT")
    if destination:
        atomic_json(Path(destination), {"selected_tests": [item.nodeid for item in session.items],
                                        "exit_code": int(exitstatus), "reports": list(_reports)})
