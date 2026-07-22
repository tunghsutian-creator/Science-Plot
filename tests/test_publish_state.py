from __future__ import annotations

from copy import deepcopy

import pytest

from sciplot_core.publish_state import build_publish_state


def _passed_records() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    return (
        {"status": "passed"},
        {"complete": True},
        {"complete": True},
    )


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
        ({"package_contract": {"complete": False}}, "package_contract_complete"),
        ({"delivery_package": {"complete": "true"}}, "delivery_package_complete"),
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

    result = build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        prerequisite_state="needs_human_confirmation",
    )

    assert result["state"] == "needs_human_confirmation"
    assert result["ready_to_use"] is False
    assert result["publish_gates"]["failed_gates"] == [
        "prerequisite_state_ready"
    ]


def test_publish_state_is_pure() -> None:
    qa, package, delivery = _passed_records()
    verification = {"passed": True, "issues": []}
    before = deepcopy((qa, package, delivery, verification))

    build_publish_state(
        qa=qa,
        package_contract=package,
        delivery_package=delivery,
        delivery_verification=verification,
    )

    assert (qa, package, delivery, verification) == before
