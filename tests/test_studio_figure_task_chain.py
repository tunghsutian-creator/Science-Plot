from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    FigureTask,
    OrderedMetricsBinding,
    ResolvedFigurePlan,
    editable_figure_plan,
    request_for_figure_task,
)
from sciplot_core.presentation_identity import SelectedPresentationIdentity
from sciplot_core.studio_core.figure_set_state import (
    _figure_registry_entry,
    _read_studio_figure_set,
)
from sciplot_core.studio_core.figure_set_prepare import _prepare_studio_figure_set
from sciplot_core.studio_core.figure_set_storage import (
    _commit_studio_figure_set_transaction,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_queue_item_from_task,
    figure_task_from_queue_item,
    figure_task_from_registry_entry,
    primary_figure_task,
    validate_figure_queue_against_plan,
)
from sciplot_core.studio_core.presentation_evidence import (
    validate_prepared_studio_presentation,
)


def _v1_task(*, order: int = 1) -> FigureTask:
    return FigureTask(
        figure_id="legacy_curve",
        order=order,
        title="Legacy curve",
        x_metric="time",
        y_metric="stress",
        template="point_line",
        artifact_stem="legacy_curve",
        document_stem="legacy_curve",
    )


def _scatter_task(*, order: int = 1) -> FigureTask:
    return FigureTask.with_metric_binding(
        figure_id="performance_scatter",
        order=order,
        title="Performance scatter",
        metric_binding=CartesianMetricBinding(
            x_metric="density",
            y_metric="specific_impact_strength",
        ),
        template="scatter",
        artifact_stem="performance_scatter",
        document_stem="performance_scatter",
    )


def _polar_task(*, order: int = 2) -> FigureTask:
    return FigureTask.with_metric_binding(
        figure_id="performance_polar",
        order=order,
        title="Performance polar curve",
        metric_binding=OrderedMetricsBinding(
            metric_ids=(
                "density",
                "specific_impact_strength",
                "tensile_strength",
            )
        ),
        template="polar_curve",
        artifact_stem="performance_polar",
        document_stem="performance_polar",
    )


def _mixed_plan() -> ResolvedFigurePlan:
    return ResolvedFigurePlan.planned(
        rule_id="performance_comparison",
        selection_policy="test_mixed_templates",
        primary_figure_id="performance_scatter",
        tasks=(_scatter_task(), _polar_task()),
    )


def _spec_for_task(
    task: FigureTask,
    *,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "sciplot_veusz_plot_spec",
        "version": 1,
        "template": task.template,
        "source_request": request_for_figure_task(
            request
            or {
                "rule_id": "performance_comparison",
                "template": "scatter",
                "study_model": {"figure_queue": []},
            },
            task,
        ),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _registry_entry(
    project_dir: Path,
    task: FigureTask,
    *,
    primary: bool,
) -> dict[str, Any]:
    document = (
        project_dir / "studio" / "document.vsz"
        if primary
        else project_dir / "studio" / "figures" / f"{task.document_stem}.vsz"
    )
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("Add('page')\n", encoding="utf-8")
    spec = (
        project_dir / "studio" / "spec.json"
        if primary
        else document.with_suffix(".spec.json")
    )
    _write_json(spec, _spec_for_task(task))
    return _figure_registry_entry(
        figure=figure_queue_item_from_task(task),
        document_path=document,
        generated_hash=None,
        series_count=1,
    )


def _write_mixed_project(project_dir: Path) -> ResolvedFigurePlan:
    plan = _mixed_plan()
    entries = [
        _registry_entry(
            project_dir,
            task,
            primary=task.figure_id == plan.primary_figure_id,
        )
        for task in plan.tasks
    ]
    _write_json(
        project_dir / "plot_request.json",
        {
            "rule_id": plan.rule_id,
            "template": "scatter",
            "resolved_figure_plan": plan.to_payload(),
        },
    )
    _write_json(
        project_dir / "studio" / "figure_set.json",
        {
            "kind": "sciplot_studio_figure_set",
            "version": 2,
            "rule_id": plan.rule_id,
            "primary_figure_id": plan.primary_figure_id,
            "figures": entries,
            "resolved_figure_plan": plan.to_payload(),
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
        },
    )
    return plan


@pytest.mark.parametrize(
    "task",
    [
        pytest.param(_v1_task(), id="v1-cartesian"),
        pytest.param(_scatter_task(), id="v2-cartesian"),
        pytest.param(_polar_task(order=1), id="v2-ordered"),
    ],
)
def test_queue_round_trip_preserves_exact_task_without_fake_axes(
    task: FigureTask,
) -> None:
    item = figure_queue_item_from_task(task)

    assert item["resolved_figure_task"] == task.to_payload()
    assert figure_task_from_queue_item(item, required=True) == task
    if isinstance(task.metric_binding, OrderedMetricsBinding):
        assert item["metric_ids"] == list(task.metric_binding.metric_ids)
        assert not {"metric", "x_metric", "y_metric"} & set(item)
        assert "None" not in json.dumps(item)
    else:
        assert item["x_metric"]
        assert item["y_metric"]
        assert item["metric"] == item["y_metric"]
        assert "metric_ids" not in item


def test_queue_plan_binding_rejects_coordinated_task_tamper() -> None:
    plan = _mixed_plan()
    queue = [figure_queue_item_from_task(task) for task in plan.tasks]
    forged = deepcopy(queue)
    forged_task = FigureTask.with_metric_binding(
        figure_id="performance_polar",
        order=2,
        title="Performance polar curve",
        metric_binding=OrderedMetricsBinding(
            metric_ids=("density", "tensile_strength")
        ),
        template="polar_curve",
        artifact_stem="performance_polar",
        document_stem="performance_polar",
    )
    forged[1] = figure_queue_item_from_task(forged_task)

    validate_figure_queue_against_plan(queue, plan)
    with pytest.raises(ValueError, match="studio_figure_task_mismatch"):
        validate_figure_queue_against_plan(forged, plan)


@pytest.mark.parametrize(
    "bad_task",
    [
        None,
        "not-an-object",
        {"kind": "sciplot_figure_task", "version": 99},
    ],
)
def test_present_malformed_queue_task_never_downgrades_to_legacy(
    bad_task: object,
) -> None:
    item = figure_queue_item_from_task(_v1_task())
    item["resolved_figure_task"] = bad_task

    with pytest.raises(ValueError, match="studio_figure_task_mismatch"):
        figure_task_from_queue_item(item, required=False)


def test_primary_task_is_selected_by_identity_not_list_position_or_metric() -> None:
    plan = ResolvedFigurePlan.planned(
        rule_id="performance_comparison",
        selection_policy="test_nonfirst_primary",
        primary_figure_id="performance_polar",
        tasks=(_scatter_task(), _polar_task()),
    )

    assert primary_figure_task(plan) == plan.tasks[1]


def test_registry_round_trip_retains_exact_mixed_tasks(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    plan = _write_mixed_project(project_dir)

    registry = _read_studio_figure_set(project_dir)

    assert registry is not None
    assert registry["version"] == 2
    entries = registry["figures"]
    assert [
        figure_task_from_registry_entry(entry, required=True) for entry in entries
    ] == list(plan.tasks)
    ordered_entry = entries[1]
    assert ordered_entry["metric_ids"] == [
        "density",
        "specific_impact_strength",
        "tensile_strength",
    ]
    assert not {"metric", "x_metric", "y_metric"} & set(ordered_entry)
    assert "None" not in json.dumps(registry)


def test_registry_rejects_stale_ordered_axes_and_task_tamper(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    _write_mixed_project(project_dir)
    registry_path = project_dir / "studio" / "figure_set.json"
    baseline = json.loads(registry_path.read_text(encoding="utf-8"))

    stale_axes = deepcopy(baseline)
    stale_axes["figures"][1]["x_metric"] = "density"
    stale_axes["figures"][1]["y_metric"] = "specific_impact_strength"
    _write_json(registry_path, stale_axes)
    assert _read_studio_figure_set(project_dir) is None

    changed_task = deepcopy(baseline)
    changed_task["figures"][1]["resolved_figure_task"]["metric_binding"][
        "metric_ids"
    ] = ["density", "tensile_strength"]
    _write_json(registry_path, changed_task)
    assert _read_studio_figure_set(project_dir) is None

    reordered = deepcopy(baseline)
    reordered["figures"].reverse()
    _write_json(registry_path, reordered)
    assert _read_studio_figure_set(project_dir) is None

    missing = deepcopy(baseline)
    missing["figures"].pop()
    _write_json(registry_path, missing)
    assert _read_studio_figure_set(project_dir) is None


def test_legacy_v1_registry_remains_readable_without_becoming_task_evidence(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    document = project_dir / "studio" / "document.vsz"
    document.parent.mkdir(parents=True)
    document.write_text("Add('page')\n", encoding="utf-8")
    _write_json(project_dir / "plot_request.json", {"rule_id": "legacy_custom_rule"})
    _write_json(
        project_dir / "studio" / "figure_set.json",
        {
            "kind": "sciplot_studio_figure_set",
            "version": 1,
            "rule_id": "legacy_custom_rule",
            "primary_figure_id": "legacy_curve",
            "figures": [
                {
                    "figure_id": "legacy_curve",
                    "title": "Legacy curve",
                    "metric": "stress",
                    "x_metric": "time",
                    "y_metric": "stress",
                    "order": 1,
                    "document_stem": "legacy_curve",
                    "document": str(document),
                }
            ],
        },
    )

    registry = _read_studio_figure_set(project_dir)

    assert registry is not None
    assert registry["version"] == 1
    assert (
        figure_task_from_registry_entry(
            registry["figures"][0],
            required=False,
        )
        is None
    )


def test_presentation_identity_binds_primary_while_secondary_uses_own_task(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    plan = _write_mixed_project(project_dir)

    validate_prepared_studio_presentation(
        project_dir=project_dir,
        document_path=project_dir / "studio" / "document.vsz",
        identity=SelectedPresentationIdentity(
            rule_id=plan.rule_id,
            template="scatter",
        ),
        figure_plan=plan,
    )


def test_primary_task_template_must_match_selected_presentation(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    plan = _write_mixed_project(project_dir)

    with pytest.raises(RuntimeError, match="presentation_identity_mismatch"):
        validate_prepared_studio_presentation(
            project_dir=project_dir,
            document_path=project_dir / "studio" / "document.vsz",
            identity=SelectedPresentationIdentity(
                rule_id=plan.rule_id,
                template="polar_curve",
            ),
            figure_plan=plan,
        )


def test_secondary_spec_task_tamper_fails_before_publication(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    plan = _write_mixed_project(project_dir)
    secondary_spec = project_dir / "studio" / "figures" / "performance_polar.spec.json"
    payload = json.loads(secondary_spec.read_text(encoding="utf-8"))
    payload["source_request"]["resolved_figure_task"] = _scatter_task().to_payload()
    _write_json(secondary_spec, payload)

    with pytest.raises(RuntimeError, match="studio_figure_task_mismatch"):
        validate_prepared_studio_presentation(
            project_dir=project_dir,
            document_path=project_dir / "studio" / "document.vsz",
            identity=SelectedPresentationIdentity(
                rule_id=plan.rule_id,
                template="scatter",
            ),
            figure_plan=plan,
        )


def test_secondary_spec_stale_metric_projection_fails_before_publication(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    plan = _write_mixed_project(project_dir)
    secondary_spec = project_dir / "studio" / "figures" / "performance_polar.spec.json"
    payload = json.loads(secondary_spec.read_text(encoding="utf-8"))
    payload["source_request"]["x_metric"] = "density"
    payload["source_request"]["y_metric"] = "specific_impact_strength"
    _write_json(secondary_spec, payload)

    with pytest.raises(RuntimeError, match="studio_figure_task_mismatch"):
        validate_prepared_studio_presentation(
            project_dir=project_dir,
            document_path=project_dir / "studio" / "document.vsz",
            identity=SelectedPresentationIdentity(
                rule_id=plan.rule_id,
                template="scatter",
            ),
            figure_plan=plan,
        )


def test_prior_legacy_registry_cannot_override_current_task_document_stem(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    request_path = project_dir / "plot_request.json"
    plan = _mixed_plan()
    queue = [figure_queue_item_from_task(task) for task in plan.tasks]
    _write_json(
        request_path,
        {
            "rule_id": plan.rule_id,
            "template": "scatter",
            "resolved_figure_plan": plan.to_payload(),
        },
    )
    current_entries = [
        _registry_entry(
            project_dir,
            task,
            primary=task.figure_id == plan.primary_figure_id,
        )
        for task in plan.tasks
    ]
    legacy_secondary = project_dir / "studio" / "figures" / "legacy_secondary_name.vsz"
    legacy_secondary.write_text("legacy-secondary\n", encoding="utf-8")
    _write_json(
        legacy_secondary.with_suffix(".spec.json"),
        {
            "kind": "sciplot_veusz_plot_spec",
            "version": 1,
            "template": "polar_curve",
        },
    )
    _write_json(
        project_dir / "studio" / "figure_set.json",
        {
            "kind": "sciplot_studio_figure_set",
            "version": 1,
            "rule_id": plan.rule_id,
            "primary_figure_id": plan.primary_figure_id,
            "figures": [
                {
                    **{
                        key: value
                        for key, value in current_entries[0].items()
                        if key not in {"resolved_figure_task", "template"}
                    }
                },
                {
                    "figure_id": "performance_polar",
                    "title": "Performance polar curve",
                    "metric": "None",
                    "x_metric": "None",
                    "y_metric": "None",
                    "order": 2,
                    "artifact_stem": "performance_polar",
                    "document_stem": "legacy_secondary_name",
                    "status": "ready",
                    "document": str(legacy_secondary),
                    "spec": str(legacy_secondary.with_suffix(".spec.json")),
                    "generated_hash": None,
                    "series_count": 1,
                },
            ],
        },
    )

    registry = _prepare_studio_figure_set(
        project_dir=project_dir,
        request_path=request_path,
        request=json.loads(request_path.read_text(encoding="utf-8")),
        primary_document=project_dir / "studio" / "document.vsz",
        preserve_existing=True,
        queue_override=queue,
        figure_plan=plan,
    )

    assert registry is not None
    secondary = registry["figures"][1]
    assert secondary["document_stem"] == "performance_polar"
    assert Path(secondary["document"]) == (
        project_dir / "studio" / "figures" / "performance_polar.vsz"
    )
    assert legacy_secondary.is_file()


def test_spec_task_mismatch_rolls_back_document_spec_and_registry(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    studio_dir = project_dir / "studio"
    target_document = studio_dir / "document.vsz"
    target_spec = studio_dir / "spec.json"
    target_registry = studio_dir / "figure_set.json"
    studio_dir.mkdir(parents=True)
    target_document.write_bytes(b"old-document")
    _write_json(
        target_spec,
        {
            "kind": "sciplot_veusz_plot_spec",
            "version": 1,
            "template": "scatter",
        },
    )
    _write_json(
        target_registry,
        {"kind": "sciplot_studio_figure_set", "version": 1, "figures": []},
    )
    before = {
        path: path.read_bytes()
        for path in (target_document, target_spec, target_registry)
    }

    task = _scatter_task()
    plan = ResolvedFigurePlan.planned(
        rule_id="performance_comparison",
        selection_policy="test_atomic_task_binding",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    staged_document = studio_dir / ".staged-document.vsz"
    staged_spec = studio_dir / ".staged-spec.json"
    staged_document.write_bytes(b"new-document")
    _write_json(staged_spec, _spec_for_task(_polar_task(order=1)))
    entry = _figure_registry_entry(
        figure=figure_queue_item_from_task(task),
        document_path=target_document,
        generated_hash=None,
        series_count=1,
        state_document_path=staged_document,
    )
    editable_plan = editable_figure_plan(plan, [entry])
    registry = {
        "kind": "sciplot_studio_figure_set",
        "version": 2,
        "rule_id": plan.rule_id,
        "primary_figure_id": plan.primary_figure_id,
        "figures": [entry],
        "resolved_figure_plan": editable_plan.to_payload(),
        "plan_id": editable_plan.plan_id,
        "plan_sha256": editable_plan.plan_sha256,
    }
    replacement_calls: list[tuple[Path, Path]] = []

    def replace_path(source: Path, target: Path) -> None:
        replacement_calls.append((source, target))
        source.replace(target)

    with pytest.raises(RuntimeError, match="studio_figure_task_mismatch"):
        _commit_studio_figure_set_transaction(
            project_dir=project_dir,
            replacements=[
                {
                    "staged": staged_document,
                    "target": target_document,
                    "expected_hash": _sha256(staged_document),
                    "kind": "document",
                },
                {
                    "staged": staged_spec,
                    "target": target_spec,
                    "expected_hash": _sha256(staged_spec),
                    "kind": "spec",
                },
            ],
            manual_archive_requests=[],
            registry=registry,
            path_replacer=replace_path,
        )

    assert replacement_calls == []
    assert {
        path: path.read_bytes()
        for path in (target_document, target_spec, target_registry)
    } == before
    assert not list(studio_dir.glob(".sciplot-figure-set-transaction-*"))


def _sha256(path: Path) -> str:
    from sciplot_core.foundation.file_hashing import existing_file_sha256

    value = existing_file_sha256(path)
    assert value is not None
    return value
