from __future__ import annotations

import pytest

import sciplot_core.intake.catalog as intake_catalog
from sciplot_core.intake.catalog import (
    INTAKE_CATALOG,
    _catalog_item,
    _catalog_item_for_rule,
    intake_catalog_payload,
)
from sciplot_core.materials_rules import get_rule


def _experiment_payloads() -> list[dict[str, object]]:
    payload = intake_catalog_payload(include_pending=True)
    return [
        experiment
        for data_type in payload["data_types"]
        for experiment in data_type["experiments"]
    ]


def test_intake_selects_one_complete_figure_plan_per_mechanical_test() -> None:
    payload = intake_catalog_payload(include_pending=True)
    mechanical = next(
        item for item in payload["data_types"] if item["id"] == "mechanical"
    )
    experiments = {
        item["id"]: item
        for item in mechanical["experiments"]
        if item.get("rule_id")
        in {"tensile_curve", "compression_curve", "flexural_curve"}
    }

    assert tuple(experiments) == (
        "tensile_curve",
        "compression_curve",
        "flexural_curve",
    )
    assert {item["rule_id"] for item in experiments.values()} == {
        "tensile_curve",
        "compression_curve",
        "flexural_curve",
    }
    assert all(
        item["default_replicate_mode"] == "representative"
        for item in experiments.values()
    )
    assert all(item["template"] == "curve" for item in experiments.values())


def test_intake_catalog_projects_every_capability_from_its_semantic_rule() -> None:
    raw_experiments = [
        experiment
        for data_type in INTAKE_CATALOG
        for experiment in data_type["experiments"]
    ]
    assert all(
        set(experiment) <= {"id", "label", "rule_id", "unknown"}
        for experiment in raw_experiments
    )
    assert "torque_offset_stack" not in {
        str(experiment["id"]) for experiment in raw_experiments
    }

    projected = _experiment_payloads()
    mapped = [item for item in projected if item.get("rule_id")]
    assert len({item["rule_id"] for item in mapped}) == len(mapped)
    for item in mapped:
        rule = get_rule(str(item["rule_id"]))
        rule_payload = rule.to_payload()
        assert item["template"] == rule.template
        assert item["chart"] == rule.template
        assert item["presentation_contract"] == rule.presentation_contract_payload()
        assert item["render_options"] == rule.render_options
        assert item["default_replicate_mode"] == rule_payload[
            "experiment_recommendation"
        ]["default_replicate_mode"]

    _, internal_tensile = _catalog_item("mechanical", "tensile_curve")
    assert "render_options" not in internal_tensile
    assert internal_tensile["template"] == get_rule("tensile_curve").template


def test_intake_catalog_rejects_duplicate_rule_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = {
        "id": "duplicate",
        "label": "Duplicate",
        "icon": "unknown",
        "experiments": (
            {
                "id": "duplicate_torque",
                "label": "Duplicate torque",
                "rule_id": "torque_curve",
            },
        ),
    }
    monkeypatch.setattr(intake_catalog, "INTAKE_CATALOG", (*INTAKE_CATALOG, duplicate))

    with pytest.raises(ValueError, match="rule ids must be unique.*torque_curve"):
        intake_catalog_payload(include_pending=True)
    with pytest.raises(ValueError, match="rule ids must be unique.*torque_curve"):
        _catalog_item_for_rule("torque_curve")


def test_unknown_intake_navigation_remains_unprojected() -> None:
    data_type, experiment = _catalog_item("unknown", "unknown")

    assert data_type["id"] == "unknown"
    assert experiment == {"id": "unknown", "label": "未知", "rule_id": None}
    assert _catalog_item_for_rule(None) is None
