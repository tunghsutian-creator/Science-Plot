from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.workflow.performance_bundle as performance_bundle
from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.performance_resolution import resolve_performance_plan
from sciplot_core.figure_plan.terminal_binding import bind_terminal_figure_evidence
from sciplot_core.studio import read_studio_figure_set
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.publish_run import publish_studio_export_run
from sciplot_core.studio_core.registry_state import _veusz_spec_path
from sciplot_core.terminal_request import project_terminal_render_request


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "performance_comparison"
    / "material_performance_long.csv"
)
RULE_ID = "performance_comparison"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _prepare_performance_project(
    tmp_path: Path,
    *,
    template: str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = project_dir / "performance.csv"
    shutil.copyfile(FIXTURE, source)
    request: dict[str, Any] = {
        "input": str(source),
        "rule_id": RULE_ID,
    }
    if template is not None:
        request["template"] = template
        request["explicit_template_selection"] = True
    request_path = project_dir / "plot_request.json"
    _write_json(request_path, request)
    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )
    return project_dir, request_path, prepared


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_default_studio_performance_plan_installs_mixed_task_registry(
    tmp_path: Path,
) -> None:
    project_dir, request_path, prepared = _prepare_performance_project(tmp_path)
    request = _read_json(request_path)
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    registry = read_studio_figure_set(project_dir)

    assert plan is not None
    assert plan.selected_figure_ids == (
        "performance_scatter",
        "performance_polar_curve",
    )
    assert plan.primary_figure_id == "performance_scatter"
    assert registry is not None
    assert registry["version"] == 2
    assert registry["primary_figure_id"] == plan.primary_figure_id
    assert [item["figure_id"] for item in registry["figures"]] == list(
        plan.selected_figure_ids
    )
    assert [item["resolved_figure_task"] for item in registry["figures"]] == [
        task.to_payload() for task in plan.tasks
    ]

    primary_document = Path(prepared["document"])
    secondary_document = (
        project_dir / "studio" / "figures" / "performance_polar_curve.vsz"
    )
    assert primary_document == project_dir / "studio" / "document.vsz"
    assert secondary_document.is_file()
    specs = [
        _read_json(_veusz_spec_path(primary_document)),
        _read_json(_veusz_spec_path(secondary_document)),
    ]
    assert [spec["template"] for spec in specs] == ["scatter", "polar_curve"]
    assert [spec["source_request"]["resolved_figure_task"] for spec in specs] == [
        task.to_payload() for task in plan.tasks
    ]
    assert [item["size_mm"] for item in registry["figures"]] == [
        [120.0, 55.0],
        [120.0, 55.0],
    ]
    assert all(outcome.status == "pending" for outcome in plan.outcomes)
    registry_plan = ResolvedFigurePlan.from_payload(registry["resolved_figure_plan"])
    assert all(outcome.status == "editable" for outcome in registry_plan.outcomes)


@pytest.mark.comprehensive
def test_default_studio_exact_current_publish_exports_both_tasks(
    tmp_path: Path,
) -> None:
    project_dir, request_path, prepared = _prepare_performance_project(tmp_path)
    document = Path(prepared["document"])
    exported = export_studio_document(
        document,
        formats=["pdf", "tiff_300"],
    )

    run = publish_studio_export_run(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document,
        exports=exported["exports"],
        export_document_sha256=str(exported["document_sha256"]),
    )

    plan = ResolvedFigurePlan.from_payload(run["resolved_figure_plan"])
    assert plan.complete
    assert plan.selected_figure_ids == (
        "performance_scatter",
        "performance_polar_curve",
    )
    assert [(item["figure_id"], item["format"]) for item in run["exports"]] == [
        ("performance_scatter", "pdf"),
        ("performance_scatter", "tiff_300"),
        ("performance_polar_curve", "pdf"),
        ("performance_polar_curve", "tiff_300"),
    ]
    veusz_documents = [
        value
        for outcome in plan.outcomes
        for value in outcome.artifacts
        if Path(value).suffix.casefold() == ".vsz"
    ]
    assert len(veusz_documents) == 2
    assert all(Path(value).is_file() for value in veusz_documents)
    assert run["figure_set_export_scope"]["supported_figure_ids"] == list(
        plan.selected_figure_ids
    )
    manifest = _read_json(Path(run["manifest"]))
    assert manifest["publish_gates"]["passed"] is True
    assert len(manifest["delivery_package"]["project_documents"]) == 2
    assert len(manifest["delivery_package"]["figures"]) == 4
    assert manifest["delivery_verification"]["verified_project_document_count"] == 2
    assert manifest["delivery_verification"]["verified_export_count"] == 4


def _install_task_recording_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def renderer(
        source: Path,
        *,
        template: str,
        output_dir: Path,
        options: dict[str, Any],
        export_formats: object,
        request_context: dict[str, Any],
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        document = output_dir / f"{template}.vsz"
        pdf = output_dir / f"{template}.pdf"
        tiff = output_dir / f"{template}_300dpi.tiff"
        spec = output_dir / f"{template}.spec.json"
        document.write_text("Add('page')\n", encoding="utf-8")
        pdf.write_bytes(b"%PDF-test")
        tiff.write_bytes(b"II-test")
        _write_json(spec, {"kind": "sciplot_veusz_plot_spec", "template": template})
        calls.append(
            {
                "source": source,
                "template": template,
                "output_dir": output_dir,
                "options": dict(options),
                "export_formats": export_formats,
                "request_context": request_context,
            }
        )
        return {
            "outputs": [str(pdf), str(tiff)],
            "exports": [
                {"format": "pdf", "path": str(pdf)},
                {"format": "tiff_300", "path": str(tiff)},
            ],
            "qa_reports": [],
            "veusz_documents": [str(document)],
            "veusz_specs": [str(spec)],
            "terminal_render_requests": [
                project_terminal_render_request(
                    template=template,
                    render_options=options,
                    request_context=request_context,
                )
            ],
            "transform_steps": [],
        }

    monkeypatch.setattr(performance_bundle, "render_to_dir", renderer)
    return calls


def test_workflow_performance_bundle_consumes_exact_selected_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = resolve_performance_plan(
        input_path=FIXTURE,
        request={"template": "scatter"},
    )
    request = {
        "rule_id": RULE_ID,
        "template": "scatter",
        "resolved_figure_plan": plan.to_payload(),
    }
    calls = _install_task_recording_renderer(monkeypatch)

    result = performance_bundle._render_veusz_performance_bundle(
        FIXTURE,
        output_dir=tmp_path / "output",
        options={},
        export_formats=["pdf", "tiff_300"],
        request=request,
    )

    assert result is not None
    assert [call["template"] for call in calls] == [
        task.template for task in plan.tasks
    ]
    assert [call["request_context"]["resolved_figure_task"] for call in calls] == [
        task.to_payload() for task in plan.tasks
    ]
    assert [call["output_dir"].name for call in calls] == [
        task.artifact_stem for task in plan.tasks
    ]
    assert result["multi_metric_bundle"]["figure_ids"] == list(plan.selected_figure_ids)
    assert [
        item["resolved_figure_task"] for item in result["terminal_render_requests"]
    ] == [task.to_payload() for task in plan.tasks]
    completed = ResolvedFigurePlan.from_payload(result["resolved_figure_plan"])
    assert completed.complete
    assert all(outcome.status == "ready" for outcome in completed.outcomes)
    evidence = bind_terminal_figure_evidence(
        selected_plan=plan,
        result=result,
    )
    assert evidence is not None
    assert evidence.terminal_tasks == plan.tasks


def test_workflow_performance_bundle_rejects_planless_execution_before_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_task_recording_renderer(monkeypatch)

    with pytest.raises(ValueError, match="performance_figure_plan_required"):
        performance_bundle._render_veusz_performance_bundle(
            FIXTURE,
            output_dir=tmp_path / "output",
            options={},
            export_formats=["pdf", "tiff_300"],
            request={"rule_id": RULE_ID, "template": "scatter"},
        )

    assert calls == []
    assert not (tmp_path / "output").exists()
