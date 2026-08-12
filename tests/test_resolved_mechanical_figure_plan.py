from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigurePlanResolutionError,
    ResolvedFigurePlan,
    REQUIRED_FIGURE_PLAN_RULE_IDS,
    resolve_figure_plan,
    source_tree_sha256,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.mechanical_figure_contract import (
    MECHANICAL_QUARTILE_METHOD,
    MECHANICAL_RULE_IDS,
    MECHANICAL_STATISTICS_METHOD_ID,
    mechanical_figure_contract,
    mechanical_selection_policy,
)
from sciplot_core.study_model import experiment_recommendation_payload


EXPECTED_REAL_SOURCE_FACTS = {
    "tensile_curve": (
        ("E0 2MM",),
        (("E0 2MM", 9),),
        (
            "stress_vs_strain",
            "tensile_strength_by_sample",
            "elongation_at_break_by_sample",
            "tensile_modulus_by_sample",
            "toughness_by_sample",
        ),
    ),
    "compression_curve": (
        ("Conventional PU foam",),
        (("Conventional PU foam", 6),),
        (
            "compressive_stress_vs_strain",
            "compressive_strength_by_sample",
        ),
    ),
    "flexural_curve": (
        ("A_HA56",),
        (("A_HA56", 6),),
        (
            "flexural_stress_vs_strain",
            "flexural_strength_by_sample",
        ),
    ),
}


def _fixture(rule_id: str) -> Path:
    source = resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))
    assert source.exists()
    return source


def _resolve(
    rule_id: str,
    *,
    replicate_mode: str | None = None,
    study_model: dict[str, object] | None = None,
) -> ResolvedFigurePlan:
    request: dict[str, object] = {"template": "curve"}
    if replicate_mode is not None:
        request["replicate_mode"] = replicate_mode
    plan = resolve_figure_plan(
        rule_id=rule_id,
        template="curve",
        study_model=(
            experiment_recommendation_payload(rule_id=rule_id)
            if study_model is None
            else study_model
        ),
        input_path=_fixture(rule_id),
        request=request,
    )
    assert plan is not None
    return plan


def test_study_model_and_runtime_share_the_complete_mechanical_contract() -> None:
    assert MECHANICAL_RULE_IDS <= REQUIRED_FIGURE_PLAN_RULE_IDS
    for rule_id in sorted(MECHANICAL_RULE_IDS):
        contract = mechanical_figure_contract(rule_id)
        recommendation = experiment_recommendation_payload(rule_id=rule_id)

        assert recommendation["default_replicate_mode"] == "representative"
        assert recommendation["figure_queue"] == [
            task.study_model_payload() for task in contract.tasks
        ]
        assert contract.primary_task.template == "curve"
        assert all(task.template == "box_strip" for task in contract.summary_tasks)
        assert len({task.artifact_stem for task in contract.tasks}) == len(
            contract.tasks
        )
        assert len({task.document_stem for task in contract.tasks}) == len(
            contract.tasks
        )
        for task in contract.summary_tasks:
            method = task.statistics_method
            assert method is not None
            assert method["method_id"] == MECHANICAL_STATISTICS_METHOD_ID
            assert method["center"] == "median"
            assert method["spread_or_interval"] == "interquartile range"
            assert method["test"] == "none"
            assert method["parameters"] == {
                "raw_points_visible": True,
                "quartile_method": MECHANICAL_QUARTILE_METHOD,
                "box_whisker_mode": "1.5IQR",
            }


@pytest.mark.parametrize("rule_id", sorted(MECHANICAL_RULE_IDS))
def test_real_mechanical_source_resolves_exact_ordered_v2_tasks(
    rule_id: str,
) -> None:
    expected_samples, expected_counts, expected_ids = EXPECTED_REAL_SOURCE_FACTS[
        rule_id
    ]
    contract = mechanical_figure_contract(rule_id)

    plan = _resolve(rule_id)

    assert plan.rule_id == rule_id
    assert plan.selection_policy == mechanical_selection_policy("representative")
    assert plan.primary_figure_id == contract.primary_task.figure_id
    assert plan.selected_figure_ids == expected_ids
    assert plan.source_sha256 == source_tree_sha256(_fixture(rule_id))
    assert tuple(task.order for task in plan.tasks) == tuple(
        range(1, len(expected_ids) + 1)
    )
    assert all(task.to_payload()["version"] == 2 for task in plan.tasks)
    assert all(task.sample_order == expected_samples for task in plan.tasks)
    assert all(task.replicate_counts == expected_counts for task in plan.tasks)
    for task, task_contract in zip(plan.tasks, contract.tasks, strict=True):
        assert task.metric_binding == CartesianMetricBinding(
            x_metric=task_contract.x_metric,
            y_metric=task_contract.y_metric,
        )
        assert task.template == task_contract.template
        assert task.artifact_stem == task_contract.artifact_stem
        assert task.document_stem == task_contract.document_stem
    assert ResolvedFigurePlan.from_payload(plan.to_payload()) == plan


def test_individual_mode_changes_only_curve_series_identity() -> None:
    plan = _resolve("compression_curve", replicate_mode="individual")
    curve, summary = plan.tasks

    assert plan.selection_policy == mechanical_selection_policy("individual")
    assert curve.sample_order == tuple(
        f"Conventional PU foam__repeat {index}" for index in range(2, 8)
    )
    assert curve.replicate_counts == tuple((sample, 1) for sample in curve.sample_order)
    assert summary.sample_order == ("Conventional PU foam",)
    assert summary.replicate_counts == (("Conventional PU foam", 6),)


def test_mean_curve_mode_fails_before_source_resolution(tmp_path: Path) -> None:
    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_figure_plan(
            rule_id="tensile_curve",
            template="curve",
            study_model={},
            input_path=tmp_path / "absent",
            request={"template": "curve", "replicate_mode": "mean"},
        )

    assert exc_info.value.reason_code == "mechanical_mean_curve_unsupported"


def test_study_model_contract_conflict_fails_before_source_resolution(
    tmp_path: Path,
) -> None:
    recommendation = experiment_recommendation_payload(rule_id="tensile_curve")
    recommendation["figure_queue"][1]["default_template"] = "bar"

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_figure_plan(
            rule_id="tensile_curve",
            template="curve",
            study_model=recommendation,
            input_path=tmp_path / "absent",
            request={"template": "curve"},
        )

    assert exc_info.value.reason_code == "mechanical_study_model_queue_mismatch"


def test_mechanical_source_error_reason_is_preserved(tmp_path: Path) -> None:
    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_figure_plan(
            rule_id="flexural_curve",
            template="curve",
            study_model={},
            input_path=tmp_path / "absent",
            request={"template": "curve"},
        )

    assert exc_info.value.reason_code == "mechanical_source_unavailable"


def test_mechanical_primary_template_cannot_override_summary_contract() -> None:
    with pytest.raises(FigurePlanResolutionError) as exc_info:
        resolve_figure_plan(
            rule_id="compression_curve",
            template="box_strip",
            study_model={},
            input_path=_fixture("compression_curve"),
            request={"template": "box_strip"},
        )

    assert exc_info.value.reason_code == "mechanical_template_invalid"
