from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureTask,
    OrderedMetricsBinding,
    ResolvedFigurePlan,
)
from sciplot_core.policy import DEFAULT_LAYOUT_POLICY
from sciplot_core.terminal_request import project_terminal_render_request
from sciplot_core.workflow.request_publish import _build_request_manifest
from sciplot_core.workflow.request_rendering import RequestRenderResult
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent


@pytest.mark.parametrize(
    ("rule_id", "templates", "task_kind"),
    [
        ("performance_comparison", ("scatter", "polar_curve"), "mixed_v2"),
        ("impact_metric", ("box_strip", "box_strip"), "legacy"),
        ("rheology_frequency_sweep", ("point_line",) * 4, "cartesian_v2"),
        ("dsc_curve", ("curve",), "cartesian_v2"),
        (
            "tensile_curve",
            ("curve", "box_strip", "box_strip", "box_strip", "box_strip"),
            "cartesian_v2",
        ),
    ],
)
def test_request_render_result_owns_one_completed_plan_projection(
    tmp_path: Path,
    rule_id: str,
    templates: tuple[str, ...],
    task_kind: str,
) -> None:
    tasks = tuple(
        _task(
            order=order,
            template=template,
            task_kind=task_kind,
        )
        for order, template in enumerate(templates, start=1)
    )
    selected = ResolvedFigurePlan.planned(
        rule_id=rule_id,
        selection_policy="fixture_existing_plan_shape",
        primary_figure_id=tasks[0].figure_id,
        tasks=tasks,
        source_sha256="a" * 64,
    )
    raw_result = {
        "terminal_render_requests": [
            project_terminal_render_request(
                template=task.template,
                render_options={"size": "60x55"},
                request_context={
                    "rule_id": rule_id,
                    "resolved_figure_task": task.to_payload(),
                },
            )
            for task in tasks
        ]
    }
    before = deepcopy(raw_result)

    rendered = RequestRenderResult(
        route_intent=resolve_workflow_route_intent({"template": templates[0]}),
        final_recipe=None,
        result=raw_result,
        plotted_data_source=tmp_path / "input.csv",
        selected_figure_plan=selected,
    )

    completed = rendered.completed_figure_plan
    assert completed is not None
    assert completed.plan_id == selected.plan_id
    assert completed.status == "incomplete"
    assert [outcome.figure_id for outcome in completed.outcomes] == [
        task.figure_id for task in tasks
    ]
    assert {outcome.reason_code for outcome in completed.outcomes} == {
        (
            "selected_figure_artifacts_missing"
            if len(tasks) == 1
            else "selected_figure_outcome_missing"
        )
    }
    assert rendered.result["resolved_figure_plan"] == completed.to_payload()
    assert "figure_outcomes" not in rendered.result
    assert rendered.figure_evidence is not None
    assert rendered.figure_evidence.completed_plan == completed
    assert rendered.figure_evidence.reported_outcomes == completed.outcomes
    assert raw_result == before


def test_workflow_manifest_keeps_only_the_completed_plan(
    tmp_path: Path,
) -> None:
    task = _task(order=1, template="curve", task_kind="cartesian_v2")
    selected = ResolvedFigurePlan.planned(
        rule_id="dsc_curve",
        selection_policy="fixture_existing_plan_shape",
        primary_figure_id=task.figure_id,
        tasks=(task,),
        source_sha256="a" * 64,
    )
    rendered = RequestRenderResult(
        route_intent=resolve_workflow_route_intent({"template": "curve"}),
        final_recipe=None,
        result={
            "terminal_render_requests": [
                project_terminal_render_request(
                    template=task.template,
                    render_options={},
                    request_context={
                        "rule_id": selected.rule_id,
                        "resolved_figure_task": task.to_payload(),
                    },
                )
            ]
        },
        plotted_data_source=tmp_path / "input.csv",
        selected_figure_plan=selected,
    )

    manifest = _build_request_manifest(
        request_path=tmp_path / "plot_request.json",
        source_request={},
        request={},
        mapping_application=None,
        cleanup_application=None,
        semantic={},
        input_path=tmp_path / "input.csv",
        raw_archive={},
        output_dir=tmp_path / "output",
        rendered=rendered,
        result=rendered.result,
        study_model={},
        publication_intent={},
        transform_ledger={},
        publication_profile={},
        publication_qa={},
        publication_artifacts={},
        qa={},
        figures=[],
        layout_policy=DEFAULT_LAYOUT_POLICY,
    )

    assert manifest["resolved_figure_plan"] == rendered.result[
        "resolved_figure_plan"
    ]
    assert "figure_outcomes" not in manifest
    assert "figure_outcomes" not in rendered.result


def _task(*, order: int, template: str, task_kind: str) -> FigureTask:
    figure_id = f"task_{order}"
    common = {
        "figure_id": figure_id,
        "order": order,
        "title": f"Task {order}",
        "template": template,
        "artifact_stem": figure_id,
        "document_stem": figure_id,
    }
    if task_kind == "legacy":
        return FigureTask(
            **common,
            x_metric="sample",
            y_metric="impact_strength",
        )
    if task_kind == "mixed_v2" and order == 2:
        return FigureTask.with_metric_binding(
            **common,
            metric_binding=OrderedMetricsBinding(
                metric_ids=("density", "impact_strength", "tensile_strength"),
            ),
        )
    return FigureTask.with_metric_binding(
        **common,
        metric_binding=CartesianMetricBinding(
            x_metric="temperature" if order == 1 else "sample",
            y_metric=f"metric_{order}",
        ),
    )
