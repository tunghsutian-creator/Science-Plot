from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sciplot_core.autoplot.summary as summary_module
from sciplot_core.figure_plan import FigureOutcome, FigureTask, ResolvedFigurePlan


def test_autoplot_projection_reuses_full_manifest_plan(tmp_path: Path) -> None:
    plan = _completed_plan(tmp_path)
    manifest = _manifest(plan)
    one_step = {"resolved_figure_plan": plan.to_payload()}
    manifest_before = deepcopy(manifest)
    one_step_before = deepcopy(one_step)

    payload, gate, consistent = summary_module._autoplot_figure_plan_projection(
        manifest=manifest,
        one_step=one_step,
    )

    assert payload == plan.to_payload()
    assert gate is not None and gate["complete"] is True
    assert consistent is True
    assert manifest == manifest_before
    assert one_step == one_step_before


@pytest.mark.parametrize(
    "one_step_plan",
    [None, {"kind": "forged"}],
)
def test_autoplot_projection_rejects_one_step_plan_split(
    tmp_path: Path,
    one_step_plan: object | None,
) -> None:
    plan = _completed_plan(tmp_path)

    _payload, _gate, consistent = summary_module._autoplot_figure_plan_projection(
        manifest=_manifest(plan),
        one_step=(
            {}
            if one_step_plan is None
            else {"resolved_figure_plan": one_step_plan}
        ),
    )

    assert consistent is False


def test_autoplot_projection_compares_outcomes_not_only_plan_id(
    tmp_path: Path,
) -> None:
    plan = _completed_plan(tmp_path)
    different_outcomes = ResolvedFigurePlan(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        outcomes=(
            FigureOutcome(
                figure_id=plan.tasks[0].figure_id,
                status="unavailable",
                reason_code="fixture_unavailable",
            ),
        ),
    )
    assert different_outcomes.plan_id == plan.plan_id
    assert different_outcomes.plan_sha256 == plan.plan_sha256

    _payload, _gate, consistent = summary_module._autoplot_figure_plan_projection(
        manifest=_manifest(plan),
        one_step={"resolved_figure_plan": different_outcomes.to_payload()},
    )

    assert consistent is False


def test_autoplot_projection_accepts_legacy_payload_without_plan() -> None:
    payload, gate, consistent = summary_module._autoplot_figure_plan_projection(
        manifest={},
        one_step={},
    )

    assert payload is None
    assert gate is None
    assert consistent is True


def test_autoplot_projection_rejects_invalid_manifest_plan() -> None:
    forged_plan = {"kind": "forged"}

    payload, gate, consistent = summary_module._autoplot_figure_plan_projection(
        manifest={"resolved_figure_plan": forged_plan},
        one_step={"resolved_figure_plan": forged_plan},
    )

    assert payload is None
    assert gate is not None and gate["valid"] is False
    assert consistent is False


def test_autoplot_summary_exposes_full_plan_and_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _completed_plan(tmp_path)
    evidence = _evidence(tmp_path, plan=plan, one_step_plan=plan.to_payload())
    _stub_summary_dependencies(monkeypatch, evidence=evidence)

    summary = summary_module.build_autoplot_summary(
        {},
        _validated_envelope_ready=lambda *_args, **_kwargs: True,
    )

    assert summary["ready_to_use"] is True
    assert summary["figure_plan"] == plan.to_payload()
    assert summary["figure_plan_gate"]["complete"] is True
    assert summary["integrity"]["figure_plan_projection_consistent"] is True


def test_autoplot_summary_fails_when_one_step_drops_the_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _completed_plan(tmp_path)
    evidence = _evidence(tmp_path, plan=plan, one_step_plan=None)
    _stub_summary_dependencies(monkeypatch, evidence=evidence)

    summary = summary_module.build_autoplot_summary(
        {},
        _validated_envelope_ready=lambda *_args, **_kwargs: True,
    )

    assert summary["state"] == "needs_rule_repair"
    assert summary["ready_to_use"] is False
    assert summary["integrity"]["figure_plan_projection_consistent"] is False
    assert "resolved_figure_plan_projection_mismatch" in summary["integrity"][
        "reasons"
    ]


@pytest.mark.parametrize(
    (
        "repair_value",
        "confirmation_value",
        "expected_repair",
        "expected_confirmation",
    ),
    [
        (["repair_a"], ["confirm_a"], ["repair_a"], ["confirm_a"]),
        ("repair_a", {"confirm_a": True}, [], []),
    ],
)
def test_autoplot_summary_normalizes_envelope_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repair_value: object,
    confirmation_value: object,
    expected_repair: list[str],
    expected_confirmation: list[str],
) -> None:
    plan = _completed_plan(tmp_path)
    evidence = _evidence(
        tmp_path,
        plan=plan,
        one_step_plan=plan.to_payload(),
        validated_envelope={
            "repair_reasons": repair_value,
            "confirmation_reasons": confirmation_value,
        },
    )
    _stub_summary_dependencies(monkeypatch, evidence=evidence)

    summary = summary_module.build_autoplot_summary(
        {},
        _validated_envelope_ready=lambda *_args, **_kwargs: True,
    )

    assert summary["validated_envelope"]["repair_reasons"] == expected_repair
    assert (
        summary["validated_envelope"]["confirmation_reasons"]
        == expected_confirmation
    )


def test_autoplot_summary_passes_predicate_inputs_once_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _completed_plan(tmp_path)
    validated_envelope = {"repair_reasons": ["repair_a"]}
    render_request = {"template": "point_line"}
    evidence = _evidence(
        tmp_path,
        plan=plan,
        one_step_plan=plan.to_payload(),
        validated_envelope=validated_envelope,
        render_request=render_request,
    )
    _stub_summary_dependencies(monkeypatch, evidence=evidence)
    calls: list[tuple[object, object]] = []
    one_step_input = {"nested": {"sentinel": True}}
    one_step_before = deepcopy(one_step_input)
    evidence_before = deepcopy(
        {
            "manifest": evidence.manifest,
            "one_step": evidence.effective_one_step,
            "validated_envelope": evidence.validated_envelope,
            "render_request": evidence.render_request,
        }
    )

    def envelope_ready(payload: object, *, render_request: object) -> bool:
        calls.append((payload, render_request))
        return True

    summary_module.build_autoplot_summary(
        one_step_input,
        _validated_envelope_ready=envelope_ready,
    )

    assert calls == [(validated_envelope, render_request)]
    assert one_step_input == one_step_before
    assert {
        "manifest": evidence.manifest,
        "one_step": evidence.effective_one_step,
        "validated_envelope": evidence.validated_envelope,
        "render_request": evidence.render_request,
    } == evidence_before


def _completed_plan(tmp_path: Path) -> ResolvedFigurePlan:
    artifacts = (
        tmp_path / "figure.vsz",
        tmp_path / "figure.pdf",
        tmp_path / "figure_300dpi.tiff",
    )
    for artifact in artifacts:
        artifact.write_bytes(b"fixture")
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
    return ResolvedFigurePlan(
        rule_id="impact_metric",
        selection_policy="fixture",
        primary_figure_id=task.figure_id,
        tasks=(task,),
        outcomes=(
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=tuple(str(path) for path in artifacts),
            ),
        ),
    )


def _manifest(plan: ResolvedFigurePlan) -> dict[str, Any]:
    payload = plan.to_payload()
    return {
        "kind": "sciplot_run",
        "semantic": {"rule_id": plan.rule_id},
        "request": {"rule_id": plan.rule_id},
        "resolved_figure_plan": payload,
        "result": {
            "resolved_figure_plan": payload,
        },
        "study_model": {
            "run": {
                "resolved_figure_plan": payload,
            }
        },
    }


def _evidence(
    tmp_path: Path,
    *,
    plan: ResolvedFigurePlan,
    one_step_plan: object | None,
    validated_envelope: dict[str, Any] | None = None,
    render_request: dict[str, Any] | None = None,
) -> SimpleNamespace:
    run_output = tmp_path / "run"
    run_output.mkdir()
    delivery_path = run_output / "delivery"
    delivery_path.mkdir()
    status_path = run_output / "one_step_status.json"
    manifest_path = run_output / "manifest.json"
    status_path.write_text("{}\n", encoding="utf-8")
    manifest_path.write_text("{}\n", encoding="utf-8")
    one_step: dict[str, Any] = {
        "state": "ready",
        "delivery_package": {"path": str(delivery_path), "complete": True},
    }
    if one_step_plan is not None:
        one_step["resolved_figure_plan"] = one_step_plan
    manifest = {
        **_manifest(plan),
        "one_step": one_step,
        "state": "ready",
    }
    return SimpleNamespace(
        run_output=run_output,
        project_dir=tmp_path,
        status_path=status_path,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_one_step=one_step,
        effective_one_step=one_step,
        status_valid=True,
        manifest_valid=True,
        preparation_state_claims=("ready",),
        publish_state_claims=("ready",),
        manifest_state="ready",
        reported_state="ready",
        persisted_state="ready",
        reported_payload_state="ready",
        delivery_package=one_step["delivery_package"],
        manifest_delivery_package=one_step["delivery_package"],
        persisted_status=one_step,
        figure_qa={
            "status": "passed",
            "qa_status": "passed",
            "needs_ai_intervention": False,
        },
        intervention={},
        validated_envelope=(
            validated_envelope if validated_envelope is not None else {}
        ),
        render_request=render_request if render_request is not None else {},
        reported_result={"request_path": str(tmp_path / "plot_request.json")},
        route_package=lambda: {},
    )


def _stub_summary_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    evidence: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        summary_module.AutoplotRunEvidence,
        "load",
        classmethod(lambda _cls, _result: evidence),
    )
    monkeypatch.setattr(
        summary_module,
        "_manifest_publish_integrity",
        lambda _manifest: {
            "valid": True,
            "package_contract_complete": True,
            "expected": {"ready_to_use": True},
        },
    )
    monkeypatch.setattr(
        summary_module,
        "verify_output_package_contract",
        lambda *_args, **_kwargs: {"passed": True},
    )
    monkeypatch.setattr(
        summary_module,
        "verify_delivery_package",
        lambda *_args, **_kwargs: {"passed": True},
    )
    monkeypatch.setattr(
        summary_module,
        "requested_delivery_root",
        lambda *_args, **_kwargs: Path(evidence.delivery_package["path"]),
    )
