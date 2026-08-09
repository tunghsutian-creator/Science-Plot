from __future__ import annotations

from sciplot_core.intake.catalog import intake_catalog_payload


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
    assert all("template" not in item for item in experiments.values())
