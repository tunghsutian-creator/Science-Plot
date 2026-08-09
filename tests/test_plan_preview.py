from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.plan_preview as preview_module
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    FigureTask,
    ResolvedFigurePlan,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.mechanical_figure_contract import (
    mechanical_figure_contract,
    mechanical_selection_policy,
)


def test_plan_preview_activates_registered_real_tensile_plan() -> None:
    rule_id = "tensile_curve"
    source = resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))
    contract = mechanical_figure_contract(rule_id)

    payload = preview_module.build_plan_preview(
        source,
        request={"rule_id": rule_id, "template": "curve"},
    )

    assert payload["status"] == "planned"
    assert payload["blocker"] is None
    plan = payload["resolved_figure_plan"]
    assert plan is not None
    assert plan["rule_id"] == rule_id
    assert plan["selection_policy"] == mechanical_selection_policy(
        "representative"
    )
    assert plan["selected_figure_ids"] == [
        task.figure_id for task in contract.tasks
    ]
    assert [task["sample_order"] for task in plan["tasks"]] == [
        ["E0 2MM"] for _task in contract.tasks
    ]
    assert [task["replicate_counts"] for task in plan["tasks"]] == [
        [{"sample": "E0 2MM", "count": 9}] for _task in contract.tasks
    ]
    assert plan["status"] == "planned"
    assert plan["complete"] is False
    assert [outcome["status"] for outcome in plan["outcomes"]] == [
        "pending" for _task in contract.tasks
    ]
    assert all(not outcome["artifacts"] for outcome in plan["outcomes"])


def test_plan_preview_returns_one_complete_planned_payload_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mechanical"
    request: dict[str, Any] = {
        "rule_id": "tensile_curve",
        "template": "curve",
        "series_order": ["sample_b", "sample_a"],
    }
    request_before = deepcopy(request)
    semantic = {
        "rule_id": "tensile_curve",
        "semantic_family": "tensile_test",
        "template": "curve",
    }
    study_model = {"kind": "sciplot_study_model", "figure_queue": []}
    plan = _two_task_plan()
    captured: dict[str, object] = {}

    def fake_classify(
        input_path: Path,
        *,
        requested_rule_id: str | None,
    ) -> dict[str, Any]:
        captured["classified_source"] = input_path
        captured["requested_rule_id"] = requested_rule_id
        return semantic

    def fake_study_model(
        *,
        request: dict[str, Any],
        semantic: dict[str, Any],
        input_path: Path,
    ) -> dict[str, Any]:
        captured["study_request"] = request
        captured["study_semantic"] = semantic
        captured["study_source"] = input_path
        return study_model

    def fake_resolve(**kwargs: Any) -> ResolvedFigurePlan:
        captured["resolver"] = kwargs
        return plan

    monkeypatch.setattr(preview_module, "classify_source", fake_classify)
    monkeypatch.setattr(preview_module, "study_model_from_request", fake_study_model)
    monkeypatch.setattr(preview_module, "resolve_figure_plan", fake_resolve)

    payload = preview_module.build_plan_preview(source, request=request)

    resolved_source = source.resolve()
    assert request == request_before
    assert captured["classified_source"] == resolved_source
    assert captured["requested_rule_id"] == "tensile_curve"
    assert captured["study_request"] == request
    assert captured["study_request"] is not request
    assert captured["study_semantic"] is semantic
    assert captured["study_source"] == resolved_source
    assert captured["resolver"] == {
        "rule_id": "tensile_curve",
        "template": "curve",
        "study_model": study_model,
        "input_path": resolved_source,
        "request": captured["study_request"],
    }
    assert payload == {
        "kind": "sciplot_figure_plan_preview",
        "version": 1,
        "status": "planned",
        "source": str(resolved_source),
        "rule_id": "tensile_curve",
        "template": "curve",
        "resolved_figure_plan": plan.to_payload(),
        "blocker": None,
    }


def test_plan_preview_marks_non_figure_plan_source_not_applicable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "generic.csv"
    monkeypatch.setattr(
        preview_module,
        "classify_source",
        lambda *_args, **_kwargs: {
            "semantic_family": "generic_curve",
            "template": "curve",
        },
    )
    monkeypatch.setattr(
        preview_module,
        "study_model_from_request",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        preview_module,
        "resolve_figure_plan",
        lambda **_kwargs: None,
    )

    payload = preview_module.build_plan_preview(source, request={})

    assert payload["status"] == "not_applicable"
    assert payload["rule_id"] is None
    assert payload["template"] == "curve"
    assert payload["resolved_figure_plan"] is None
    assert payload["blocker"] is None


def test_plan_preview_projects_one_known_resolution_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mechanical"
    monkeypatch.setattr(
        preview_module,
        "classify_source",
        lambda *_args, **_kwargs: {
            "rule_id": "tensile_curve",
            "semantic_family": "tensile_test",
            "template": "curve",
        },
    )
    monkeypatch.setattr(
        preview_module,
        "study_model_from_request",
        lambda **_kwargs: {},
    )

    def blocked_resolver(**_kwargs: Any) -> None:
        raise FigurePlanResolutionError(
            "mechanical_source_facts_unavailable",
            "Mechanical source facts are unavailable.",
        )

    monkeypatch.setattr(preview_module, "resolve_figure_plan", blocked_resolver)

    payload = preview_module.build_plan_preview(
        source,
        request={"rule_id": "tensile_curve", "template": "curve"},
    )

    assert payload["status"] == "blocked"
    assert payload["resolved_figure_plan"] is None
    assert payload["blocker"] == {
        "reason_code": "mechanical_source_facts_unavailable",
        "message": "Mechanical source facts are unavailable.",
    }


def _two_task_plan() -> ResolvedFigurePlan:
    tasks = (
        FigureTask(
            figure_id="stress_vs_strain",
            order=1,
            title="Stress vs Strain",
            x_metric="strain",
            y_metric="stress",
            template="curve",
            artifact_stem="stress_vs_strain",
            document_stem="stress_vs_strain",
        ),
        FigureTask(
            figure_id="strength",
            order=2,
            title="Tensile Strength",
            x_metric="sample",
            y_metric="strength_MPa",
            template="box_strip",
            artifact_stem="strength",
            document_stem="strength",
        ),
    )
    return ResolvedFigurePlan.planned(
        rule_id="tensile_curve",
        selection_policy="fixture",
        primary_figure_id="stress_vs_strain",
        tasks=tasks,
        source_sha256="a" * 64,
    )
