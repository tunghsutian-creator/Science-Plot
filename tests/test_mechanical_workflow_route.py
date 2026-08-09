from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sciplot_core._paths import resolve_fixture_path
from sciplot_core import workflow
from sciplot_core.figure_plan import ResolvedFigurePlan, resolve_figure_plan
from sciplot_core.materials_rules import get_rule
from sciplot_core.mechanical_figure_contract import mechanical_figure_contract
from sciplot_core.study_model import experiment_recommendation_payload
from sciplot_core.workflow import request_rendering
from sciplot_core.workflow.request_rendering import RequestRenderResult
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent


def _resolved_compression_plan() -> tuple[Path, ResolvedFigurePlan]:
    rule_id = "compression_curve"
    source = resolve_fixture_path(str(get_rule(rule_id).fixture_path or ""))
    plan = resolve_figure_plan(
        rule_id=rule_id,
        template="curve",
        study_model=experiment_recommendation_payload(rule_id=rule_id),
        input_path=source,
        request={"template": "curve"},
    )
    assert plan is not None
    return source, plan


def test_direct_mechanical_plan_uses_shared_semantic_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, plan = _resolved_compression_plan()
    request = {
        "template": "curve",
        "rule_id": plan.rule_id,
        "resolved_figure_plan": plan.to_payload(),
    }
    route = resolve_workflow_route_intent(request)
    sentinel = RequestRenderResult(
        route_intent=route,
        final_recipe=None,
        result={"kind": "sentinel"},
        plotted_data_source=source,
    )
    calls: list[dict[str, Any]] = []

    def fake_semantic_render(**kwargs: Any) -> RequestRenderResult:
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(
        request_rendering,
        "_render_semantic_plan_request",
        fake_semantic_render,
    )
    monkeypatch.setattr(
        request_rendering,
        "_render_with_auto_split",
        lambda *_args, **_kwargs: pytest.fail(
            "mechanical direct route bypassed semantic preparation"
        ),
    )

    rendered = request_rendering.execute_request_render(
        request=request,
        route_intent=route,
        semantic={"rule_id": plan.rule_id, "template": "curve"},
        study_model=experiment_recommendation_payload(rule_id=plan.rule_id),
        input_path=source,
        output_dir=tmp_path / "output",
        base_dir=tmp_path,
        transform_steps=[],
    )

    contract = mechanical_figure_contract(plan.rule_id)
    assert rendered is sentinel
    assert route.route == "render"
    assert len(calls) == 1
    assert calls[0]["selected_figure_plan"] == plan
    assert plan.selected_figure_ids == tuple(task.figure_id for task in contract.tasks)
    assert calls[0]["final_recipe"] is None
    assert calls[0]["named_recipe_binding"] is None


@pytest.mark.comprehensive
def test_direct_compression_lifecycle_delivers_every_selected_task(
    tmp_path: Path,
) -> None:
    source, expected_plan = _resolved_compression_plan()
    output_dir = tmp_path / "output"
    request_path = tmp_path / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "input": str(source),
                "output": str(output_dir),
                "rule_id": expected_plan.rule_id,
                "template": "curve",
                "explicit_template_selection": True,
                "explicit_render_option_keys": [],
                "exports": ["pdf", "tiff_300"],
            }
        ),
        encoding="utf-8",
    )

    manifest = workflow.run_request(request_path)
    plan = ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"])
    assert manifest["route"] == "render"
    assert manifest["final_recipe"] is None
    assert plan.status == "ready"
    assert plan.selected_figure_ids == expected_plan.selected_figure_ids
    assert manifest["result"]["resolved_figure_plan"] == plan.to_payload()
    assert "figure_outcomes" not in manifest
    assert "figure_outcomes" not in manifest["result"]
    assert [
        item["resolved_figure_task"]
        for item in manifest["result"]["terminal_render_requests"]
    ] == [task.to_payload() for task in plan.tasks]
    assert len(manifest["result"]["veusz_documents"]) == len(plan.tasks)
