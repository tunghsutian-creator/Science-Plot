from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.studio_render as studio_render
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureOutcome,
    FigureTask,
    OrderedMetricsBinding,
    ResolvedFigurePlan,
)
from sciplot_core.source_coverage.terminal_requests import (
    _authoritative_terminal_render_requests,
)
from sciplot_core.figure_plan.terminal_binding import (
    BoundTerminalFigureEvidence,
    bind_terminal_figure_evidence,
)
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.terminal_request import (
    TERMINAL_RENDER_REQUEST_KIND,
    TERMINAL_RENDER_REQUEST_VERSION,
    normalize_terminal_render_request,
    project_terminal_render_request,
)
from sciplot_core.workflow import request_rendering
from sciplot_core.workflow.request_rendering import RequestRenderResult
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent


def _legacy_task(*, figure_id: str = "legacy_curve", order: int = 1) -> FigureTask:
    return FigureTask(
        figure_id=figure_id,
        order=order,
        title="Legacy curve",
        x_metric="time",
        y_metric="stress",
        template="curve",
        artifact_stem=figure_id,
        document_stem=figure_id,
    )


def _cartesian_v2_task(
    *,
    figure_id: str = "cartesian_curve",
    order: int = 1,
) -> FigureTask:
    return FigureTask.with_metric_binding(
        figure_id=figure_id,
        order=order,
        title="Cartesian curve",
        metric_binding=CartesianMetricBinding(
            x_metric="temperature",
            y_metric="storage_modulus",
        ),
        template="curve",
        artifact_stem=figure_id,
        document_stem=figure_id,
    )


def _ordered_task(
    *,
    figure_id: str = "ordered_polar",
    order: int = 2,
) -> FigureTask:
    return FigureTask.with_metric_binding(
        figure_id=figure_id,
        order=order,
        title="Ordered polar",
        metric_binding=OrderedMetricsBinding(
            metric_ids=("density", "impact_strength", "tensile_strength"),
        ),
        template="polar_curve",
        artifact_stem=figure_id,
        document_stem=figure_id,
    )


def _planned_two_task_plan() -> ResolvedFigurePlan:
    return ResolvedFigurePlan.planned(
        rule_id="performance_comparison",
        selection_policy="fixture_two_tasks",
        primary_figure_id="cartesian_curve",
        tasks=(
            _cartesian_v2_task(),
            _ordered_task(),
        ),
        source_sha256="a" * 64,
    )


def _completed_plan(plan: ResolvedFigurePlan) -> ResolvedFigurePlan:
    return ResolvedFigurePlan(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        outcomes=tuple(
            FigureOutcome(
                figure_id=task.figure_id,
                status="unavailable",
                reason_code="fixture_artifacts_unavailable",
                message="Fixture outcome.",
            )
            for task in plan.tasks
        ),
        source_sha256=plan.source_sha256,
    )


def _terminal_request(
    task: FigureTask,
    *,
    rule_id: str = "performance_comparison",
) -> dict[str, Any]:
    return project_terminal_render_request(
        template=task.template,
        render_options={"size": "60x55"},
        request_context={
            "rule_id": rule_id,
            "x_metric": "stale_x",
            "y_metric": "stale_y",
            "metric_ids": ["stale_metric"],
            "study_model": {
                "figure_queue": [
                    {
                        "x_metric": "first_queue_x",
                        "y_metric": "first_queue_y",
                    }
                ]
            },
            "resolved_figure_task": task.to_payload(),
        },
    )


def _completed_result(plan: ResolvedFigurePlan) -> dict[str, Any]:
    completed = _completed_plan(plan)
    return {
        "kind": "sciplot_render_result",
        "terminal_render_requests": [
            _terminal_request(task, rule_id=plan.rule_id) for task in plan.tasks
        ],
        "resolved_figure_plan": completed.to_payload(),
    }


def test_legacy_terminal_request_payload_remains_exact_and_unversioned() -> None:
    context = {
        "rule_id": "legacy_custom_rule",
        "study_model": {
            "figure_queue": [
                {
                    "x_metric": "queue_time",
                    "y_metric": "queue_stress",
                }
            ]
        },
    }
    before = deepcopy(context)

    terminal = project_terminal_render_request(
        template="curve",
        render_options={"size": "60x55"},
        request_context=context,
    )

    assert terminal == {
        "template": "curve",
        "render_options": {"size": "60x55"},
        "rule_id": "legacy_custom_rule",
        "x_metric": "queue_time",
        "y_metric": "queue_stress",
    }
    assert normalize_terminal_render_request(terminal, label="legacy") == terminal
    assert (
        canonical_json_sha256(terminal, allow_nan=False)
        == "9c0532f0b2d42d64f939c79b2b989ef4f52c6fe539eb7b4c6eb90901ee0b0ba6"
    )
    assert context == before


@pytest.mark.parametrize(
    "task",
    [
        _legacy_task(),
        _cartesian_v2_task(),
        _ordered_task(order=1),
    ],
)
def test_task_aware_terminal_request_v2_round_trips_exact_task(
    task: FigureTask,
) -> None:
    context = {
        "rule_id": "performance_comparison",
        "x_metric": "stale_x",
        "y_metric": "stale_y",
        "metric_ids": ["stale_metric"],
        "study_model": {
            "figure_queue": [
                {
                    "x_metric": "first_queue_x",
                    "y_metric": "first_queue_y",
                }
            ]
        },
        "resolved_figure_task": task.to_payload(),
    }
    before = deepcopy(context)

    terminal = project_terminal_render_request(
        template=task.template,
        render_options={"size": "60x55"},
        request_context=context,
    )

    assert terminal["kind"] == TERMINAL_RENDER_REQUEST_KIND
    assert terminal["version"] == TERMINAL_RENDER_REQUEST_VERSION
    assert terminal["resolved_figure_task"] == task.to_payload()
    if isinstance(task.metric_binding, OrderedMetricsBinding):
        assert terminal["metric_ids"] == list(task.metric_binding.metric_ids)
        assert "x_metric" not in terminal
        assert "y_metric" not in terminal
    else:
        expected_x = (
            task.metric_binding.x_metric
            if isinstance(task.metric_binding, CartesianMetricBinding)
            else task.x_metric
        )
        expected_y = (
            task.metric_binding.y_metric
            if isinstance(task.metric_binding, CartesianMetricBinding)
            else task.y_metric
        )
        assert terminal["x_metric"] == expected_x
        assert terminal["y_metric"] == expected_y
        assert "metric_ids" not in terminal
    assert normalize_terminal_render_request(terminal, label="task aware") == terminal
    terminal["resolved_figure_task"]["title"] = "mutated output"
    assert context == before


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("unknown_kind", "kind"),
        ("wrong_version", "version"),
        ("missing_task", "resolved_figure_task"),
        ("extra_field", "reserved fields"),
        ("template_mismatch", "template"),
        ("top_metric_mismatch", "canonical"),
        ("task_binding_mismatch", "canonical"),
        ("markers_on_legacy", "resolved_figure_task"),
    ],
)
def test_task_aware_terminal_request_rejects_noncanonical_mutations(
    mutation: str,
    reason: str,
) -> None:
    terminal = _terminal_request(_ordered_task(order=1))
    if mutation == "unknown_kind":
        terminal["kind"] = "not_sciplot"
    elif mutation == "wrong_version":
        terminal["version"] = 1
    elif mutation == "missing_task":
        terminal.pop("resolved_figure_task")
    elif mutation == "extra_field":
        terminal["unknown"] = True
    elif mutation == "template_mismatch":
        terminal["template"] = "scatter"
    elif mutation == "top_metric_mismatch":
        terminal["metric_ids"] = ["density", "tensile_strength"]
    elif mutation == "task_binding_mismatch":
        task = deepcopy(terminal["resolved_figure_task"])
        task["metric_binding"]["metric_ids"] = ["density", "tensile_strength"]
        terminal["resolved_figure_task"] = task
    else:
        terminal = {
            "template": "curve",
            "render_options": {},
            "resolved_figure_task": _legacy_task().to_payload(),
        }

    with pytest.raises(ValueError, match=reason):
        normalize_terminal_render_request(terminal, label="mutated terminal")


def test_bound_terminal_figure_evidence_is_exact_and_input_pure() -> None:
    plan = _planned_two_task_plan()
    result = _completed_result(plan)
    before = deepcopy(result)

    binding = bind_terminal_figure_evidence(
        selected_plan=plan,
        result=result,
    )

    assert isinstance(binding, BoundTerminalFigureEvidence)
    assert binding.selected_plan is plan
    assert binding.completed_plan.plan_id == plan.plan_id
    assert binding.terminal_tasks == plan.tasks
    assert (
        tuple(outcome.figure_id for outcome in binding.completed_plan.outcomes)
        == plan.selected_figure_ids
    )
    assert result == before


def test_source_unavailable_outcome_can_explain_missing_terminal_task() -> None:
    plan = _planned_two_task_plan()
    outcomes = (
        FigureOutcome(
            figure_id=plan.tasks[0].figure_id,
            status="unavailable",
            reason_code="fixture_artifacts_unavailable",
        ),
        FigureOutcome(
            figure_id=plan.tasks[1].figure_id,
            status="unavailable",
            reason_code="frequency_metric_source_unavailable",
        ),
    )
    completed = ResolvedFigurePlan(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        outcomes=outcomes,
        source_sha256=plan.source_sha256,
    )
    result = {
        "terminal_render_requests": [
            _terminal_request(plan.tasks[0], rule_id=plan.rule_id)
        ],
        "resolved_figure_plan": completed.to_payload(),
    }

    binding = bind_terminal_figure_evidence(
        selected_plan=plan,
        result=result,
    )

    assert binding is not None
    assert binding.terminal_tasks == (plan.tasks[0],)
    assert binding.reported_outcomes == outcomes


def test_source_unavailable_outcome_without_result_plan_cannot_hide_omission() -> None:
    plan = _planned_two_task_plan()
    outcomes = (
        FigureOutcome(
            figure_id=plan.tasks[0].figure_id,
            status="unavailable",
            reason_code="fixture_artifacts_unavailable",
        ),
        FigureOutcome(
            figure_id=plan.tasks[1].figure_id,
            status="unavailable",
            reason_code="frequency_metric_source_unavailable",
        ),
    )
    result = {
        "terminal_render_requests": [
            _terminal_request(plan.tasks[0], rule_id=plan.rule_id)
        ],
        "figure_outcomes": [outcome.to_payload() for outcome in outcomes],
    }

    with pytest.raises(ValueError, match="terminal_figure_task_missing"):
        bind_terminal_figure_evidence(
            selected_plan=plan,
            result=result,
        )


def test_single_rendered_task_does_not_need_early_outcome_projection() -> None:
    task = _legacy_task()
    plan = ResolvedFigurePlan.planned(
        rule_id="legacy_custom_rule",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    result = {
        "terminal_render_requests": [_terminal_request(task, rule_id=plan.rule_id)]
    }

    binding = bind_terminal_figure_evidence(
        selected_plan=plan,
        result=result,
    )

    assert binding is not None
    assert binding.terminal_tasks == (task,)
    assert binding.reported_outcomes == ()
    assert binding.completed_plan is None


def test_single_task_authoritative_source_coverage_rebuilds_v2_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _legacy_task()
    plan = ResolvedFigurePlan.planned(
        rule_id="legacy_custom_rule",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    declared = [_terminal_request(task, rule_id=plan.rule_id)]
    monkeypatch.setattr(
        studio_render,
        "derive_terminal_render_data_contract",
        lambda **_kwargs: {
            "units": [
                {
                    "kind": "series",
                    "label": "Fixture",
                }
            ]
        },
    )

    authoritative = _authoritative_terminal_render_requests(
        result={},
        authoritative_request={
            "template": task.template,
            "render_options": {"size": "60x55"},
            "resolved_figure_plan": plan.to_payload(),
        },
        declared_requests=declared,
        private_sources=[tmp_path / "terminal.csv"],
        spec_count=1,
    )

    assert authoritative == declared


def test_multi_task_authoritative_source_coverage_rebuilds_in_plan_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _planned_two_task_plan()
    declared = [_terminal_request(task, rule_id=plan.rule_id) for task in plan.tasks]

    def _unexpected_derivation(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError(
            "Task-bundle identity must be validated before data derivation."
        )

    monkeypatch.setattr(
        studio_render,
        "derive_terminal_render_data_contract",
        _unexpected_derivation,
    )

    authoritative = _authoritative_terminal_render_requests(
        result={
            "multi_metric_bundle": {
                "kind": "performance_comparison_figure_set",
                "figure_ids": list(plan.selected_figure_ids),
                "templates": [task.template for task in plan.tasks],
            },
            "terminal_render_requests": declared,
        },
        authoritative_request={
            "rule_id": plan.rule_id,
            "template": plan.tasks[0].template,
            "render_options": {"size": "60x55"},
            "resolved_figure_plan": plan.to_payload(),
        },
        declared_requests=declared,
        private_sources=[tmp_path / "terminal.csv"],
        spec_count=2,
    )

    assert authoritative == declared
    assert [request["resolved_figure_task"] for request in authoritative] == [
        task.to_payload() for task in plan.tasks
    ]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("duplicate", "terminal_figure_task_duplicate"),
        ("unselected", "terminal_figure_task_unselected"),
        ("reordered", "terminal_figure_task_reordered"),
        ("forged", "terminal_figure_task_mismatch"),
        ("legacy", "terminal_figure_task_missing"),
        ("planless", "requires a selected FigurePlan"),
        ("bundle_inventory", "bundle FigureTask inventory"),
    ],
)
def test_multi_task_authoritative_source_coverage_fails_before_derivation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    reason: str,
) -> None:
    plan = _planned_two_task_plan()
    declared = [_terminal_request(task, rule_id=plan.rule_id) for task in plan.tasks]
    bundle = {
        "kind": "performance_comparison_figure_set",
        "figure_ids": list(plan.selected_figure_ids),
        "templates": [task.template for task in plan.tasks],
    }
    authoritative_request = {
        "rule_id": plan.rule_id,
        "template": plan.tasks[0].template,
        "render_options": {"size": "60x55"},
        "resolved_figure_plan": plan.to_payload(),
    }
    if mutation == "duplicate":
        declared[1] = deepcopy(declared[0])
    elif mutation == "unselected":
        declared[1] = _terminal_request(
            _ordered_task(figure_id="unselected_polar"),
            rule_id=plan.rule_id,
        )
    elif mutation == "reordered":
        declared.reverse()
    elif mutation == "forged":
        forged = FigureTask.with_metric_binding(
            figure_id=plan.tasks[1].figure_id,
            order=2,
            title=plan.tasks[1].title,
            metric_binding=OrderedMetricsBinding(
                metric_ids=(
                    "density",
                    "tensile_strength",
                    "impact_strength",
                )
            ),
            template=plan.tasks[1].template,
            artifact_stem=plan.tasks[1].artifact_stem,
            document_stem=plan.tasks[1].document_stem,
        )
        declared[1] = _terminal_request(forged, rule_id=plan.rule_id)
    elif mutation == "legacy":
        declared[0] = {
            "template": plan.tasks[0].template,
            "render_options": {"size": "60x55"},
            "rule_id": plan.rule_id,
            "x_metric": "temperature",
            "y_metric": "storage_modulus",
        }
    elif mutation == "planless":
        authoritative_request.pop("resolved_figure_plan")
    else:
        bundle["figure_ids"] = [
            plan.tasks[0].figure_id,
            "unselected_polar",
        ]

    derivation_calls: list[dict[str, Any]] = []

    def _record_derivation(**kwargs: Any) -> dict[str, Any]:
        derivation_calls.append(kwargs)
        raise AssertionError("Invalid task evidence reached data derivation.")

    monkeypatch.setattr(
        studio_render,
        "derive_terminal_render_data_contract",
        _record_derivation,
    )

    with pytest.raises(ValueError, match=reason):
        _authoritative_terminal_render_requests(
            result={
                "multi_metric_bundle": bundle,
                "terminal_render_requests": declared,
            },
            authoritative_request=authoritative_request,
            declared_requests=declared,
            private_sources=[tmp_path / "terminal.csv"],
            spec_count=2,
        )

    assert derivation_calls == []


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "terminal_figure_task_missing"),
        ("duplicate", "terminal_figure_task_duplicate"),
        ("unselected", "terminal_figure_task_unselected"),
        ("reordered", "terminal_figure_task_reordered"),
        ("rule_mismatch", "terminal_figure_rule_mismatch"),
        ("binding_mismatch", "terminal_figure_task_mismatch"),
        ("legacy_evidence", "terminal_figure_task_missing"),
        ("result_plan_mismatch", "terminal_figure_plan_mismatch"),
    ],
)
def test_bound_terminal_figure_evidence_rejects_plan_splits(
    mutation: str,
    reason: str,
) -> None:
    plan = _planned_two_task_plan()
    result = _completed_result(plan)
    requests = result["terminal_render_requests"]
    if mutation == "missing":
        requests.pop()
    elif mutation == "duplicate":
        requests[1] = deepcopy(requests[0])
    elif mutation == "unselected":
        task = _ordered_task(figure_id="unselected_polar", order=2)
        requests[1] = _terminal_request(task)
    elif mutation == "reordered":
        requests.reverse()
    elif mutation == "rule_mismatch":
        requests[0]["rule_id"] = "different_rule"
    elif mutation == "binding_mismatch":
        changed = FigureTask.with_metric_binding(
            figure_id="ordered_polar",
            order=2,
            title="Ordered polar",
            metric_binding=OrderedMetricsBinding(
                metric_ids=("density", "tensile_strength", "impact_strength"),
            ),
            template="polar_curve",
            artifact_stem="ordered_polar",
            document_stem="ordered_polar",
        )
        requests[1] = _terminal_request(changed)
    elif mutation == "legacy_evidence":
        requests[0] = {
            "template": "curve",
            "render_options": {"size": "60x55"},
            "x_metric": "temperature",
            "y_metric": "storage_modulus",
        }
    else:
        different = ResolvedFigurePlan(
            rule_id="different_rule",
            selection_policy=plan.selection_policy,
            primary_figure_id=plan.primary_figure_id,
            tasks=plan.tasks,
            outcomes=_completed_plan(plan).outcomes,
            source_sha256=plan.source_sha256,
        )
        result["resolved_figure_plan"] = different.to_payload()

    with pytest.raises(ValueError, match=reason):
        bind_terminal_figure_evidence(
            selected_plan=plan,
            result=result,
        )


def test_unplanned_legacy_result_remains_valid_but_task_evidence_needs_plan(
    tmp_path: Path,
) -> None:
    route = resolve_workflow_route_intent({"template": "curve"})
    legacy_result = {
        "terminal_render_requests": [
            {
                "template": "curve",
                "render_options": {},
            }
        ]
    }

    rendered = RequestRenderResult(
        route_intent=route,
        final_recipe=None,
        result=legacy_result,
        plotted_data_source=tmp_path / "input.csv",
    )

    assert rendered.figure_evidence is None
    assert rendered.result == legacy_result
    with pytest.raises(ValueError, match="terminal_figure_task_unbound"):
        RequestRenderResult(
            route_intent=route,
            final_recipe=None,
            result={
                "terminal_render_requests": [_terminal_request(_cartesian_v2_task())]
            },
            plotted_data_source=tmp_path / "input.csv",
        )


def test_request_render_result_binds_plan_tasks_and_completed_outcomes(
    tmp_path: Path,
) -> None:
    plan = _planned_two_task_plan()
    result = _completed_result(plan)
    route = resolve_workflow_route_intent({"template": "curve"})

    rendered = RequestRenderResult(
        route_intent=route,
        final_recipe=None,
        result=result,
        plotted_data_source=tmp_path / "input.csv",
        selected_figure_plan=plan,
    )

    assert rendered.figure_evidence is not None
    assert rendered.figure_evidence.terminal_tasks == plan.tasks
    assert rendered.figure_evidence.completed_plan.plan_id == plan.plan_id


def test_execute_request_render_parses_and_binds_plan_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _legacy_task()
    plan = ResolvedFigurePlan.planned(
        rule_id="legacy_custom_rule",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    result = _completed_result(plan)
    request = {
        "template": "curve",
        "rule_id": "legacy_custom_rule",
        "resolved_figure_plan": plan.to_payload(),
    }
    route = resolve_workflow_route_intent(request)
    calls: list[dict[str, Any]] = []

    def fake_render(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return result

    monkeypatch.setattr(request_rendering, "_render_with_auto_split", fake_render)
    reports: list[dict[str, Any]] = []
    monkeypatch.setattr(
        request_rendering,
        "_write_render_report",
        lambda _output, **kwargs: reports.append(kwargs["result"]),
    )

    rendered = request_rendering.execute_request_render(
        request=request,
        route_intent=route,
        semantic={},
        study_model={},
        input_path=tmp_path / "input.csv",
        output_dir=tmp_path / "output",
        base_dir=tmp_path,
        transform_steps=[],
    )

    assert len(calls) == 1
    assert reports == [rendered.result]
    assert rendered.selected_figure_plan == plan
    assert rendered.figure_evidence is not None
    assert rendered.figure_evidence.terminal_tasks == (task,)


def test_execute_request_render_rejects_invalid_plan_before_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = {
        "template": "curve",
        "resolved_figure_plan": {"kind": "forged"},
    }
    route = resolve_workflow_route_intent(request)
    calls: list[bool] = []
    report_calls: list[bool] = []
    monkeypatch.setattr(
        request_rendering,
        "_render_with_auto_split",
        lambda *_args, **_kwargs: calls.append(True),
    )
    monkeypatch.setattr(
        request_rendering,
        "_write_render_report",
        lambda *_args, **_kwargs: report_calls.append(True),
    )

    with pytest.raises(ValueError, match="ResolvedFigurePlan"):
        request_rendering.execute_request_render(
            request=request,
            route_intent=route,
            semantic={},
            study_model={},
            input_path=tmp_path / "input.csv",
            output_dir=tmp_path / "output",
            base_dir=tmp_path,
            transform_steps=[],
        )

    assert calls == []
    assert report_calls == []


def test_named_recipe_with_plan_fails_before_recipe_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _legacy_task()
    plan = ResolvedFigurePlan.planned(
        rule_id="legacy_custom_rule",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    request = {
        "recipe": "tensile",
        "rule_id": plan.rule_id,
        "resolved_figure_plan": plan.to_payload(),
    }
    route = resolve_workflow_route_intent(request)
    recipe_calls: list[bool] = []
    monkeypatch.setattr(
        request_rendering,
        "run_recipe",
        lambda *_args, **_kwargs: recipe_calls.append(True),
    )

    with pytest.raises(ValueError, match="workflow_recipe_figure_plan_unsupported"):
        request_rendering.execute_request_render(
            request=request,
            route_intent=route,
            semantic={},
            study_model={},
            input_path=tmp_path / "input.csv",
            output_dir=tmp_path / "output",
            base_dir=tmp_path,
            transform_steps=[],
        )

    assert recipe_calls == []


def test_post_render_task_mismatch_fails_before_direct_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _legacy_task()
    plan = ResolvedFigurePlan.planned(
        rule_id="legacy_custom_rule",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    result = _completed_result(plan)
    changed = FigureTask(
        figure_id=task.figure_id,
        order=task.order,
        title=task.title,
        x_metric="changed_time",
        y_metric=task.y_metric,
        template=task.template,
        artifact_stem=task.artifact_stem,
        document_stem=task.document_stem,
    )
    result["terminal_render_requests"] = [
        _terminal_request(changed, rule_id=plan.rule_id)
    ]
    request = {
        "template": "curve",
        "rule_id": plan.rule_id,
        "resolved_figure_plan": plan.to_payload(),
    }
    route = resolve_workflow_route_intent(request)
    render_calls: list[bool] = []
    report_calls: list[bool] = []
    monkeypatch.setattr(
        request_rendering,
        "_render_with_auto_split",
        lambda *_args, **_kwargs: render_calls.append(True) or result,
    )
    monkeypatch.setattr(
        request_rendering,
        "_write_render_report",
        lambda *_args, **_kwargs: report_calls.append(True),
    )

    with pytest.raises(ValueError, match="terminal_figure_task_mismatch"):
        request_rendering.execute_request_render(
            request=request,
            route_intent=route,
            semantic={},
            study_model={},
            input_path=tmp_path / "input.csv",
            output_dir=tmp_path / "output",
            base_dir=tmp_path,
            transform_steps=[],
        )

    assert render_calls == [True]
    assert report_calls == []


def test_post_render_task_mismatch_fails_before_auto_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _legacy_task()
    plan = ResolvedFigurePlan.planned(
        rule_id="legacy_custom_rule",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    result = _completed_result(plan)
    result["terminal_render_requests"] = [
        _terminal_request(
            FigureTask(
                figure_id=task.figure_id,
                order=task.order,
                title=task.title,
                x_metric="changed_time",
                y_metric=task.y_metric,
                template=task.template,
                artifact_stem=task.artifact_stem,
                document_stem=task.document_stem,
            ),
            rule_id=plan.rule_id,
        )
    ]
    request = {
        "resolved_figure_plan": plan.to_payload(),
    }
    route = resolve_workflow_route_intent(request)
    prepared_source = tmp_path / "prepared.csv"
    render_calls: list[bool] = []
    report_calls: list[bool] = []
    monkeypatch.setattr(
        request_rendering,
        "prepare_semantic_source",
        lambda *_args, **_kwargs: {
            "source": str(prepared_source),
            "processed_source": None,
            "processed": False,
            "transform_steps": [],
        },
    )
    monkeypatch.setattr(
        request_rendering,
        "_render_with_auto_split",
        lambda *_args, **_kwargs: render_calls.append(True) or result,
    )
    monkeypatch.setattr(
        request_rendering,
        "compute_analysis_metrics",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        request_rendering,
        "_write_auto_report",
        lambda *_args, **_kwargs: report_calls.append(True),
    )

    with pytest.raises(ValueError, match="terminal_figure_task_mismatch"):
        request_rendering.execute_request_render(
            request=request,
            route_intent=route,
            semantic={
                "rule_id": plan.rule_id,
                "template": "curve",
                "semantic_family": "legacy",
                "render_options": {},
            },
            study_model={},
            input_path=tmp_path / "input.csv",
            output_dir=tmp_path / "output",
            base_dir=tmp_path,
            transform_steps=[],
        )

    assert render_calls == [True]
    assert report_calls == []
