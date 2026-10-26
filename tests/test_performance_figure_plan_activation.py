from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.workflow.performance_bundle as performance_bundle
import sciplot_core.studio_core.figure_set_state as figure_set_state
import sciplot_core.studio_core.prepare_existing as prepare_existing
from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.performance_resolution import resolve_performance_plan
from sciplot_core.figure_plan.terminal_binding import bind_terminal_figure_evidence
from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.studio import prepare_studio_document, read_studio_figure_set
from sciplot_core.studio import export_native_document_artifacts
from sciplot_core.studio_core.publish_run import publish_studio_export_run
from sciplot_core.studio_core.registry_state import _veusz_spec_path
from sciplot_core.studio_render.models import StudioPreparationBlocked
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
    prepared = prepare_studio_document(
        project_dir,
        rule_id=None,
        template=None,
        project_name=None,
    )
    return project_dir, request_path, prepared


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _publish_registry_fixture(project: Path, writes: dict[str, bytes | None]) -> None:
    """Admit an intentionally invalid domain fixture without a physical CAS race."""
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.project_store.adapters import publish_files

    store = project_store(project, with_snapshot=True)
    before = store.snapshot()
    publish_files(store, writes, kind="figure_set", baseline={"project_id": before["project_id"],
        "generation": before["generation"], "files": {name: before["files"].get(name, {}).get("sha256") for name in writes}})
    assert store.snapshot()["sequence"] == before["sequence"] + 1


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


def test_exact_current_performance_reuses_one_validated_registry_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir, _request_path, generated = _prepare_performance_project(tmp_path)
    registry_path = (project_dir / "studio" / "figure_set.json").resolve()
    registry_reads = 0
    read_json = figure_set_state._read_json

    def count_registry_read(path: Path) -> dict[str, Any]:
        nonlocal registry_reads
        if Path(literal_source_path(path)) == registry_path:
            registry_reads += 1
        return read_json(path)

    monkeypatch.setattr(figure_set_state, "_read_json", count_registry_read)

    prepared = prepare_studio_document(project_dir)

    assert registry_reads == 1
    assert prepared["figure_set"] is not None
    assert prepared["figure_set"] == prepared["studio"]["figure_set"]
    assert [item["figure_id"] for item in prepared["figure_set"]["figures"]] == [
        "performance_scatter",
        "performance_polar_curve",
    ]
    primary = next(
        item
        for item in prepared["figure_set"]["figures"]
        if item["figure_id"] == prepared["figure_set"]["primary_figure_id"]
    )
    assert prepared["document_state"]["generated_hash"] == primary["generated_hash"]
    assert prepared["document_state"]["authority"] == "sciplot_generated"
    assert prepared["document"] == generated["document"]


def test_exact_current_performance_registry_hash_detects_manual_primary_edit(
    tmp_path: Path,
) -> None:
    project_dir, _request_path, generated = _prepare_performance_project(tmp_path)
    document = Path(generated["document"])
    registry = _read_json(project_dir / "studio" / "figure_set.json")
    primary = next(
        item
        for item in registry["figures"]
        if item["figure_id"] == registry["primary_figure_id"]
    )
    document.write_bytes(document.read_bytes() + b"\n# manual edit\n")
    from sciplot_core.studio_core.project_command_scope import adopt_saved_native
    from sciplot_core.studio_core.project_query import resolve_project_figure

    adopt_saved_native(project_dir, resolve_project_figure(project_dir))

    prepared = prepare_studio_document(project_dir)

    assert prepared["document_state"]["generated_hash"] == primary["generated_hash"]
    assert prepared["document_state"]["authority"] == "veusz_manual"
    assert prepared["document_state"]["manual_edit_detected"] is True


def test_exact_current_performance_rejects_split_generated_hash_projection(
    tmp_path: Path,
) -> None:
    project_dir, _request_path, generated = _prepare_performance_project(tmp_path)
    document = Path(generated["document"])
    from hashlib import sha256

    edited_native = document.read_bytes() + b"\n# manual edit\n"
    edited_hash = sha256(edited_native).hexdigest()
    assert edited_hash is not None
    registry_path = project_dir / "studio" / "figure_set.json"
    registry = _read_json(registry_path)
    primary = next(
        item
        for item in registry["figures"]
        if item["figure_id"] == registry["primary_figure_id"]
    )
    assert primary["document_state"]["generated_hash"] != edited_hash
    primary["generated_hash"] = edited_hash
    _publish_registry_fixture(project_dir, {"studio/document.vsz": edited_native,
        "studio/figure_set.json": json.dumps(registry).encode()})

    with pytest.raises(StudioPreparationBlocked) as exc_info:
        prepare_studio_document(project_dir)

    assert exc_info.value.reason_code == "studio_figure_set_mismatch"


@pytest.mark.parametrize("registry_state", ["missing", "malformed"])
def test_required_plan_registry_failure_blocks_before_metadata_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_state: str,
) -> None:
    project_dir, request_path, _generated = _prepare_performance_project(tmp_path)
    registry_path = project_dir / "studio" / "figure_set.json"
    if registry_state == "missing":
        replacement = None
    else:
        replacement = b"{not-json"
    _publish_registry_fixture(project_dir, {registry_path.relative_to(project_dir).as_posix(): replacement})
    request_before = request_path.read_bytes()
    metadata_writes: list[str] = []

    def record_launcher(*_args: object, **_kwargs: object) -> Path:
        metadata_writes.append("launcher")
        return project_dir / "unexpected-launcher"

    def record_registration(*_args: object, **_kwargs: object) -> None:
        metadata_writes.append("registration")

    monkeypatch.setattr(prepare_existing, "_write_studio_launcher", record_launcher)
    monkeypatch.setattr(prepare_existing, "_write_veusz_launcher", record_launcher)
    monkeypatch.setattr(
        prepare_existing,
        "_write_export_edited_launcher",
        record_launcher,
    )
    monkeypatch.setattr(
        prepare_existing,
        "_register_studio_block",
        record_registration,
    )

    with pytest.raises(StudioPreparationBlocked) as exc_info:
        prepare_studio_document(project_dir)

    assert exc_info.value.reason_code == "studio_figure_set_mismatch"
    assert metadata_writes == []
    assert request_path.read_bytes() == request_before


@pytest.mark.comprehensive
def test_default_studio_exact_current_publish_exports_both_tasks(
    tmp_path: Path,
) -> None:
    project_dir, request_path, prepared = _prepare_performance_project(tmp_path)
    document = Path(prepared["document"])
    exported = export_native_document_artifacts(
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
