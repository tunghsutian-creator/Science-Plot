from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

from sciplot_core.delivery.plan_binding import (
    DeliveryRecordsMatchPlanPayload,
    delivery_records_match_plan,
)
from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    CartesianMetricBindingPayload,
    FigureOutcome,
    FigureOutcomePayload,
    FigurePlanGateInvalidPayload,
    FigurePlanGatePayload,
    FigurePlanGateValidPayload,
    FigurePlanManifestGatePayload,
    FigurePlanManifestGateValidPayload,
    FigureTask,
    FigureTaskPayload,
    FigureTaskReplicateCountPayload,
    FigureTaskV1Payload,
    FigureTaskV2Payload,
    OrderedMetricsBinding,
    OrderedMetricsBindingPayload,
    ResolvedFigurePlan,
    ResolvedFigurePlanPayload,
    figure_plan_gate,
    figure_plan_manifest_gate,
    finalize_figure_plan_result,
    merge_figure_outcomes,
    outcomes_for_artifact_map,
    request_for_figure_task,
    resolve_figure_plan,
)
from sciplot_core.figure_plan.execution import editable_figure_plan
from sciplot_core.publish_state import build_publish_state
from sciplot_core.study_model import (
    STUDY_MODEL_KIND,
    STUDY_MODEL_VERSION,
    experiment_recommendation_payload,
)


_FREQUENCY_FIGURE_IDS = (
    "storage_modulus_vs_frequency",
    "loss_modulus_vs_frequency",
    "loss_factor_vs_frequency",
    "complex_viscosity_vs_frequency",
)
_FREQUENCY_METRICS = (
    "storage_modulus",
    "loss_modulus",
    "loss_factor",
    "complex_viscosity",
)


def _frequency_study_model() -> dict[str, object]:
    recommendation = experiment_recommendation_payload(
        rule_id="rheology_frequency_sweep"
    )
    return {
        "kind": STUDY_MODEL_KIND,
        "version": STUDY_MODEL_VERSION,
        "figure_queue": [
            {
                **figure,
                "order": order,
                "status": "planned",
            }
            for order, figure in enumerate(
                recommendation["figure_queue"],
                start=1,
            )
        ],
    }


def test_editable_plan_binds_verified_pending_transaction_targets(
    tmp_path: Path,
) -> None:
    task = FigureTask(
        figure_id="impact_strength_by_sample",
        order=1,
        title="Impact strength by sample",
        x_metric="sample",
        y_metric="impact_strength",
        template="bar",
        artifact_stem="impact_strength_by_sample",
        document_stem="impact_strength_by_sample",
    )
    plan = ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    document = tmp_path / "studio" / "document.vsz"
    spec = tmp_path / "studio" / "spec.json"
    entries = [
        {
            "figure_id": task.figure_id,
            "status": "ready",
            "document": str(document),
            "spec": str(spec),
        }
    ]

    before_commit = editable_figure_plan(plan, entries)
    transaction_ready = editable_figure_plan(
        plan,
        entries,
        verified_pending_artifact_targets={document, spec},
    )

    assert before_commit.outcomes[0].status == "unavailable"
    assert transaction_ready.outcomes[0].status == "editable"
    assert transaction_ready.outcomes[0].artifacts == (
        str(document),
        str(spec),
    )


def _frequency_plan(tmp_path: Path) -> ResolvedFigurePlan:
    plan = resolve_figure_plan(
        rule_id="rheology_frequency_sweep",
        template="point_line",
        study_model=_frequency_study_model(),
        input_path=tmp_path / "unused-frequency-source",
        request={},
    )
    assert plan is not None
    return plan


def _delivery_artifacts(
    directory: Path,
    stem: str,
    *,
    include_300dpi_tiff: bool = True,
    include_plain_tiff: bool = False,
) -> tuple[str, ...]:
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = [
        directory / f"{stem}.vsz",
        directory / f"{stem}.pdf",
    ]
    if include_300dpi_tiff:
        artifacts.append(directory / f"{stem}_300dpi.tiff")
    if include_plain_tiff:
        artifacts.append(directory / f"{stem}.tiff")
    for path in artifacts:
        path.write_bytes(b"figure-plan-test")
    return tuple(str(path) for path in artifacts)


def test_public_payload_return_types_are_exact_total_contracts() -> None:
    assert get_type_hints(FigureTask.to_payload)["return"] is FigureTaskPayload
    assert get_type_hints(FigureOutcome.to_payload)["return"] is FigureOutcomePayload
    assert (
        get_type_hints(ResolvedFigurePlan.to_payload)["return"]
        is ResolvedFigurePlanPayload
    )
    assert get_type_hints(figure_plan_gate)["return"] == FigurePlanGatePayload | None
    assert (
        get_type_hints(figure_plan_manifest_gate)["return"]
        == FigurePlanManifestGatePayload | None
    )
    assert (
        get_type_hints(delivery_records_match_plan)["return"]
        == DeliveryRecordsMatchPlanPayload
    )

    assert set(get_args(FigureTaskPayload)) == {
        FigureTaskV1Payload,
        FigureTaskV2Payload,
    }
    for payload_type in (
        FigureTaskV1Payload,
        FigureTaskV2Payload,
        CartesianMetricBindingPayload,
        OrderedMetricsBindingPayload,
        FigureTaskReplicateCountPayload,
        FigureOutcomePayload,
        ResolvedFigurePlanPayload,
        FigurePlanGateInvalidPayload,
        FigurePlanGateValidPayload,
        FigurePlanManifestGateValidPayload,
    ):
        assert payload_type.__optional_keys__ == frozenset()


def test_public_payload_json_shape_and_order_stay_stable() -> None:
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="x",
        y_metric="y",
        template="point_line",
        artifact_stem="figure_a",
        document_stem="figure_a",
        conditions=("condition_a",),
        condition_labels=("Condition A",),
        sample_order=("sample_a",),
        replicate_counts=(("sample_a", 2),),
    )
    outcome = FigureOutcome(figure_id="figure_a", status="pending")
    plan = ResolvedFigurePlan(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id="figure_a",
        tasks=(task,),
        outcomes=(outcome,),
        source_sha256="a" * 64,
    )
    expected_task = {
        "kind": "sciplot_figure_task",
        "version": 1,
        "figure_id": "figure_a",
        "order": 1,
        "selected": True,
        "title": "Figure A",
        "x_metric": "x",
        "y_metric": "y",
        "template": "point_line",
        "artifact_stem": "figure_a",
        "document_stem": "figure_a",
        "conditions": ["condition_a"],
        "condition_labels": ["Condition A"],
        "sample_order": ["sample_a"],
        "replicate_counts": [{"sample": "sample_a", "count": 2}],
    }
    expected_outcome = {
        "kind": "sciplot_figure_outcome",
        "version": 1,
        "figure_id": "figure_a",
        "status": "pending",
        "artifacts": [],
        "reason_code": None,
        "message": None,
    }
    expected_plan = {
        "kind": "sciplot_resolved_figure_plan",
        "version": 1,
        "plan_id": "rfp_5d444542fe9b98a4",
        "plan_sha256": (
            "5d444542fe9b98a41e43674b5794c80b4360f3d8fce87a66cda6bbedf3109910"
        ),
        "rule_id": "test_rule",
        "selection_policy": "test_selection",
        "primary_figure_id": "figure_a",
        "source_sha256": "a" * 64,
        "selected_figure_ids": ["figure_a"],
        "tasks": [expected_task],
        "outcomes": [expected_outcome],
        "status": "planned",
        "complete": False,
    }

    task_payload = task.to_payload()
    outcome_payload = outcome.to_payload()
    plan_payload = plan.to_payload()
    assert task_payload == expected_task
    assert outcome_payload == expected_outcome
    assert plan_payload == expected_plan
    assert (
        FigureTask.from_payload(deepcopy(expected_task)).to_payload() == expected_task
    )
    assert ResolvedFigurePlan.from_payload(deepcopy(expected_plan)).to_payload() == (
        expected_plan
    )
    assert plan.plan_sha256 == (
        "5d444542fe9b98a41e43674b5794c80b4360f3d8fce87a66cda6bbedf3109910"
    )
    assert plan.plan_id == "rfp_5d444542fe9b98a4"
    assert json.dumps(
        plan_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ) == json.dumps(
        expected_plan,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert list(plan_payload) == [
        "kind",
        "version",
        "plan_id",
        "plan_sha256",
        "rule_id",
        "selection_policy",
        "primary_figure_id",
        "source_sha256",
        "selected_figure_ids",
        "tasks",
        "outcomes",
        "status",
        "complete",
    ]

    invalid = figure_plan_gate({"kind": "not_a_figure_plan"})
    assert invalid == {
        "valid": False,
        "complete": False,
        "plan_id": None,
        "plan_sha256": None,
        "selected_figure_ids": [],
        "ready_figure_ids": [],
        "incomplete_figure_ids": [],
        "reason": (
            "invalid_resolved_figure_plan: Not a SciPlot ResolvedFigurePlan payload."
        ),
    }
    assert list(invalid) == [
        "valid",
        "complete",
        "plan_id",
        "plan_sha256",
        "selected_figure_ids",
        "ready_figure_ids",
        "incomplete_figure_ids",
        "reason",
    ]

    valid = figure_plan_gate(plan_payload)
    assert valid is not None
    assert valid["valid"] is True
    assert valid["source_sha256"] == "a" * 64
    assert list(valid) == [
        "valid",
        "complete",
        "plan_id",
        "plan_sha256",
        "source_sha256",
        "selected_figure_ids",
        "ready_figure_ids",
        "incomplete_figure_ids",
        "reason",
    ]

    outcomes = [expected_outcome]
    manifest_valid = figure_plan_manifest_gate(
        {
            "semantic": {"rule_id": plan.rule_id},
            "request": {"rule_id": plan.rule_id},
            "resolved_figure_plan": plan_payload,
            "figure_outcomes": outcomes,
            "result": {
                "resolved_figure_plan": plan_payload,
                "figure_outcomes": outcomes,
            },
            "study_model": {
                "run": {
                    "resolved_figure_plan_id": plan.plan_id,
                    "figure_outcomes": outcomes,
                }
            },
        }
    )
    assert manifest_valid is not None
    assert manifest_valid["valid"] is True
    assert manifest_valid["source_sha256"] == "a" * 64
    assert list(manifest_valid) == [
        *list(valid),
        "projection_consistency",
    ]
    assert list(manifest_valid["projection_consistency"]) == [
        "manifest_rule_matches",
        "manifest_outcomes_match",
        "result_plan_matches",
        "result_outcomes_match",
        "study_plan_id_matches",
        "study_outcomes_match",
        "outcome_artifacts_exist",
    ]

    unknown_task = {**expected_task, "unexpected": True}
    with pytest.raises(ValueError, match="unsupported fields"):
        FigureTask.from_payload(unknown_task)
    unknown_outcome = {**expected_outcome, "unexpected": True}
    with pytest.raises(ValueError, match="unsupported fields"):
        FigureOutcome.from_payload(unknown_outcome)


def test_v2_metric_binding_payloads_round_trip_without_fake_axes() -> None:
    scatter_payload = {
        "kind": "sciplot_figure_task",
        "version": 2,
        "figure_id": "performance_scatter",
        "order": 1,
        "selected": True,
        "title": "Performance comparison scatter",
        "metric_binding": {
            "kind": "cartesian_xy",
            "x_metric": "density",
            "y_metric": "specific_impact_strength",
        },
        "template": "scatter",
        "artifact_stem": "performance_scatter",
        "document_stem": "performance_scatter",
        "conditions": [],
        "condition_labels": [],
        "sample_order": [],
        "replicate_counts": [],
    }
    polar_payload = {
        "kind": "sciplot_figure_task",
        "version": 2,
        "figure_id": "performance_polar_curve",
        "order": 2,
        "selected": True,
        "title": "Performance comparison polar curve",
        "metric_binding": {
            "kind": "ordered_metrics",
            "metric_ids": [
                "density",
                "specific_impact_strength",
                "tensile_strength",
                "elongation_at_break",
            ],
        },
        "template": "polar_curve",
        "artifact_stem": "performance_polar_curve",
        "document_stem": "performance_polar_curve",
        "conditions": [],
        "condition_labels": [],
        "sample_order": [],
        "replicate_counts": [],
    }

    scatter = FigureTask.from_payload(deepcopy(scatter_payload))
    polar = FigureTask.from_payload(deepcopy(polar_payload))

    assert isinstance(scatter.metric_binding, CartesianMetricBinding)
    assert isinstance(polar.metric_binding, OrderedMetricsBinding)
    assert scatter.to_payload() == scatter_payload
    assert polar.to_payload() == polar_payload
    assert "x_metric" not in polar.to_payload()
    assert "y_metric" not in polar.to_payload()


def test_ordered_metric_order_is_plan_identity() -> None:
    def _plan(metric_ids: tuple[str, ...]) -> ResolvedFigurePlan:
        task = FigureTask.with_metric_binding(
            figure_id="performance_polar_curve",
            order=1,
            title="Performance comparison polar curve",
            metric_binding=OrderedMetricsBinding(metric_ids=metric_ids),
            template="polar_curve",
            artifact_stem="performance_polar_curve",
            document_stem="performance_polar_curve",
        )
        return ResolvedFigurePlan.planned(
            rule_id="performance_comparison",
            selection_policy="explicit_supported_template",
            primary_figure_id=task.figure_id,
            tasks=(task,),
            source_sha256="a" * 64,
        )

    original = _plan(("density", "strength", "elongation"))
    reordered = _plan(("strength", "density", "elongation"))

    assert original.plan_sha256 != reordered.plan_sha256
    assert original.plan_id != reordered.plan_id
    tampered = deepcopy(original.to_payload())
    tampered["tasks"][0]["metric_binding"]["metric_ids"] = [
        "strength",
        "density",
        "elongation",
    ]
    with pytest.raises(ValueError, match="plan_id|plan_sha256"):
        ResolvedFigurePlan.from_payload(tampered)


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy_axis",
        "binding_unknown_field",
        "binding_unknown_kind",
        "ordered_cartesian_field",
        "empty_metrics",
        "blank_metric",
        "normalized_duplicate",
        "unknown_version",
    ],
)
def test_v2_metric_binding_rejects_mixed_or_malformed_payloads(
    mutation: str,
) -> None:
    payload = {
        "kind": "sciplot_figure_task",
        "version": 2,
        "figure_id": "performance_polar_curve",
        "order": 1,
        "selected": True,
        "title": "Performance comparison polar curve",
        "metric_binding": {
            "kind": "ordered_metrics",
            "metric_ids": ["density"],
        },
        "template": "polar_curve",
        "artifact_stem": "performance_polar_curve",
        "document_stem": "performance_polar_curve",
        "conditions": [],
        "condition_labels": [],
        "sample_order": [],
        "replicate_counts": [],
    }
    binding = payload["metric_binding"]
    if mutation == "legacy_axis":
        payload["x_metric"] = "legacy_x"
    elif mutation == "binding_unknown_field":
        binding["unexpected"] = True
    elif mutation == "binding_unknown_kind":
        binding["kind"] = "unknown"
    elif mutation == "ordered_cartesian_field":
        binding["x_metric"] = "density"
    elif mutation == "empty_metrics":
        binding["metric_ids"] = []
    elif mutation == "blank_metric":
        binding["metric_ids"] = [""]
    elif mutation == "normalized_duplicate":
        binding["metric_ids"] = [" density ", "density"]
    else:
        payload["version"] = 3

    with pytest.raises(ValueError):
        FigureTask.from_payload(payload)


def test_cartesian_binding_and_legacy_task_fields_are_closed() -> None:
    legacy = {
        "kind": "sciplot_figure_task",
        "version": 1,
        "figure_id": "legacy_scatter",
        "order": 1,
        "selected": True,
        "title": "Legacy scatter",
        "x_metric": "density",
        "y_metric": "strength",
        "template": "scatter",
        "artifact_stem": "legacy_scatter",
        "document_stem": "legacy_scatter",
        "conditions": [],
        "condition_labels": [],
        "sample_order": [],
        "replicate_counts": [],
    }
    mixed_legacy = {
        **legacy,
        "metric_binding": {
            "kind": "cartesian_xy",
            "x_metric": "density",
            "y_metric": "strength",
        },
    }
    cartesian = {
        "kind": "sciplot_figure_task",
        "version": 2,
        "figure_id": "performance_scatter",
        "order": 1,
        "selected": True,
        "title": "Performance comparison scatter",
        "metric_binding": {
            "kind": "cartesian_xy",
            "x_metric": "density",
            "y_metric": "strength",
        },
        "template": "scatter",
        "artifact_stem": "performance_scatter",
        "document_stem": "performance_scatter",
        "conditions": [],
        "condition_labels": [],
        "sample_order": [],
        "replicate_counts": [],
    }
    cartesian_with_ordered = deepcopy(cartesian)
    cartesian_with_ordered["metric_binding"]["metric_ids"] = ["density"]
    cartesian_without_y = deepcopy(cartesian)
    del cartesian_without_y["metric_binding"]["y_metric"]

    for payload in (mixed_legacy, cartesian_with_ordered, cartesian_without_y):
        with pytest.raises(ValueError):
            FigureTask.from_payload(payload)

    single_metric = OrderedMetricsBinding(metric_ids=("density",))
    assert single_metric.to_payload() == {
        "kind": "ordered_metrics",
        "metric_ids": ["density"],
    }


def test_ordered_metric_projection_removes_stale_cartesian_fields() -> None:
    task = FigureTask.with_metric_binding(
        figure_id="performance_polar_curve",
        order=1,
        title="Performance comparison polar curve",
        metric_binding=OrderedMetricsBinding(
            metric_ids=(
                "density",
                "specific_impact_strength",
                "tensile_strength",
            )
        ),
        template="polar_curve",
        artifact_stem="performance_polar_curve",
        document_stem="performance_polar_curve",
    )
    request = {
        "metric": "wrong_metric",
        "x_metric": "wrong_x",
        "y_metric": "wrong_y",
        "metric_ids": ["wrong_metric"],
        "extension": "keep",
        "study_model": {
            "metric": "wrong_root_metric",
            "x_metric": "wrong_root_x",
            "y_metric": "wrong_root_y",
            "metric_ids": ["wrong_root_metric"],
            "extension": "keep_root",
            "figure_queue": [
                {
                    "id": task.figure_id,
                    "metric": "wrong_queue_metric",
                    "x_metric": "wrong_queue_x",
                    "y_metric": "wrong_queue_y",
                    "metric_ids": ["wrong_queue_metric"],
                    "extension": "keep_queue",
                }
            ],
        },
    }
    original = deepcopy(request)

    projected = request_for_figure_task(request, task)

    assert request == original
    assert isinstance(task.metric_binding, OrderedMetricsBinding)
    assert projected["metric_ids"] == list(task.metric_binding.metric_ids)
    assert projected["extension"] == "keep"
    for key in ("metric", "x_metric", "y_metric"):
        assert key not in projected
        assert key not in projected["study_model"]
        assert key not in projected["study_model"]["figure_queue"][0]
    assert "metric_ids" not in projected["study_model"]
    queue_task = projected["study_model"]["figure_queue"][0]
    assert queue_task["metric_ids"] == list(task.metric_binding.metric_ids)
    assert queue_task["extension"] == "keep_queue"
    assert queue_task["resolved_figure_task"] == task.to_payload()
    assert projected["study_model"]["extension"] == "keep_root"
    assert projected["template"] == "polar_curve"
    assert projected["resolved_figure_task"] == task.to_payload()


def test_cartesian_metric_projection_removes_stale_ordered_fields() -> None:
    task = FigureTask.with_metric_binding(
        figure_id="performance_scatter",
        order=1,
        title="Performance comparison scatter",
        metric_binding=CartesianMetricBinding(
            x_metric="density",
            y_metric="specific_impact_strength",
        ),
        template="scatter",
        artifact_stem="performance_scatter",
        document_stem="performance_scatter",
    )
    request = {
        "metric_ids": ["wrong_top_metric"],
        "study_model": {
            "metric_ids": ["wrong_root_metric"],
            "figure_queue": [
                {
                    "id": task.figure_id,
                    "metric_ids": ["wrong_queue_metric"],
                }
            ],
        },
    }

    projected = request_for_figure_task(request, task)

    assert "metric_ids" not in projected
    assert "metric_ids" not in projected["study_model"]
    assert "metric_ids" not in projected["study_model"]["figure_queue"][0]
    assert projected["x_metric"] == "density"
    assert projected["y_metric"] == "specific_impact_strength"
    assert projected["study_model"]["figure_queue"][0]["metric"] == (
        "specific_impact_strength"
    )


def test_plan_serialization_is_strict_and_hash_bound(
    tmp_path: Path,
) -> None:
    plan = _frequency_plan(tmp_path)
    payload = plan.to_payload()

    restored = ResolvedFigurePlan.from_payload(deepcopy(payload))

    assert restored == plan
    assert restored.to_payload() == payload
    assert restored.plan_sha256 == plan.plan_sha256
    assert restored.plan_id == plan.plan_id

    tampered_hash = deepcopy(payload)
    tampered_hash["plan_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="plan_sha256"):
        ResolvedFigurePlan.from_payload(tampered_hash)

    tampered_task = deepcopy(payload)
    tampered_task["tasks"][0]["title"] = "Tampered storage modulus"
    with pytest.raises(ValueError, match="plan_id|plan_sha256"):
        ResolvedFigurePlan.from_payload(tampered_task)

    unknown_field = deepcopy(payload)
    unknown_field["unexpected"] = True
    with pytest.raises(ValueError, match="unsupported fields"):
        ResolvedFigurePlan.from_payload(unknown_field)

    one_ready = merge_figure_outcomes(
        plan,
        (
            FigureOutcome(
                figure_id=plan.primary_figure_id,
                status="ready",
                artifacts=("storage.vsz", "storage.pdf", "storage.tiff"),
            ),
        ),
    )
    assert one_ready.plan_id == plan.plan_id
    assert one_ready.plan_sha256 == plan.plan_sha256
    assert one_ready.status == "incomplete"

    with pytest.raises(ValueError, match="ordered sample_order"):
        FigureTask(
            figure_id="invalid_replicates",
            order=1,
            title="Invalid replicates",
            x_metric="sample",
            y_metric="impact_strength",
            template="box_strip",
            artifact_stem="invalid_replicates",
            document_stem="invalid_replicates",
            sample_order=("E0",),
            replicate_counts=(("E2", 2),),
        )


def test_frequency_plan_order_and_single_task_request_projection(
    tmp_path: Path,
) -> None:
    study_model = _frequency_study_model()
    original = deepcopy(study_model)
    plan = resolve_figure_plan(
        rule_id="rheology_frequency_sweep",
        template="point_line",
        study_model=study_model,
        input_path=tmp_path / "unused-frequency-source",
        request={},
    )
    assert plan is not None

    assert plan.selected_figure_ids == _FREQUENCY_FIGURE_IDS
    assert tuple(task.order for task in plan.tasks) == (1, 2, 3, 4)
    assert tuple(task.y_metric for task in plan.tasks) == _FREQUENCY_METRICS
    assert plan.primary_figure_id == "storage_modulus_vs_frequency"

    selected_task = plan.tasks[2]
    projected = request_for_figure_task(
        {
            "x_metric": "wrong_x",
            "y_metric": "wrong_y",
            "template": "curve",
            "study_model": study_model,
        },
        selected_task,
    )

    assert study_model == original
    assert projected["x_metric"] == "angular_frequency"
    assert projected["y_metric"] == "loss_factor"
    assert projected["template"] == "point_line"
    assert projected["resolved_figure_task"] == selected_task.to_payload()
    assert projected["study_model"]["figure_queue"] == [
        {
            **next(
                figure
                for figure in original["figure_queue"]
                if figure["id"] == selected_task.figure_id
            ),
            "id": selected_task.figure_id,
            "order": 1,
            "status": "planned",
            "title": selected_task.title,
            "metric": selected_task.y_metric,
            "x_metric": selected_task.x_metric,
            "y_metric": selected_task.y_metric,
            "default_template": selected_task.template,
            "artifact_stem": selected_task.artifact_stem,
            "document_stem": selected_task.document_stem,
            "resolved_figure_task": selected_task.to_payload(),
        }
    ]


def test_incomplete_resolved_plan_blocks_publish_state(
    tmp_path: Path,
) -> None:
    plan = _frequency_plan(tmp_path)
    incomplete = merge_figure_outcomes(
        plan,
        (
            FigureOutcome(
                figure_id=plan.primary_figure_id,
                status="ready",
                artifacts=("storage.vsz", "storage.pdf", "storage.tiff"),
            ),
        ),
    )

    result = build_publish_state(
        qa={"status": "passed"},
        package_contract={"complete": True},
        delivery_package={"complete": True},
        prerequisite_state="ready",
        resolved_figure_plan=incomplete.to_payload(),
    )

    assert result["state"] == "needs_rule_repair"
    assert result["ready_to_use"] is False
    assert result["publish_gates"]["gates"] == {
        "qa_passed": True,
        "package_contract_complete": True,
        "delivery_package_complete": True,
        "prerequisite_state_ready": True,
        "resolved_figure_plan_complete": False,
    }
    assert result["publish_gates"]["failed_gates"] == ["resolved_figure_plan_complete"]


def test_each_task_needs_vsz_pdf_and_300dpi_tiff_for_completion(
    tmp_path: Path,
) -> None:
    plan = _frequency_plan(tmp_path)
    artifacts_by_id = {
        task.figure_id: _delivery_artifacts(
            tmp_path / "artifacts",
            task.artifact_stem,
            include_300dpi_tiff=task is not plan.tasks[-1],
            include_plain_tiff=task is plan.tasks[-1],
        )
        for task in plan.tasks
    }

    partial = merge_figure_outcomes(
        plan,
        outcomes_for_artifact_map(plan, artifacts_by_id),
    )
    partial_gate = figure_plan_gate(partial.to_payload())

    assert partial.complete is False
    assert [outcome.status for outcome in partial.outcomes] == [
        "ready",
        "ready",
        "ready",
        "unavailable",
    ]
    assert partial_gate is not None
    assert partial_gate["ready_figure_ids"] == list(plan.selected_figure_ids[:-1])
    assert partial_gate["incomplete_figure_ids"] == [plan.selected_figure_ids[-1]]
    assert set(partial_gate["ready_figure_ids"]).isdisjoint(
        partial_gate["incomplete_figure_ids"]
    )
    assert partial_gate["ready_figure_ids"] + partial_gate[
        "incomplete_figure_ids"
    ] == list(plan.selected_figure_ids)

    final_task = plan.tasks[-1]
    artifacts_by_id[final_task.figure_id] = _delivery_artifacts(
        tmp_path / "artifacts",
        final_task.artifact_stem,
    )
    complete = merge_figure_outcomes(
        plan,
        outcomes_for_artifact_map(plan, artifacts_by_id),
    )
    complete_gate = figure_plan_gate(complete.to_payload())

    assert complete.complete is True
    assert complete_gate is not None
    assert complete_gate["complete"] is True
    assert complete_gate["ready_figure_ids"] == list(plan.selected_figure_ids)
    assert complete_gate["incomplete_figure_ids"] == []


def test_finalize_does_not_inherit_old_ready_outcomes(
    tmp_path: Path,
) -> None:
    plan = _frequency_plan(tmp_path)
    previously_ready = merge_figure_outcomes(
        plan,
        tuple(
            FigureOutcome(
                figure_id=task.figure_id,
                status="ready",
                artifacts=(
                    f"{task.artifact_stem}.vsz",
                    f"{task.artifact_stem}.pdf",
                    f"{task.artifact_stem}_300dpi.tiff",
                ),
            )
            for task in plan.tasks
        ),
    )
    assert previously_ready.complete is True

    current_result: dict[str, object] = {}
    finalized = finalize_figure_plan_result(previously_ready, current_result)

    assert finalized is not None
    assert finalized.complete is False
    assert [outcome.status for outcome in finalized.outcomes] == [
        "unavailable",
        "unavailable",
        "unavailable",
        "unavailable",
    ]
    assert {outcome.reason_code for outcome in finalized.outcomes} == {
        "selected_figure_outcome_missing"
    }
    gate = figure_plan_gate(current_result["resolved_figure_plan"])
    assert gate is not None
    assert gate["ready_figure_ids"] == []
    assert gate["incomplete_figure_ids"] == list(plan.selected_figure_ids)


def test_supported_manifest_cannot_drop_resolved_plan(
    tmp_path: Path,
) -> None:
    plan = _frequency_plan(tmp_path)
    missing = figure_plan_manifest_gate(
        {
            "semantic": {"rule_id": plan.rule_id},
            "request": {"rule_id": plan.rule_id},
        }
    )

    assert missing is not None
    assert missing["valid"] is False
    assert missing["complete"] is False
    assert missing["reason"] == "resolved_figure_plan_required_for_supported_rule"
    assert (
        figure_plan_manifest_gate(
            {
                "semantic": {"rule_id": "legacy_custom_rule"},
                "request": {"rule_id": "legacy_custom_rule"},
            }
        )
        is None
    )


def test_manifest_rule_must_match_embedded_plan(
    tmp_path: Path,
) -> None:
    plan = _frequency_plan(tmp_path)
    outcomes = [outcome.to_payload() for outcome in plan.outcomes]
    manifest = {
        "semantic": {"rule_id": "legacy_custom_rule"},
        "request": {"rule_id": "legacy_custom_rule"},
        "resolved_figure_plan": plan.to_payload(),
        "figure_outcomes": outcomes,
        "result": {
            "resolved_figure_plan": plan.to_payload(),
            "figure_outcomes": outcomes,
        },
        "study_model": {
            "run": {
                "resolved_figure_plan_id": plan.plan_id,
                "figure_outcomes": outcomes,
            }
        },
    }

    gate = figure_plan_manifest_gate(manifest)

    assert gate is not None
    assert gate["valid"] is True
    assert gate["complete"] is False
    assert gate["projection_consistency"]["manifest_rule_matches"] is False
