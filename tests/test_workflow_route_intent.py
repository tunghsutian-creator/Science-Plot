from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from sciplot_core.workflow import request_rendering, request_run
from sciplot_core.workflow.request_rendering import RequestRenderResult
from sciplot_core.workflow.route_intent import (
    WorkflowRoute,
    WorkflowRouteIntent,
    resolve_workflow_route_intent,
)


@pytest.mark.parametrize(
    ("request_payload", "expected"),
    [
        ({}, WorkflowRouteIntent("auto", None, None)),
        (
            {"recipe": "auto"},
            WorkflowRouteIntent("auto", "auto", None),
        ),
        (
            {"recipe": "auto", "template": "curve"},
            WorkflowRouteIntent("auto", "auto", "curve"),
        ),
        (
            {"recipe": "tensile"},
            WorkflowRouteIntent("recipe", "tensile", None),
        ),
        (
            {"recipe": "tensile", "template": "curve"},
            WorkflowRouteIntent("recipe", "tensile", "curve"),
        ),
        (
            {"template": "curve"},
            WorkflowRouteIntent("render", None, "curve"),
        ),
        (
            {"recipe": None, "template": None},
            WorkflowRouteIntent("auto", None, None),
        ),
    ],
)
def test_route_intent_resolves_once_from_request_shape(
    request_payload: dict[str, object],
    expected: WorkflowRouteIntent,
) -> None:
    assert resolve_workflow_route_intent(request_payload) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipe", True),
        ("recipe", 1),
        ("recipe", []),
        ("recipe", {}),
        ("recipe", ""),
        ("recipe", "  "),
        ("template", True),
        ("template", 1),
        ("template", []),
        ("template", {}),
        ("template", ""),
        ("template", "  "),
    ],
)
def test_route_intent_rejects_malformed_present_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match=rf"workflow_route_invalid:.*{field}"):
        resolve_workflow_route_intent({field: value})


@pytest.mark.parametrize(
    "intent",
    [
        ("auto", "tensile", None),
        ("auto", None, "curve"),
        ("recipe", None, None),
        ("recipe", "auto", None),
        ("render", "tensile", "curve"),
        ("render", None, None),
        ("unknown", None, None),
    ],
)
def test_route_intent_rejects_impossible_direct_construction(
    intent: tuple[str, str | None, str | None],
) -> None:
    route, recipe, template = intent
    with pytest.raises(ValueError, match="workflow_route_invalid"):
        WorkflowRouteIntent(
            cast(WorkflowRoute, route),
            recipe,
            template,
        )


def test_template_materialization_does_not_change_auto_render_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request: dict[str, Any] = {}
    route_intent = resolve_workflow_route_intent(request)
    request["template"] = "curve"
    sentinel = RequestRenderResult(
        route_intent=route_intent,
        final_recipe=None,
        result={"kind": "sentinel"},
        plotted_data_source=tmp_path / "input.csv",
    )
    calls: list[WorkflowRouteIntent] = []

    def fake_auto_request(**kwargs: Any) -> RequestRenderResult:
        calls.append(kwargs["route_intent"])
        return sentinel

    monkeypatch.setattr(request_rendering, "_render_auto_request", fake_auto_request)
    monkeypatch.setattr(
        request_rendering,
        "run_recipe",
        lambda *_args, **_kwargs: pytest.fail("auto intent reached recipe route"),
    )

    rendered = request_rendering.execute_request_render(
        request=request,
        route_intent=route_intent,
        semantic={},
        study_model={},
        input_path=tmp_path / "input.csv",
        output_dir=tmp_path / "output",
        base_dir=tmp_path,
        transform_steps=[],
    )

    assert rendered is sentinel
    assert calls == [route_intent]
    assert rendered.route == "auto"


def test_template_materialization_does_not_bypass_auto_intervention_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request: dict[str, Any] = {}
    route_intent = resolve_workflow_route_intent(request)
    request["template"] = "curve"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    calls: list[str] = []

    def fake_intervention(**_kwargs: Any) -> dict[str, Any]:
        calls.append("intervention")
        return {"category": "ambiguous_source"}

    monkeypatch.setattr(
        request_run,
        "build_intervention_request",
        fake_intervention,
    )
    monkeypatch.setattr(
        request_run,
        "write_cleanup_request",
        lambda *_args, **_kwargs: calls.append("cleanup"),
    )
    monkeypatch.setattr(
        request_run,
        "build_one_step_project",
        lambda **_kwargs: calls.append("one_step") or {},
    )
    monkeypatch.setattr(
        request_run,
        "_write_one_step_status",
        lambda *_args, **_kwargs: calls.append("status"),
    )

    with pytest.raises(ValueError, match="could not auto-detect"):
        request_run._enforce_intervention_gate(
            request_path=tmp_path / "plot_request.json",
            request=request,
            route_intent=route_intent,
            semantic={
                "needs_ai_intervention": True,
                "rule_readiness": "ready",
            },
            input_path=tmp_path / "input.csv",
            output_dir=output_dir,
            raw_archive={},
            study_model={},
            layout_policy=object(),
        )

    assert calls == ["intervention", "cleanup", "one_step", "status"]
    assert (output_dir / "intervention_request.json").is_file()


def test_direct_route_does_not_enter_auto_intervention_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = {"template": "curve"}
    route_intent = resolve_workflow_route_intent(request)
    monkeypatch.setattr(
        request_run,
        "build_intervention_request",
        lambda **_kwargs: pytest.fail("direct route entered auto intervention"),
    )

    request_run._enforce_intervention_gate(
        request_path=tmp_path / "plot_request.json",
        request=request,
        route_intent=route_intent,
        semantic={
            "needs_ai_intervention": True,
            "rule_readiness": "ready",
        },
        input_path=tmp_path / "input.csv",
        output_dir=tmp_path / "output",
        raw_archive={},
        study_model={},
        layout_policy=object(),
    )


def test_recipe_execution_uses_captured_recipe_after_request_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request: dict[str, Any] = {
        "recipe": "tensile",
        "template": "curve",
    }
    route_intent = resolve_workflow_route_intent(request)
    request["recipe"] = "wrong_late_value"
    recipes: list[str] = []

    def fake_recipe(
        recipe: str,
        _input_path: Path,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        recipes.append(recipe)
        return {"processed_source": None}

    monkeypatch.setattr(request_rendering, "run_recipe", fake_recipe)

    rendered = request_rendering.execute_request_render(
        request=request,
        route_intent=route_intent,
        semantic={},
        study_model={},
        input_path=tmp_path / "input.csv",
        output_dir=tmp_path / "output",
        base_dir=tmp_path,
        transform_steps=[],
    )

    assert recipes == ["tensile"]
    assert rendered.route_intent is route_intent
    assert rendered.route == "recipe"
    assert rendered.final_recipe == "tensile"
