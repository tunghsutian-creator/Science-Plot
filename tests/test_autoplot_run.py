from __future__ import annotations

import json
from pathlib import Path

import pytest

import sciplot_core.autoplot.run as run_module
from sciplot_core.materials_rules import get_rule


_AUTOPLOT_V2_RUN_FIELDS = {
    "kind",
    "version",
    "state",
    "ready_to_use",
    "project_dir",
    "run_output",
    "request_path",
    "manifest",
    "one_step_status",
    "delivery",
    "delivery_complete",
    "delivery_recorded_complete",
    "review_html",
    "revision_brief",
    "route",
    "figure_plan",
    "figure_plan_gate",
    "quality",
    "validated_envelope",
    "integrity",
    "token_policy",
    "codex_handoff",
    "summary_path",
}


def test_run_autoplot_forwards_request_and_persists_exact_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "source.csv"
    input_path.write_text("x,y\n1,2\n", encoding="utf-8")
    output_root = tmp_path / "outputs"
    delivery_root = tmp_path / "delivery"
    run_output = output_root / "project" / "run"
    one_step_result = {"state": "ready", "result": {"figure": "figure.pdf"}}
    captured: dict[str, object] = {}
    rule = get_rule("impact_metric")
    registry = object()
    projection_calls: list[tuple[object, object]] = []

    monkeypatch.setattr(run_module, "get_rule", lambda _rule_id: rule)
    monkeypatch.setattr(
        run_module,
        "load_validated_envelope_registry",
        lambda: registry,
    )

    def fake_invocation_projection(*, rule: object, registry: object):
        projection_calls.append((rule, registry))
        return {"availability": "ready", "reason_codes": []}

    monkeypatch.setattr(
        run_module,
        "current_rule_invocation_contract_payload",
        fake_invocation_projection,
    )

    def fake_run_one_step(source: Path, **kwargs: object) -> dict[str, object]:
        captured["source"] = source
        captured.update(kwargs)
        return one_step_result

    def fake_build_summary(result: dict[str, object]) -> dict[str, object]:
        assert result is one_step_result
        return {
            "kind": "sciplot_autoplot_result",
            "state": "ready",
            "ready_to_use": True,
            "run_output": str(run_output),
            "nested": {"value": 1},
        }

    monkeypatch.setattr(run_module, "run_one_step", fake_run_one_step)
    monkeypatch.setattr(run_module, "build_autoplot_summary", fake_build_summary)

    result = run_module.run_autoplot(
        input_path,
        output_root=output_root,
        project_name="project",
        delivery_root=delivery_root,
        rule_id="impact_metric",
        template="box_strip",
    )

    summary_path = run_output / "autoplot_summary.json"
    assert captured == {
        "source": input_path,
        "output_root": output_root,
        "project_name": "project",
        "delivery_root": delivery_root,
        "rule_id": "impact_metric",
        "template": "box_strip",
    }
    assert projection_calls == [(rule, registry)]
    assert result["summary_path"] == str(summary_path)
    assert json.loads(summary_path.read_text(encoding="utf-8")) == result


def test_run_autoplot_current_rule_rejects_missing_source_before_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "source-does-not-exist.csv"
    output_root = tmp_path / "outputs"

    monkeypatch.setattr(
        run_module,
        "current_rule_invocation_contract_payload",
        lambda **_kwargs: {"availability": "ready", "reason_codes": []},
    )

    def forbidden_work(*_args: object, **_kwargs: object) -> None:
        pytest.fail("missing source reached project creation")

    monkeypatch.setattr(run_module, "run_one_step", forbidden_work)

    with pytest.raises(ValueError, match="^Input not found: "):
        run_module.run_autoplot(
            input_path,
            output_root=output_root,
            rule_id="impact_metric",
        )

    assert not output_root.exists()


@pytest.mark.parametrize(
    "reason_codes",
    [
        ["validated_envelope_missing"],
        [
            "certified_rule_contract_sha256_mismatch",
            "certified_rule_semantic_contract_sha256_mismatch",
        ],
    ],
)
def test_run_autoplot_returns_v2_rule_repair_without_project_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason_codes: list[str],
) -> None:
    input_path = tmp_path / "source-does-not-exist.csv"
    output_root = tmp_path / "outputs"
    rule = get_rule("swelling_curve")
    registry = object()

    monkeypatch.setattr(run_module, "get_rule", lambda _rule_id: rule)
    monkeypatch.setattr(
        run_module,
        "load_validated_envelope_registry",
        lambda: registry,
    )

    def fake_invocation_projection(*, rule: object, registry: object):
        return {
            "availability": "needs_rule_repair",
            "reason_codes": list(reason_codes),
        }

    def forbidden_work(*_args: object, **_kwargs: object) -> None:
        pytest.fail("rule preflight must stop before project or summary writes")

    monkeypatch.setattr(
        run_module,
        "current_rule_invocation_contract_payload",
        fake_invocation_projection,
    )
    monkeypatch.setattr(run_module, "run_one_step", forbidden_work)
    monkeypatch.setattr(run_module, "atomic_write_json", forbidden_work)

    result = run_module.run_autoplot(
        input_path,
        output_root=output_root,
        project_name="blocked",
        rule_id=rule.rule_id,
    )

    assert set(result) == _AUTOPLOT_V2_RUN_FIELDS
    assert result["kind"] == "sciplot_autoplot_result"
    assert result["version"] == 2
    assert result["state"] == "needs_rule_repair"
    assert result["ready_to_use"] is False
    assert all(
        result[field] is None
        for field in (
            "project_dir",
            "run_output",
            "request_path",
            "manifest",
            "one_step_status",
            "delivery",
            "review_html",
            "revision_brief",
            "summary_path",
        )
    )
    assert result["delivery_complete"] is False
    assert result["delivery_recorded_complete"] is False
    assert set(result["route"]) == {
        "mode",
        "source_kind",
        "semantic_family",
        "rule_id",
        "confidence_band",
        "recipe",
        "template",
        "figure_size",
        "exports",
    }
    assert result["figure_plan"] == {
        "complete": False,
        "status": "needs_rule_repair",
    }
    assert result["figure_plan_gate"] == {
        "valid": False,
        "complete": False,
        "status": "needs_rule_repair",
    }
    assert set(result["quality"]) == {
        "status",
        "qa_status",
        "layout_review_mode",
        "issue_ids",
        "quality_actions",
        "image_review_required",
    }
    assert result["validated_envelope"] == {
        "state": "needs_rule_repair",
        "rule_id": rule.rule_id,
        "ready_without_ai": False,
        "contract_current": False,
        "evidence": None,
        "repair_reasons": reason_codes,
        "confirmation_reasons": [],
    }
    assert set(result["integrity"]) == {
        "state_consistent",
        "preparation_state_consistent",
        "publish_state_consistent",
        "qa_ready",
        "validated_envelope_ready",
        "manifest_exists",
        "manifest_valid",
        "one_step_status_exists",
        "one_step_status_valid",
        "one_step_manifest_consistent",
        "figure_plan_projection_consistent",
        "delivery_path_exists",
        "delivery_path_canonical",
        "delivery_package_consistent",
        "delivery_verification",
        "publish_state_valid",
        "publish_state",
        "package_contract_verification",
        "reasons",
    }
    assert result["integrity"]["reasons"] == reason_codes
    assert set(result["token_policy"]) == {
        "default_codex_context",
        "codex_reads_images_by_default",
        "image_review_required",
        "image_review_allowed_only_when",
        "codex_role",
    }
    assert set(result["codex_handoff"]) == {
        "required",
        "read_first",
        "image_review_required",
        "intervention_package",
    }
    assert result["codex_handoff"]["required"] is True
    assert not output_root.exists()
