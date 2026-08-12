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
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
    ScientificTransformContract,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_source import (
    ScientificSourceResolutionError,
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


def test_temperature_preview_keeps_plan_shape_without_fabricating_transform() -> None:
    rule = get_rule("rheology_temperature_sweep")
    source = resolve_fixture_path(str(rule.fixture_path or ""))

    payload = preview_module.build_plan_preview(
        source,
        request={"rule_id": rule.rule_id, "template": rule.template},
    )

    assert set(payload) == {
        "kind",
        "version",
        "status",
        "source",
        "rule_id",
        "template",
        "resolved_figure_plan",
        "scientific_transform",
        "blocker",
    }
    assert payload["status"] == "planned"
    assert payload["scientific_transform"] is None
    assert payload["blocker"] is None
    plan = payload["resolved_figure_plan"]
    assert plan is not None
    assert plan["rule_id"] == rule.rule_id
    assert len(plan["tasks"]) == 2


def test_plan_preview_returns_one_complete_planned_payload_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mechanical"
    source.write_text("source", encoding="utf-8")
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
        "scientific_transform": None,
        "blocker": None,
    }


def test_plan_preview_marks_non_figure_plan_source_not_applicable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "generic.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(
        preview_module,
        "classify_source",
        lambda *_args, **_kwargs: {
            "semantic_family": "generic_curve",
            "template": "curve",
            "needs_ai_intervention": True,
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
    assert payload["scientific_transform"] is None
    assert payload["blocker"] is None


@pytest.mark.parametrize(
    ("rule_id", "reason_code", "payload_rule_id"),
    [
        ("", "plan_rule_invalid", None),
        (" ", "plan_rule_invalid", None),
        ("not_a_rule", "plan_rule_unknown", "not_a_rule"),
    ],
)
def test_plan_preview_blocks_invalid_rule_before_source_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rule_id: str,
    reason_code: str,
    payload_rule_id: str | None,
) -> None:
    def unexpected_classification(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid rule reached source classification")

    monkeypatch.setattr(
        preview_module,
        "classify_source",
        unexpected_classification,
    )

    payload = preview_module.build_plan_preview(
        tmp_path / "missing.csv",
        request={"rule_id": rule_id},
    )

    assert payload["status"] == "blocked"
    assert payload["rule_id"] == payload_rule_id
    assert payload["blocker"] is not None
    assert payload["blocker"]["reason_code"] == reason_code


def test_plan_preview_blocks_unsupported_template_before_source_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_classification(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unsupported template reached source classification")

    monkeypatch.setattr(
        preview_module,
        "classify_source",
        unexpected_classification,
    )

    payload = preview_module.build_plan_preview(
        tmp_path / "missing.csv",
        request={"rule_id": "tensile_curve", "template": "polar_curve"},
    )

    assert payload["status"] == "blocked"
    assert payload["rule_id"] == "tensile_curve"
    assert payload["template"] == "polar_curve"
    assert payload["blocker"] is not None
    assert payload["blocker"]["reason_code"] == "plan_template_unsupported"


def test_plan_preview_blocks_uncertified_rule_before_source_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasons = [
        "certified_rule_contract_sha256_mismatch",
        "certified_rule_semantic_contract_sha256_mismatch",
    ]

    def unexpected_classification(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("uncertified rule reached source classification")

    monkeypatch.setattr(
        preview_module,
        "load_validated_envelope_registry",
        lambda: object(),
    )
    monkeypatch.setattr(
        preview_module,
        "current_rule_invocation_contract_payload",
        lambda **_kwargs: {
            "availability": "needs_rule_repair",
            "reason_codes": reasons,
        },
    )
    monkeypatch.setattr(
        preview_module,
        "classify_source",
        unexpected_classification,
    )

    payload = preview_module.build_plan_preview(
        tmp_path / "missing.csv",
        request={"rule_id": "tensile_curve", "template": "curve"},
    )

    assert payload["status"] == "blocked"
    assert payload["blocker"] == {
        "reason_code": reasons[0],
        "message": (
            "Material rule `tensile_curve` is not available for deterministic "
            "invocation: " + ", ".join(reasons) + "."
        ),
    }


def test_plan_preview_blocks_missing_source_without_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_classification(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("missing source reached classification")

    monkeypatch.setattr(
        preview_module,
        "classify_source",
        unexpected_classification,
    )

    payload = preview_module.build_plan_preview(
        tmp_path / "missing.csv",
        request={"rule_id": "tensile_curve", "template": "curve"},
    )

    assert payload["status"] == "blocked"
    assert payload["blocker"] == {
        "reason_code": "plan_source_not_found",
        "message": f"Input not found: {tmp_path / 'missing.csv'}",
    }


def test_plan_preview_blocks_expected_source_inspection_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("source", encoding="utf-8")

    def unreadable(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("source is unreadable")

    monkeypatch.setattr(preview_module, "classify_source", unreadable)

    payload = preview_module.build_plan_preview(source, request={})

    assert payload["status"] == "blocked"
    assert payload["blocker"] == {
        "reason_code": "plan_source_inspection_failed",
        "message": "source is unreadable",
    }


def test_plan_preview_blocks_reported_source_inspection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("source", encoding="utf-8")
    monkeypatch.setattr(
        preview_module,
        "classify_source",
        lambda *_args, **_kwargs: {
            "semantic_family": "unknown",
            "template": "curve",
            "vendor_error": "Could not recognize this source.",
        },
    )

    payload = preview_module.build_plan_preview(source, request={})

    assert payload["status"] == "blocked"
    assert payload["blocker"] == {
        "reason_code": "plan_source_inspection_failed",
        "message": "Could not recognize this source.",
    }


def test_plan_preview_does_not_mask_classification_programming_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("source", encoding="utf-8")

    def broken_classifier(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("classifier invariant broke")

    monkeypatch.setattr(preview_module, "classify_source", broken_classifier)

    with pytest.raises(RuntimeError, match="classifier invariant broke"):
        preview_module.build_plan_preview(source, request={})


def test_plan_preview_projects_one_known_resolution_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mechanical"
    source.write_text("source", encoding="utf-8")
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


def test_scientific_source_keeps_its_figure_plan_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "dma.csv"
    source.write_text("source", encoding="utf-8")
    monkeypatch.setattr(
        preview_module,
        "classify_source",
        lambda *_args, **_kwargs: {
            "rule_id": "dma_temperature_sweep",
            "semantic_family": "dma_temperature_sweep",
            "template": "point_line",
        },
    )
    monkeypatch.setattr(
        preview_module,
        "study_model_from_request",
        lambda **_kwargs: {},
    )

    def blocked_source(*_args: object, **_kwargs: object) -> None:
        raise ScientificSourceResolutionError(
            "dma_temperature_source_contract_invalid",
            "DMA source contract is invalid.",
        )

    monkeypatch.setattr(
        preview_module,
        "resolve_scientific_source",
        blocked_source,
    )
    payload = preview_module.build_plan_preview(
        source,
        request={"rule_id": "dma_temperature_sweep"},
    )

    assert payload["status"] == "blocked"
    assert payload["blocker"] == {
        "reason_code": "dma_temperature_source_contract_invalid",
        "message": "DMA source contract is invalid.",
    }


def test_stress_plan_reuses_one_resolved_contract_and_forwards_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "relaxation.csv"
    source.write_text("source", encoding="utf-8")
    rule = get_rule("rheology_stress_relaxation")
    requested_order = [
        f"{source.stem}_{position}" for position in ("second", "first")
    ]
    contract = _minimal_transform_contract(requested_order)
    calls: list[tuple[Path, object]] = []
    import sciplot_core.semantic_sources.stress_relaxation_transform as transform

    monkeypatch.setattr(
        preview_module,
        "classify_source",
        lambda *_args, **_kwargs: {
            "rule_id": "rheology_stress_relaxation",
            "semantic_family": "rheology_stress_relaxation",
            "template": "curve",
        },
    )
    monkeypatch.setattr(preview_module, "study_model_from_request", lambda **_kwargs: {})
    monkeypatch.setattr(
        preview_module,
        "resolve_figure_plan",
        lambda **_kwargs: pytest.fail(
            "resolved stress source must supply its FigurePlan"
        ),
    )

    def fake_resolve(path: Path, *, series_order: object) -> ResolvedScientificTransform:
        calls.append((path, series_order))
        assert isinstance(series_order, list)
        series = tuple(
            CurveSeriesPayload(
                sample=sample,
                x_label=rule.x_axis.canonical_label,
                x_unit=rule.x_axis.canonical_unit,
                y_label=rule.y_axis.canonical_label,
                y_unit=rule.y_axis.canonical_unit,
                points=((float(index), float(len(series_order) - index)),),
            )
            for index, sample in enumerate(series_order, start=1)
        )
        return ResolvedScientificTransform(
            series=series,
            contract=contract,
            selected_sources=(path,),
        )

    monkeypatch.setattr(transform, "resolve_stress_relaxation_transform", fake_resolve)

    payload = preview_module.build_plan_preview(
        source,
        request={
            "rule_id": "rheology_stress_relaxation",
            "series_order": requested_order,
        },
    )

    assert calls == [(source.resolve(), requested_order)]
    assert payload["scientific_transform"] == contract.to_payload()
    assert payload["status"] == "planned"
    plan = payload["resolved_figure_plan"]
    assert plan is not None
    assert plan["selection_policy"] == "registered_single_curve"
    assert [task["sample_order"] for task in plan["tasks"]] == [requested_order]


def test_stress_plan_blocks_before_figure_plan_when_transform_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "relaxation.csv"
    source.write_text("source", encoding="utf-8")
    figure_plan_calls = 0
    import sciplot_core.semantic_sources.stress_relaxation_transform as transform

    monkeypatch.setattr(
        preview_module,
        "classify_source",
        lambda *_args, **_kwargs: {
            "rule_id": "rheology_stress_relaxation",
            "semantic_family": "rheology_stress_relaxation",
            "template": "curve",
        },
    )
    monkeypatch.setattr(preview_module, "study_model_from_request", lambda **_kwargs: {})

    def invalid_transform(*_args: object, **_kwargs: object) -> None:
        raise ValueError("anchor missing")

    def figure_plan_sentinel(**_kwargs: Any) -> None:
        nonlocal figure_plan_calls
        figure_plan_calls += 1

    monkeypatch.setattr(transform, "resolve_stress_relaxation_transform", invalid_transform)
    monkeypatch.setattr(preview_module, "resolve_figure_plan", figure_plan_sentinel)

    payload = preview_module.build_plan_preview(
        source,
        request={"rule_id": "rheology_stress_relaxation"},
    )

    assert figure_plan_calls == 0
    assert payload["status"] == "blocked"
    assert payload["scientific_transform"] is None
    assert payload["blocker"] == {
        "reason_code": "stress_relaxation_transform_invalid",
        "message": "anchor missing",
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


def _minimal_transform_contract(
    series_order: list[str],
) -> ScientificTransformContract:
    return ScientificTransformContract(
        semantic_family="rheology_stress_relaxation",
        source_columns=(),
        unit_conversions=(),
        anchor={"scope": "none"},
        normalizer={"scope": "none"},
        x_coordinate_policy={"operation": "identity"},
        retain_anchor=None,
        axis_compatibility={},
        output={
            "x_metric": "time",
            "y_metric": "normalized_stress",
            "series_order": list(series_order),
        },
        selected_sources=(),
    )
