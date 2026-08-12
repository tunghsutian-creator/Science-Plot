from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureTask,
    ResolvedFigurePlan,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.scientific_source import resolve_scientific_source
import sciplot_core.workflow.auto_split as auto_split
import sciplot_core.workflow.single_task_bundle as single_task_bundle
from sciplot_core.studio_core.figure_task_evidence import (
    generic_figure_queue_from_plan,
)


def _generic_plan() -> ResolvedFigurePlan:
    task = FigureTask.with_metric_binding(
        figure_id="tga_mass_vs_temperature",
        order=1,
        title="Mass versus temperature",
        metric_binding=CartesianMetricBinding(
            x_metric="temperature",
            y_metric="mass",
        ),
        template="curve",
        artifact_stem="tga_mass_vs_temperature",
        document_stem="tga_mass_vs_temperature",
    )
    return ResolvedFigurePlan.planned(
        rule_id="tga_curve",
        selection_policy="test_generic_single_task",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )


def test_generic_selected_plan_uses_shared_bundle_with_prepared_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _generic_plan()
    calls: list[dict[str, Any]] = []

    def render_bundle(input_path: Path, **kwargs: Any) -> dict[str, Any]:
        calls.append({"input_path": input_path, **kwargs})
        return {"kind": "generic_single_task_result"}

    monkeypatch.setattr(
        auto_split,
        "render_selected_single_task_bundle",
        render_bundle,
    )
    monkeypatch.setattr(
        auto_split,
        "render_to_dir",
        lambda *_args, **_kwargs: pytest.fail(
            "selected plan fell back to render_to_dir"
        ),
    )
    prepared = tmp_path / "prepared.csv"

    result = auto_split._render_with_auto_split(
        prepared,
        template="curve",
        output_dir=tmp_path / "out",
        options={},
        export_formats=["pdf"],
        request={
            "rule_id": plan.rule_id,
            "resolved_figure_plan": plan.to_payload(),
        },
        _terminal_source_prepared=True,
    )

    assert result == {"kind": "generic_single_task_result"}
    assert len(calls) == 1
    assert calls[0]["input_path"] == prepared
    assert calls[0]["plan"] == plan
    assert calls[0]["task"] == plan.tasks[0]
    assert calls[0]["terminal_source_prepared"] is True


def test_shared_single_task_bundle_forwards_prepared_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _generic_plan()
    captured: dict[str, Any] = {}

    def stop_at_renderer(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        raise RuntimeError("stop after marker capture")

    monkeypatch.setattr(single_task_bundle, "render_to_dir", stop_at_renderer)

    with pytest.raises(RuntimeError, match="stop after marker capture"):
        single_task_bundle.render_selected_single_task_bundle(
            tmp_path / "prepared.csv",
            plan=plan,
            task=plan.tasks[0],
            output_dir=tmp_path / "out",
            options={},
            export_formats=["pdf"],
            request={"rule_id": plan.rule_id},
            metric_id="mass",
            bundle_kind="generic_single_task_figure_set",
            missing_reason_code="generic_single_task_artifacts_incomplete",
            terminal_source_prepared=True,
        )

    assert captured["_terminal_source_prepared"] is True


def test_studio_projects_generic_plan_without_a_second_queue_contract() -> None:
    plan = _generic_plan()

    queue = generic_figure_queue_from_plan(plan, render_adapter="generic")

    assert [item["id"] for item in queue] == [plan.primary_figure_id]
    assert queue[0]["resolved_figure_task"] == plan.tasks[0].to_payload()
    assert generic_figure_queue_from_plan(plan, render_adapter="dsc") == []

    second_task = FigureTask.with_metric_binding(
        figure_id="tga_derivative_vs_temperature",
        order=2,
        title="Derivative versus temperature",
        metric_binding=CartesianMetricBinding(
            x_metric="temperature",
            y_metric="mass_derivative",
        ),
        template="curve",
        artifact_stem="tga_derivative_vs_temperature",
        document_stem="tga_derivative_vs_temperature",
    )
    multi_task_plan = ResolvedFigurePlan.planned(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=(*plan.tasks, second_task),
    )
    with pytest.raises(ValueError, match="studio_generic_single_task_plan_mismatch"):
        generic_figure_queue_from_plan(
            multi_task_plan,
            render_adapter="generic",
        )


def test_dsc_rule_uses_the_shared_generic_studio_queue() -> None:
    rule = get_rule("dsc_curve")
    source = resolve_fixture_path(str(rule.fixture_path or ""))
    resolved = resolve_scientific_source(
        source,
        rule_id=rule.rule_id,
        request={},
        template=rule.template,
    )

    assert resolved is not None
    assert resolved.figure_plan is not None
    queue = generic_figure_queue_from_plan(
        resolved.figure_plan,
        render_adapter=rule.render_adapter,
    )
    assert [item["id"] for item in queue] == [
        resolved.figure_plan.primary_figure_id
    ]
    assert queue[0]["resolved_figure_task"] == (
        resolved.figure_plan.tasks[0].to_payload()
    )
