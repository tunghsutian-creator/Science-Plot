from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from sciplot_core.autoplot.publish_integrity import _manifest_publish_integrity
from sciplot_core.figure_plan import FigureOutcome, FigureTask, ResolvedFigurePlan


pytestmark = pytest.mark.focused


def _publish_report(
    *,
    ready: bool = True,
    plan_complete: bool | None = None,
) -> dict[str, Any]:
    gates = {
        "qa_passed": True,
        "package_contract_complete": True,
        "delivery_package_complete": True,
        "prerequisite_state_ready": True,
    }
    if plan_complete is not None:
        gates["resolved_figure_plan_complete"] = plan_complete
    failed_gates = [gate_id for gate_id, passed in gates.items() if not passed]
    return {
        "kind": "sciplot_publish_gate_report",
        "version": 1,
        "status": "passed" if ready else "failed",
        "passed": ready,
        "gates": gates,
        "failed_gates": failed_gates,
    }


def _ready_manifest() -> dict[str, Any]:
    return {
        "one_step": {"state": "ready"},
        "qa": {"status": "passed"},
        "package_contract": {"complete": True},
        "delivery_package": {"complete": True},
        "state": "ready",
        "ready_to_use": True,
        "publish_gates": _publish_report(),
    }


def _complete_plan_payload() -> dict[str, Any]:
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="x",
        y_metric="y",
        template="point_line",
        artifact_stem="figure_a",
        document_stem="figure_a",
    )
    return ResolvedFigurePlan(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
        outcomes=(
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=(
                    "figure_a.vsz",
                    "figure_a.pdf",
                    "figure_a_300dpi.tiff",
                ),
            ),
        ),
    ).to_payload()


def _all_checks(**changes: bool) -> dict[str, bool]:
    checks = {
        "state_recorded": True,
        "ready_to_use_recorded": True,
        "state_matches_gates": True,
        "ready_to_use_matches_gates": True,
        "publish_gates_match": True,
    }
    checks.update(changes)
    return checks


def test_canonical_publish_integrity_is_exact_and_input_pure() -> None:
    manifest = _ready_manifest()
    before = deepcopy(manifest)

    integrity = _manifest_publish_integrity(manifest)

    assert integrity == {
        "valid": True,
        "checks": _all_checks(),
        "recorded_state": "ready",
        "recorded_ready_to_use": True,
        "recorded_publish_gates": _publish_report(),
        "expected": {
            "state": "ready",
            "ready_to_use": True,
            "publish_gates": _publish_report(),
        },
        "package_contract_complete": True,
    }
    assert manifest == before


@pytest.mark.parametrize(
    ("field", "forged", "failed_check"),
    [
        ("state", "needs_rule_repair", "state_matches_gates"),
        ("ready_to_use", False, "ready_to_use_matches_gates"),
        ("publish_gates", {"forged": True}, "publish_gates_match"),
    ],
)
def test_each_recorded_projection_is_checked_independently(
    field: str,
    forged: object,
    failed_check: str,
) -> None:
    manifest = _ready_manifest()
    manifest[field] = forged

    integrity = _manifest_publish_integrity(manifest)

    expected_checks = _all_checks(**{failed_check: False})
    assert integrity["valid"] is False
    assert integrity["checks"] == expected_checks


@pytest.mark.parametrize(
    ("field", "failed_checks", "failed_gates", "package_complete"),
    [
        ("one_step", {"publish_gates_match"}, [], True),
        (
            "qa",
            {
                "state_matches_gates",
                "ready_to_use_matches_gates",
                "publish_gates_match",
            },
            ["qa_passed"],
            True,
        ),
        (
            "package_contract",
            {
                "state_matches_gates",
                "ready_to_use_matches_gates",
                "publish_gates_match",
            },
            ["package_contract_complete"],
            False,
        ),
        (
            "delivery_package",
            {
                "state_matches_gates",
                "ready_to_use_matches_gates",
                "publish_gates_match",
            },
            ["delivery_package_complete"],
            True,
        ),
        ("publish_gates", {"publish_gates_match"}, [], True),
    ],
)
def test_malformed_nested_records_fail_only_their_owned_checks(
    field: str,
    failed_checks: set[str],
    failed_gates: list[str],
    package_complete: bool,
) -> None:
    manifest = _ready_manifest()
    manifest[field] = []

    integrity = _manifest_publish_integrity(manifest)

    expected_checks = _all_checks(
        **{check: False for check in failed_checks},
    )
    assert integrity["valid"] is False
    assert integrity["checks"] == expected_checks
    assert integrity["expected"]["publish_gates"]["failed_gates"] == failed_gates
    assert integrity["package_contract_complete"] is package_complete


def test_non_boolean_ready_state_is_not_truthiness_coerced() -> None:
    manifest = _ready_manifest()
    manifest["ready_to_use"] = 1

    integrity = _manifest_publish_integrity(manifest)

    assert integrity["valid"] is False
    assert integrity["checks"] == _all_checks(
        ready_to_use_recorded=False,
        ready_to_use_matches_gates=False,
    )
    assert integrity["recorded_ready_to_use"] == 1


def test_absent_and_complete_figure_plans_have_exact_gate_shapes() -> None:
    absent = _manifest_publish_integrity(_ready_manifest())
    complete_manifest = _ready_manifest()
    complete_manifest["resolved_figure_plan"] = _complete_plan_payload()
    complete_manifest["publish_gates"] = _publish_report(plan_complete=True)

    complete = _manifest_publish_integrity(complete_manifest)

    assert absent["valid"] is True
    assert "resolved_figure_plan_complete" not in absent["expected"][
        "publish_gates"
    ]["gates"]
    assert complete["valid"] is True
    assert complete["expected"]["publish_gates"]["gates"][
        "resolved_figure_plan_complete"
    ] is True


def test_malformed_figure_plan_has_one_exact_failed_gate() -> None:
    manifest = _ready_manifest()
    manifest["resolved_figure_plan"] = {"kind": "not_a_figure_plan"}
    manifest["state"] = "needs_rule_repair"
    manifest["ready_to_use"] = False
    manifest["publish_gates"] = _publish_report(
        ready=False,
        plan_complete=False,
    )

    integrity = _manifest_publish_integrity(manifest)

    assert integrity["valid"] is True
    assert integrity["checks"] == _all_checks()
    assert integrity["expected"]["state"] == "needs_rule_repair"
    assert integrity["expected"]["ready_to_use"] is False
    assert integrity["expected"]["publish_gates"]["failed_gates"] == [
        "resolved_figure_plan_complete"
    ]
