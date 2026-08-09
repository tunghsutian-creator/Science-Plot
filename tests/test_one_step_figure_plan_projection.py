from __future__ import annotations

from pathlib import Path

import pytest

import sciplot_core.one_step.project as one_step_project
import sciplot_core.one_step.readiness as one_step_readiness
import sciplot_core.workflow.request_run as request_run
from sciplot_core.figure_plan import FigureOutcome, FigureTask, ResolvedFigurePlan
from sciplot_core.policy import DEFAULT_LAYOUT_POLICY
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent


def test_one_step_carries_one_canonical_completed_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(rule_id="impact_metric", complete=True)
    input_path = tmp_path / "input.csv"
    input_path.write_text("sample,value\nA,1\n", encoding="utf-8")
    _stub_readiness(monkeypatch)

    payload = one_step_project.build_one_step_project(
        input_path=input_path,
        request_path=tmp_path / "plot_request.json",
        request={"rule_id": plan.rule_id, "template": "point_line"},
        semantic={
            "rule_id": plan.rule_id,
            "semantic_family": "impact",
            "confidence": 1.0,
        },
        raw_archive={},
        study_model={},
        layout_policy=DEFAULT_LAYOUT_POLICY,
        layout_quality={},
        qa={"status": "passed"},
        delivery_package={"complete": True},
        resolved_figure_plan=plan,
    )

    assert payload["resolved_figure_plan"] == plan.to_payload()
    assert "figure_outcomes" not in payload


def test_legacy_one_step_omits_optional_plan_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_readiness(monkeypatch)

    payload = one_step_project.build_one_step_project(
        input_path=tmp_path / "legacy.csv",
        request_path=tmp_path / "plot_request.json",
        request={"rule_id": "legacy_custom_rule"},
        semantic={"rule_id": "legacy_custom_rule"},
        raw_archive={},
        study_model={},
        layout_policy=DEFAULT_LAYOUT_POLICY,
        layout_quality={},
        qa=None,
    )

    assert "resolved_figure_plan" not in payload
    assert "figure_outcomes" not in payload


def test_intervention_passes_its_existing_typed_plan_to_one_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(rule_id="impact_metric", complete=False)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        request_run,
        "build_intervention_request",
        lambda **_kwargs: {"category": "ambiguous_source"},
    )
    monkeypatch.setattr(
        request_run,
        "write_cleanup_request",
        lambda *_args, **_kwargs: None,
    )

    def capture_one_step(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(request_run, "build_one_step_project", capture_one_step)
    monkeypatch.setattr(
        request_run,
        "_write_one_step_status",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ValueError, match="could not auto-detect"):
        request_run._enforce_intervention_gate(
            request_path=tmp_path / "plot_request.json",
            request={},
            route_intent=resolve_workflow_route_intent({}),
            semantic={
                "needs_ai_intervention": True,
                "rule_readiness": "ready",
            },
            input_path=tmp_path / "input.csv",
            output_dir=output_dir,
            raw_archive={},
            study_model={},
            layout_policy=DEFAULT_LAYOUT_POLICY,
            figure_plan=plan,
        )

    assert captured["resolved_figure_plan"] is plan


def test_one_step_readiness_rejects_an_incomplete_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        one_step_readiness,
        "validated_envelope_evaluation_ready",
        lambda *_args, **_kwargs: True,
    )

    state, reasons = one_step_readiness._readiness(
        source_package={"confidence_band": "high"},
        mapping_package={"status": "confirmed"},
        render_request={},
        figure_qa_report={
            "status": "passed",
            "qa_status": "passed",
            "delivery_complete": True,
        },
        validated_envelope={"state": "inside_validated_envelope"},
        resolved_figure_plan=_plan(rule_id="impact_metric", complete=False),
    )

    assert state == "needs_rule_repair"
    assert reasons == ["resolved_figure_plan_incomplete"]


def _plan(*, rule_id: str, complete: bool) -> ResolvedFigurePlan:
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="sample",
        y_metric="value",
        template="point_line",
        artifact_stem="figure_a",
        document_stem="figure_a",
    )
    outcome = FigureOutcome(
        figure_id=task.figure_id,
        status="ready" if complete else "unavailable",
        artifacts=(
            ("figure_a.vsz", "figure_a.pdf", "figure_a_300dpi.tiff")
            if complete
            else ()
        ),
        reason_code=None if complete else "fixture_unavailable",
    )
    return ResolvedFigurePlan(
        rule_id=rule_id,
        selection_policy="fixture",
        primary_figure_id=task.figure_id,
        tasks=(task,),
        outcomes=(outcome,),
    )


def _stub_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        one_step_project,
        "evaluate_validated_envelope",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        one_step_project,
        "_readiness",
        lambda **_kwargs: ("ready", ["fixture_ready"]),
    )
