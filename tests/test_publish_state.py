from __future__ import annotations

from copy import deepcopy

import pytest

from sciplot_core.figure_plan import FigureOutcome, FigureTask, ResolvedFigurePlan
from sciplot_core.publish_state import build_publish_state


def _passed_records() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return (
        {"status": "passed"},
        {"complete": True},
        {"complete": True},
    )


def _figure_plan_payload(*, complete: bool) -> dict[str, object]:
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
    outcome = FigureOutcome(
        figure_id=task.figure_id,
        status="ready" if complete else "pending",
        artifacts=(
            ("figure_a.vsz", "figure_a.pdf", "figure_a_300dpi.tiff") if complete else ()
        ),
    )
    return ResolvedFigurePlan(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
        outcomes=(outcome,),
    ).to_payload()


def test_publish_state_requires_the_same_core_gates_for_workflow() -> None:
    qa, package, delivery = _passed_records()

    result = build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        prerequisite_state="ready",
    )

    assert result["state"] == "ready"
    assert result["ready_to_use"] is True
    assert result["publish_gates"] == {
        "kind": "sciplot_publish_gate_report",
        "version": 1,
        "status": "passed",
        "passed": True,
        "gates": {
            "qa_passed": True,
            "package_contract_complete": True,
            "delivery_package_complete": True,
            "prerequisite_state_ready": True,
        },
        "failed_gates": [],
    }


def test_publish_state_adds_exact_current_verification_for_studio() -> None:
    qa, package, delivery = _passed_records()

    result = build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        delivery_verification={"passed": True},
    )

    assert result["state"] == "ready"
    assert result["ready_to_use"] is True
    assert result["publish_gates"]["gates"]["delivery_verification_passed"] is True


@pytest.mark.parametrize(
    ("overrides", "failed_gate"),
    [
        ({"qa": {"status": "failed"}}, "qa_passed"),
        ({"qa": None}, "qa_passed"),
        ({"package_contract": {"complete": False}}, "package_contract_complete"),
        ({"package_contract": None}, "package_contract_complete"),
        ({"delivery_package": {"complete": "true"}}, "delivery_package_complete"),
        ({"delivery_package": None}, "delivery_package_complete"),
        (
            {"delivery_verification": {"passed": "true"}},
            "delivery_verification_passed",
        ),
    ],
)
def test_publish_state_fails_closed_on_missing_or_non_boolean_gates(
    overrides: dict[str, object],
    failed_gate: str,
) -> None:
    qa, package, delivery = _passed_records()
    arguments: dict[str, object] = {
        "qa": qa,
        "package_contract": package,
        "delivery_package": delivery,
        "delivery_verification": {"passed": True},
    }
    arguments.update(overrides)

    result = build_publish_state(**arguments)

    assert result["state"] == "needs_rule_repair"
    assert result["ready_to_use"] is False
    assert failed_gate in result["publish_gates"]["failed_gates"]


def test_publish_state_preserves_a_scientific_confirmation_blocker() -> None:
    qa, package, delivery = _passed_records()
    qa["status"] = "failed"

    result = build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        prerequisite_state="needs_human_confirmation",
    )

    assert result["state"] == "needs_human_confirmation"
    assert result["ready_to_use"] is False
    assert result["publish_gates"]["failed_gates"] == [
        "qa_passed",
        "prerequisite_state_ready",
    ]


@pytest.mark.parametrize(
    "prerequisite_state",
    ["needs_rule_repair", "unknown_state", []],
)
def test_publish_state_preserves_rule_repair_and_fails_unknown_states_closed(
    prerequisite_state: object,
) -> None:
    qa, package, delivery = _passed_records()

    result = build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        prerequisite_state=prerequisite_state,
    )

    assert result["state"] == "needs_rule_repair"
    assert result["ready_to_use"] is False
    assert result["publish_gates"]["failed_gates"] == ["prerequisite_state_ready"]


def test_publish_state_does_not_restore_ready_when_another_gate_fails() -> None:
    _qa, package, delivery = _passed_records()

    result = build_publish_state(
        qa={"status": "failed"},
        package_contract=package,
        delivery_package=delivery,
        prerequisite_state="ready",
    )

    assert result["state"] == "needs_rule_repair"
    assert result["ready_to_use"] is False
    assert result["publish_gates"]["failed_gates"] == ["qa_passed"]


@pytest.mark.parametrize(
    ("plan_case", "expected_gate", "expected_state"),
    [
        ("absent", None, "ready"),
        ("complete", True, "ready"),
        ("incomplete", False, "needs_rule_repair"),
        ("malformed", False, "needs_rule_repair"),
    ],
)
def test_publish_state_handles_each_optional_figure_plan_state(
    plan_case: str,
    expected_gate: bool | None,
    expected_state: str,
) -> None:
    qa, package, delivery = _passed_records()
    if plan_case == "absent":
        plan: object | None = None
    elif plan_case == "malformed":
        plan = {"kind": "not_a_resolved_figure_plan"}
    else:
        plan = _figure_plan_payload(complete=plan_case == "complete")

    result = build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        resolved_figure_plan=plan,
    )

    gates = result["publish_gates"]["gates"]
    if expected_gate is None:
        assert "resolved_figure_plan_complete" not in gates
    else:
        assert gates["resolved_figure_plan_complete"] is expected_gate
    assert result["state"] == expected_state
    assert result["ready_to_use"] is (expected_state == "ready")


def test_publish_state_preserves_exact_gate_order() -> None:
    qa, package, delivery = _passed_records()

    result = build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        delivery_verification={"passed": True},
        prerequisite_state="ready",
        resolved_figure_plan=_figure_plan_payload(complete=True),
    )

    assert list(result["publish_gates"]["gates"]) == [
        "qa_passed",
        "package_contract_complete",
        "delivery_package_complete",
        "delivery_verification_passed",
        "prerequisite_state_ready",
        "resolved_figure_plan_complete",
    ]
    assert result["publish_gates"]["failed_gates"] == []


def test_publish_state_preserves_failed_gate_order_for_malformed_inputs() -> None:
    result = build_publish_state(
        qa=None,
        package_contract=[],
        delivery_package="missing",
        delivery_verification={"passed": "true"},
        prerequisite_state="unknown_state",
        resolved_figure_plan={"kind": "not_a_resolved_figure_plan"},
    )

    assert result["state"] == "needs_rule_repair"
    assert result["publish_gates"]["failed_gates"] == [
        "qa_passed",
        "package_contract_complete",
        "delivery_package_complete",
        "delivery_verification_passed",
        "prerequisite_state_ready",
        "resolved_figure_plan_complete",
    ]


def test_publish_state_is_pure() -> None:
    qa, package, delivery = _passed_records()
    verification = {"passed": True, "issues": []}
    plan = _figure_plan_payload(complete=True)
    before = deepcopy((qa, package, delivery, verification, plan))

    build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        delivery_verification=verification,
        resolved_figure_plan=plan,
    )

    assert (qa, package, delivery, verification, plan) == before
