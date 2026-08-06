from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.figure_plan import (
    CartesianMetricBinding,
    OrderedMetricsBinding,
    ResolvedFigurePlan,
    request_for_figure_task,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.performance_resolution import (
    resolve_performance_plan,
)
from sciplot_core.render import render_to_dir
from sciplot_core.studio import read_studio_figure_set
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.registry_state import _veusz_spec_path


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)
RULE_ID = "performance_comparison"
EXPECTED_FIGURE_ID_BY_TEMPLATE = {
    "scatter": "performance_scatter",
    "polar_curve": "performance_polar_curve",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _assert_exact_task_projection(
    source_request: dict[str, Any],
    *,
    task_payload: dict[str, Any],
) -> None:
    assert source_request["resolved_figure_task"] == task_payload
    assert source_request["template"] == task_payload["template"]
    binding = task_payload["metric_binding"]
    if binding["kind"] == "cartesian_xy":
        assert source_request["x_metric"] == binding["x_metric"]
        assert source_request["y_metric"] == binding["y_metric"]
        assert "metric_ids" not in source_request
    else:
        assert binding["kind"] == "ordered_metrics"
        assert source_request["metric_ids"] == binding["metric_ids"]
        assert "x_metric" not in source_request
        assert "y_metric" not in source_request


@pytest.mark.comprehensive
@pytest.mark.parametrize("template", ["scatter", "polar_curve"])
def test_real_worker_executes_only_the_selected_performance_terminal_task(
    tmp_path: Path,
    template: str,
) -> None:
    plan = resolve_performance_plan(
        input_path=FIXTURE,
        request={"template": "scatter"},
    )
    task = next(task for task in plan.tasks if task.template == template)
    task_request = request_for_figure_task(
        {
            "rule_id": RULE_ID,
            "template": "scatter",
            "resolved_figure_plan": plan.to_payload(),
        },
        task,
    )

    result = render_to_dir(
        FIXTURE,
        template=task.template,
        output_dir=tmp_path / template,
        export_formats=("pdf",),
        request_context=task_request,
    )

    assert result["template"] == task.template
    assert len(result["outputs"]) == 1
    assert len(result["veusz_documents"]) == 1
    assert len(result["veusz_specs"]) == 1
    assert len(result["terminal_render_requests"]) == 1
    assert result["qa_reports"][0]["issues"] == []
    assert Path(result["outputs"][0]).is_file()

    terminal_request = result["terminal_render_requests"][0]
    _assert_exact_task_projection(
        terminal_request,
        task_payload=task.to_payload(),
    )

    document = Path(result["veusz_documents"][0]).resolve()
    spec = _read_json(Path(result["veusz_specs"][0]))
    assert document.is_file()
    assert spec["template"] == task.template
    _assert_exact_task_projection(
        spec["source_request"],
        task_payload=task.to_payload(),
    )

    worker_project = document.parent.parent
    assert sorted(
        path.resolve() for path in (worker_project / "studio").rglob("*.vsz")
    ) == [document]
    registry = read_studio_figure_set(worker_project)
    if registry is not None:
        assert [item["figure_id"] for item in registry["figures"]] == [task.figure_id]
        assert registry["figures"][0]["resolved_figure_task"] == task.to_payload()


@pytest.mark.parametrize("template", ["scatter", "polar_curve"])
def test_explicit_performance_studio_prepare_installs_one_task_registry(
    tmp_path: Path,
    template: str,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    request_path = project_dir / "plot_request.json"
    _write_json(
        request_path,
        {
            "input": str(source),
            "rule_id": RULE_ID,
            "template": template,
            "explicit_template_selection": True,
        },
    )

    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )

    request = _read_json(request_path)
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    assert plan is not None
    expected_figure_id = EXPECTED_FIGURE_ID_BY_TEMPLATE[template]
    assert plan.selection_policy == "explicit_supported_template"
    assert plan.selected_figure_ids == (expected_figure_id,)
    assert plan.primary_figure_id == expected_figure_id
    task = plan.tasks[0]
    assert task.order == 1
    assert task.template == template
    if template == "scatter":
        assert isinstance(task.metric_binding, CartesianMetricBinding)
    else:
        assert isinstance(task.metric_binding, OrderedMetricsBinding)

    registry = read_studio_figure_set(project_dir)
    assert registry is not None
    assert registry["version"] == 2
    assert registry["primary_figure_id"] == expected_figure_id
    assert registry["plan_id"] == plan.plan_id
    assert registry["plan_sha256"] == plan.plan_sha256
    assert len(registry["figures"]) == 1
    entry = registry["figures"][0]
    assert entry["figure_id"] == expected_figure_id
    assert entry["template"] == template
    assert entry["artifact_stem"] == task.artifact_stem
    assert entry["document_stem"] == task.document_stem
    assert entry["resolved_figure_task"] == task.to_payload()

    registry_plan = ResolvedFigurePlan.from_payload(registry["resolved_figure_plan"])
    assert registry_plan.plan_id == plan.plan_id
    assert registry_plan.selected_figure_ids == (expected_figure_id,)
    assert len(registry_plan.outcomes) == 1
    assert registry_plan.outcomes[0].status == "editable"

    document = Path(prepared["document"]).resolve()
    assert document == (project_dir / "studio" / "document.vsz").resolve()
    assert sorted(
        path.resolve() for path in (project_dir / "studio").rglob("*.vsz")
    ) == [document]
    spec = _read_json(_veusz_spec_path(document))
    assert spec["template"] == template
    _assert_exact_task_projection(
        spec["source_request"],
        task_payload=task.to_payload(),
    )
