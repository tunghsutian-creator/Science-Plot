from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sciplot_core import workflow
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_RECIPE,
    DMA_TEMPERATURE_RULE_ID,
)
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureTask,
    ResolvedFigurePlan,
    resolve_figure_plan,
)
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import get_rule
from sciplot_core.readiness.render_request_contract import (
    _render_request_policy_evaluation,
    validated_render_request_policy_payload,
)
from sciplot_core.semantic import classify_source
from sciplot_core.workflow import request_rendering
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent


EXPECTED_SAMPLE_ORDER = [
    "PBAT",
    "5 wt% UDC 2",
    "5 wt% UDC 3",
    "5 wt% UDC 4",
]
EXPECTED_POINT_COUNTS = [613, 1133, 1128, 1200]


def _fixture() -> Path:
    source = resolve_fixture_path(
        str(get_rule(DMA_TEMPERATURE_RULE_ID).fixture_path or "")
    )
    assert source.is_file()
    return source


def _semantic() -> dict[str, Any]:
    return classify_source(
        _fixture(),
        requested_rule_id=DMA_TEMPERATURE_RULE_ID,
    )


def _plan(source: Path | None = None) -> ResolvedFigurePlan:
    resolved = resolve_figure_plan(
        rule_id=DMA_TEMPERATURE_RULE_ID,
        template="point_line",
        study_model={},
        input_path=source or _fixture(),
        request={},
    )
    assert resolved is not None
    return resolved


def _named_request(plan: ResolvedFigurePlan) -> dict[str, Any]:
    return {
        "recipe": DMA_TEMPERATURE_RECIPE,
        "rule_id": DMA_TEMPERATURE_RULE_ID,
        "exports": ["pdf", "tiff_300"],
        "resolved_figure_plan": plan.to_payload(),
    }


def _execute_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    request: dict[str, Any],
    semantic: dict[str, Any] | None = None,
    input_path: Path | None = None,
) -> None:
    output_dir = tmp_path / "must_not_exist"
    route = resolve_workflow_route_intent(request)
    monkeypatch.setattr(
        request_rendering,
        "prepare_semantic_source",
        lambda *_args, **_kwargs: pytest.fail(
            "conflicting named recipe reached semantic preparation"
        ),
    )
    with pytest.raises(ValueError, match="dma_named_recipe|dma_temperature"):
        request_rendering.execute_request_render(
            request=request,
            route_intent=route,
            semantic=semantic or _semantic(),
            study_model={},
            input_path=input_path or _fixture(),
            output_dir=output_dir,
            base_dir=tmp_path,
            transform_steps=[],
        )
    assert not output_dir.exists()


def test_dma_named_recipe_preflight_binds_the_exact_plan() -> None:
    plan = _plan()
    request = _named_request(plan)

    binding = request_rendering.bind_dma_named_recipe_request(
        requested_recipe=DMA_TEMPERATURE_RECIPE,
        request=request,
        semantic=_semantic(),
        plan=plan,
        input_path=_fixture(),
    ).to_payload()

    assert binding["route"] == "recipe"
    assert binding["recipe"] == DMA_TEMPERATURE_RECIPE
    assert binding["rule_id"] == DMA_TEMPERATURE_RULE_ID
    assert binding["plan_id"] == plan.plan_id
    assert binding["plan_sha256"] == plan.plan_sha256
    assert binding["source_sha256"] == plan.source_sha256
    assert binding["sample_order"] == EXPECTED_SAMPLE_ORDER
    assert binding["point_counts"] == EXPECTED_POINT_COUNTS
    assert binding["metric_binding"] == {
        "x_metric": "temperature",
        "y_metric": "storage_modulus",
    }
    assert binding["units"] == {
        "canonical_temperature": "°C",
        "canonical_modulus": "Pa",
        "display_modulus": "MPa",
    }
    assert binding["template"] == "point_line"
    assert binding["selection_authority"] == "resolved_figure_plan"


@pytest.mark.parametrize(
    ("request_patch", "reason"),
    [
        ({"template": "curve"}, "plan_conflict"),
        ({"y_metric": "loss_factor"}, "plan_conflict"),
        ({"display_y_unit": "Pa"}, "plan_conflict"),
        ({"series_order": list(reversed(EXPECTED_SAMPLE_ORDER))}, "plan_conflict"),
        ({"series_encoding_contract": {}}, "terminal_evidence_forged"),
        ({"render_options": {"y_min": 1.0}}, "axis_visibility_conflict"),
    ],
)
def test_dma_named_recipe_conflicts_fail_before_semantic_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_patch: dict[str, Any],
    reason: str,
) -> None:
    request = {**_named_request(_plan()), **request_patch}
    output_dir = tmp_path / "must_not_exist"
    route = resolve_workflow_route_intent(request)
    monkeypatch.setattr(
        request_rendering,
        "prepare_semantic_source",
        lambda *_args, **_kwargs: pytest.fail(
            "conflicting named recipe reached semantic preparation"
        ),
    )

    with pytest.raises(ValueError, match=f"dma_named_recipe_{reason}"):
        request_rendering.execute_request_render(
            request=request,
            route_intent=route,
            semantic=_semantic(),
            study_model={},
            input_path=_fixture(),
            output_dir=output_dir,
            base_dir=tmp_path,
            transform_steps=[],
        )

    assert not output_dir.exists()


def test_dma_named_recipe_rejects_forged_task_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    task = plan.tasks[0]
    forged_task = FigureTask.with_metric_binding(
        figure_id=task.figure_id,
        order=task.order,
        title=task.title,
        metric_binding=CartesianMetricBinding(
            x_metric="temperature",
            y_metric="loss_factor",
        ),
        template=task.template,
        artifact_stem=task.artifact_stem,
        document_stem=task.document_stem,
        sample_order=task.sample_order,
        replicate_counts=task.replicate_counts,
    )
    forged_plan = ResolvedFigurePlan.planned(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=(forged_task,),
        source_sha256=plan.source_sha256,
    )

    _execute_without_writes(
        tmp_path,
        monkeypatch,
        request=_named_request(forged_plan),
    )


def test_dma_named_recipe_rejects_source_drift_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed_source = tmp_path / _fixture().name
    changed_source.write_bytes(_fixture().read_bytes())
    changed_source.write_text(
        changed_source.read_text(encoding="utf-8").replace(
            "60.37265",
            "60.37264",
            1,
        ),
        encoding="utf-8",
    )

    _execute_without_writes(
        tmp_path,
        monkeypatch,
        request=_named_request(_plan()),
        input_path=changed_source,
    )


def test_workflow_discards_staging_tree_on_named_recipe_conflict(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "conflicting_request.json"
    output_dir = tmp_path / "must_not_exist"
    request_path.write_text(
        json.dumps(
            {
                "recipe": DMA_TEMPERATURE_RECIPE,
                "input": str(_fixture()),
                "output": str(output_dir),
                "rule_id": DMA_TEMPERATURE_RULE_ID,
                "exports": ["pdf", "tiff_300"],
                "render_options": {"y_min": 1.0},
                "explicit_render_option_keys": ["y_min"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="dma_named_recipe_axis_visibility_conflict",
    ):
        workflow.run_request(request_path)

    assert output_dir.is_dir()
    assert (output_dir / "raw").is_dir()
    assert (output_dir / "request_snapshot.json").is_file()
    for forbidden in ("processed", "figures", "manifest.json", "delivery"):
        assert not (output_dir / forbidden).exists()


def test_only_dma_certifies_the_exact_named_recipe_route() -> None:
    dma_rule = get_rule(DMA_TEMPERATURE_RULE_ID)
    dma_policy = validated_render_request_policy_payload(dma_rule)
    assert dma_policy["allowed_routes"] == ["auto", "recipe"]
    render_request = {
        "kind": "sciplot_render_request",
        "version": 1,
        "path": "/tmp/request.json",
        "rule_id": DMA_TEMPERATURE_RULE_ID,
        "recipe": DMA_TEMPERATURE_RECIPE,
        "template": None,
        "exports": ["pdf", "tiff_300"],
        "render_engine": "veusz",
        "figure_size": "60x55",
        "render_options": {},
        "split_policy": {},
        "series_order": [],
        "explicit_render_option_keys": [],
    }
    contract, repairs, confirmations = _render_request_policy_evaluation(
        dma_rule,
        render_request,
    )
    assert repairs == []
    assert confirmations == []
    assert contract is not None
    assert contract["route"] == "recipe"
    assert contract["effective_recipe"] == DMA_TEMPERATURE_RECIPE
    assert contract["effective_template"] == "point_line"

    other_rule = get_rule("rheology_frequency_sweep")
    other_request = {**render_request, "rule_id": other_rule.rule_id}
    _contract, _repairs, other_confirmations = _render_request_policy_evaluation(
        other_rule,
        other_request,
    )
    assert other_confirmations == ["render_route_outside_validated_policy"]
    assert validated_render_request_policy_payload(other_rule)["allowed_routes"] == [
        "auto"
    ]


def test_rheology_dma_cannot_consume_an_unbounded_non_dma_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dma_task = _plan().tasks[0]
    other_plan = ResolvedFigurePlan.planned(
        rule_id="rheology_temperature_sweep",
        selection_policy="unbounded_test_plan",
        primary_figure_id=dma_task.figure_id,
        tasks=(dma_task,),
    )
    request = {
        "recipe": DMA_TEMPERATURE_RECIPE,
        "rule_id": other_plan.rule_id,
        "resolved_figure_plan": other_plan.to_payload(),
    }
    route = resolve_workflow_route_intent(request)
    monkeypatch.setattr(
        request_rendering,
        "run_recipe",
        lambda *_args, **_kwargs: pytest.fail("unbounded plan reached recipe"),
    )

    with pytest.raises(ValueError, match="workflow_recipe_figure_plan_unsupported"):
        request_rendering.execute_request_render(
            request=request,
            route_intent=route,
            semantic={"rule_id": other_plan.rule_id},
            study_model={},
            input_path=_fixture(),
            output_dir=tmp_path / "must_not_exist",
            base_dir=tmp_path,
            transform_steps=[],
        )

    assert not (tmp_path / "must_not_exist").exists()


@pytest.mark.comprehensive
def test_dma_auto_and_named_recipe_have_identical_terminal_evidence(
    tmp_path: Path,
) -> None:
    manifests: dict[str, dict[str, Any]] = {}
    for route, recipe in (
        ("auto", "auto"),
        ("recipe", DMA_TEMPERATURE_RECIPE),
    ):
        request_path = tmp_path / f"{route}_request.json"
        output_dir = tmp_path / f"{route}_output"
        request_path.write_text(
            json.dumps(
                {
                    "recipe": recipe,
                    "input": str(_fixture()),
                    "output": str(output_dir),
                    "rule_id": DMA_TEMPERATURE_RULE_ID,
                    "exports": ["pdf", "tiff_300"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        manifests[route] = workflow.run_request(request_path)

    auto = manifests["auto"]
    named = manifests["recipe"]
    assert auto["route"] == "auto"
    assert named["route"] == "recipe"
    assert auto["final_recipe"] == named["final_recipe"] == DMA_TEMPERATURE_RECIPE
    auto_plan = ResolvedFigurePlan.from_payload(auto["resolved_figure_plan"])
    named_plan = ResolvedFigurePlan.from_payload(named["resolved_figure_plan"])
    assert auto_plan.plan_id == named_plan.plan_id
    assert auto_plan.plan_sha256 == named_plan.plan_sha256
    assert auto_plan.status == named_plan.status == "ready"

    auto_evidence = auto["result"]["dma_temperature_execution_evidence"]
    named_evidence = named["result"]["dma_temperature_execution_evidence"]
    assert auto_evidence == named_evidence
    assert auto_evidence["finite_point_count"] == 4074
    assert auto_evidence["negative_display_point_count"] == 1
    assert auto_evidence["sample_order"] == EXPECTED_SAMPLE_ORDER
    assert auto_evidence["point_counts"] == EXPECTED_POINT_COUNTS
    binding = named["result"]["named_recipe_plan_binding"]
    assert binding["plan_id"] == named_plan.plan_id
    assert binding["source_sha256"] == named_plan.source_sha256
    assert "named_recipe_plan_binding" not in auto["result"]
    auto_operations = [step["operation"] for step in auto["transform_ledger"]["steps"]]
    named_operations = [
        step["operation"] for step in named["transform_ledger"]["steps"]
    ]
    assert auto_operations == named_operations
    assert auto_operations.count("extract_and_convert_dma_temperature_curves") == 1

    for manifest in manifests.values():
        result = manifest["result"]
        assert len(result["veusz_documents"]) == 1
        assert len(result["veusz_specs"]) == 1
        assert len([path for path in result["outputs"] if path.endswith(".pdf")]) == 1
        assert len([path for path in result["outputs"] if path.endswith(".tiff")]) == 1
        assert all(
            Path(path).is_file()
            for path in [
                *result["veusz_documents"],
                *result["veusz_specs"],
                *result["outputs"],
            ]
        )
        assert manifest["qa"]["status"] == "passed"
        assert manifest["delivery_package"]["complete"] is True
        assert manifest["publish_gates"]["passed"] is True

    assert file_sha256(Path(auto["result"]["processed_source"])) == file_sha256(
        Path(named["result"]["processed_source"])
    )
    named_report = Path(named["output"]) / "analysis_report.md"
    assert "- Route: `recipe`" in named_report.read_text(encoding="utf-8")
