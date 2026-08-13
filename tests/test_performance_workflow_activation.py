from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from sciplot_core import workflow
from sciplot_core.delivery.plan_binding import plan_source_figure_ids
from sciplot_core.figure_plan import ResolvedFigurePlan
import sciplot_core.workflow.performance_bundle as performance_bundle
import sciplot_core.workflow.request_run as request_run_module


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)
RULE_ID = "performance_comparison"


def _request(
    tmp_path: Path,
    *,
    template: str | None = None,
) -> tuple[Path, Path, Path]:
    source = tmp_path / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    output = tmp_path / "output"
    payload: dict[str, Any] = {
        "recipe": "auto",
        "rule_id": RULE_ID,
        "input": str(source),
        "output": str(output),
        "exports": ["pdf", "tiff_300"],
    }
    if template is not None:
        payload["template"] = template
        payload["explicit_template_selection"] = True
    request_path = tmp_path / "plot_request.json"
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    return request_path, source, output


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.comprehensive
def test_default_performance_workflow_delivers_exact_completed_plan(
    tmp_path: Path,
) -> None:
    request_path, _source, output = _request(tmp_path)

    manifest = workflow.run_request(request_path)

    plan = ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"])
    assert plan.complete
    assert plan.selected_figure_ids == (
        "performance_scatter",
        "performance_polar_curve",
    )
    assert (
        ResolvedFigurePlan.from_payload(manifest["result"]["resolved_figure_plan"])
        == plan
    )
    assert [
        item["resolved_figure_task"]
        for item in manifest["result"]["terminal_render_requests"]
    ] == [task.to_payload() for task in plan.tasks]
    assert plan_source_figure_ids(plan) == {
        artifact: outcome.figure_id
        for outcome in plan.outcomes
        for artifact in outcome.artifacts
        if Path(artifact).suffix.casefold() in {".vsz", ".pdf", ".tiff"}
    }
    assert {
        item["figure_id"] for item in manifest["delivery_package"]["figures"]
    } == set(plan.selected_figure_ids)
    assert [
        item["figure_id"] for item in manifest["delivery_package"]["project_documents"]
    ] == list(plan.selected_figure_ids)
    assert all(
        Path(item["path"]).is_file()
        for item in [
            *manifest["delivery_package"]["figures"],
            *manifest["delivery_package"]["project_documents"],
        ]
    )
    assert {step["id"] for step in manifest["transform_ledger"]["steps"]} >= {
        "performance_comparison_preparation_performance_scatter",
        "performance_comparison_preparation_performance_polar_curve",
    }
    assert manifest["publish_gates"]["passed"] is True
    assert (output / "manifest.json").is_file()


@pytest.mark.comprehensive
@pytest.mark.parametrize(
    ("template", "figure_id"),
    [
        ("scatter", "performance_scatter"),
        ("polar_curve", "performance_polar_curve"),
    ],
)
def test_explicit_performance_workflow_delivers_only_selected_task(
    tmp_path: Path,
    template: str,
    figure_id: str,
) -> None:
    request_path, _source, _output = _request(tmp_path, template=template)

    manifest = workflow.run_request(request_path)

    plan = ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"])
    assert plan.complete
    assert plan.selected_figure_ids == (figure_id,)
    assert [item["figure_id"] for item in manifest["delivery_package"]["figures"]] == [
        figure_id,
        figure_id,
    ]
    assert [
        item["figure_id"] for item in manifest["delivery_package"]["project_documents"]
    ] == [figure_id]


@pytest.mark.comprehensive
def test_performance_workflow_uses_its_bound_snapshot_after_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, source, output = _request(tmp_path)
    original_render = request_run_module.execute_request_render

    def render_then_mutate(*args: object, **kwargs: object):
        rendered = original_render(*args, **kwargs)
        source.write_bytes(source.read_bytes() + b"\nsource-drift")
        return rendered

    monkeypatch.setattr(
        request_run_module,
        "execute_request_render",
        render_then_mutate,
    )

    manifest = workflow.run_request(request_path)

    assert ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"]).complete
    assert source.read_bytes().endswith(b"\nsource-drift")
    assert (output / "manifest.json").is_file()


@pytest.mark.comprehensive
def test_second_performance_task_failure_restores_existing_managed_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path, _source, output = _request(tmp_path)
    (output / "figures").mkdir(parents=True)
    (output / "figures" / "old.pdf").write_bytes(b"old-pdf")
    (output / "manifest.json").write_text('{"state":"ready"}', encoding="utf-8")
    (output / "notes.txt").write_text("keep", encoding="utf-8")
    before = _snapshot(output)
    real_renderer = performance_bundle.render_to_dir
    calls = 0

    def fail_second(*args: object, **kwargs: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic performance second task failure")
        return real_renderer(*args, **kwargs)

    monkeypatch.setattr(performance_bundle, "render_to_dir", fail_second)

    with pytest.raises(RuntimeError, match="second task failure"):
        workflow.run_request(request_path)

    assert calls == 2
    assert _snapshot(output) == before
    assert not list(output.parent.glob(f".{output.name}.sciplot-managed-backup-*"))
