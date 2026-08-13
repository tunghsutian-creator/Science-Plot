from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from sciplot_core import workflow
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.delivery.plan_binding import plan_source_figure_ids
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    ResolvedFigurePlan,
    source_tree_sha256,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.publish_run import publish_studio_export_run
import sciplot_core.studio_core.prepare_generated_transaction as prepare_transaction_module
import sciplot_core.workflow.single_task_bundle as single_task_bundle_module
import sciplot_core.workflow.request_run as request_run_module


RULE_ID = "dsc_curve"
FIGURE_ID = "dsc_heat_flow_vs_temperature"
EXPECTED_SAMPLE_ORDER = ("UDC 2", "UDC 3", "UDC 4")


def _fixture() -> Path:
    source = resolve_fixture_path(str(get_rule(RULE_ID).fixture_path or ""))
    assert source.is_file()
    return source


def _copy_source(tmp_path: Path) -> Path:
    source_root = tmp_path / "dsc_source"
    source_root.mkdir()
    source = source_root / _fixture().name
    shutil.copy2(_fixture(), source)
    shutil.copy2(
        _fixture().with_name("digitization_provenance.json"),
        source_root,
    )
    return source


def _write_project(
    tmp_path: Path,
    *,
    source: Path | None = None,
) -> tuple[Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "input": str(source or _fixture()),
                "rule_id": RULE_ID,
                "template": "curve",
                "explicit_template_selection": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return project_dir, request_path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.comprehensive
def test_dsc_studio_activates_exact_single_task_registry(tmp_path: Path) -> None:
    project_dir, request_path = _write_project(tmp_path)

    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )

    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    assert plan.selected_figure_ids == (FIGURE_ID,)
    assert plan.tasks[0].sample_order == EXPECTED_SAMPLE_ORDER
    assert plan.selection_policy == "registered_single_curve"
    assert plan.source_sha256 == source_tree_sha256(_fixture())

    registry = json.loads(
        (project_dir / "studio" / "figure_set.json").read_text(encoding="utf-8")
    )
    assert registry["version"] == 2
    assert [item["figure_id"] for item in registry["figures"]] == [FIGURE_ID]
    assert registry["figures"][0]["resolved_figure_task"] == plan.tasks[0].to_payload()
    document = Path(str(prepared["document"]))
    spec = json.loads(document.with_name("spec.json").read_text(encoding="utf-8"))
    assert document.is_file()
    assert spec["source_request"]["resolved_figure_task"] == plan.tasks[0].to_payload()
    assert [item["label"] for item in spec["series"]] == list(EXPECTED_SAMPLE_ORDER)


@pytest.mark.comprehensive
def test_dsc_studio_publication_delivers_exact_single_figure(tmp_path: Path) -> None:
    project_dir, request_path = _write_project(tmp_path)
    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )
    document = Path(str(prepared["document"]))
    exported = export_studio_document(document, formats=["pdf", "tiff_300"])

    studio_run = publish_studio_export_run(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document,
        exports=exported["exports"],
        export_document_sha256=str(exported["document_sha256"]),
    )

    completed = ResolvedFigurePlan.from_payload(studio_run["resolved_figure_plan"])
    assert completed.status == "ready"
    assert completed.selected_figure_ids == (FIGURE_ID,)
    assert completed.outcomes[0].delivery_artifacts_complete is True
    delivery = studio_run["delivery_package"]
    assert delivery["full_figure_set_complete"] is True
    assert [item["figure_id"] for item in delivery["project_documents"]] == [FIGURE_ID]
    assert {item["figure_id"] for item in delivery["figures"]} == {FIGURE_ID}
    assert len(delivery["project_documents"]) == 1
    assert len(delivery["figures"]) == 2


@pytest.mark.comprehensive
def test_dsc_studio_render_failure_rolls_back_request_and_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir, request_path = _write_project(tmp_path)
    original_request = request_path.read_bytes()

    def reject_render(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic DSC Studio render failure")

    monkeypatch.setattr(prepare_transaction_module, "_write_veusz_document", reject_render)

    with pytest.raises(RuntimeError, match="DSC Studio render failure"):
        generate_studio_document(
            project_dir=project_dir,
            request_path=request_path,
            rule_id=None,
            template=None,
            project_name=None,
        )

    assert request_path.read_bytes() == original_request
    assert not (project_dir / "studio" / "document.vsz").exists()
    assert not (project_dir / "studio" / "spec.json").exists()
    assert not (project_dir / "studio" / "figure_set.json").exists()
    assert not list(project_dir.rglob(".sciplot-studio-prepare-*"))


@pytest.mark.comprehensive
def test_dsc_workflow_delivers_the_same_completed_single_task_plan(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "workflow_request.json"
    output_dir = tmp_path / "workflow_output"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(_fixture()),
                "output": str(output_dir),
                "rule_id": RULE_ID,
                "exports": ["pdf", "tiff_300"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = workflow.run_request(request_path)

    plan = ResolvedFigurePlan.from_payload(manifest["resolved_figure_plan"])
    assert plan.status == "ready"
    assert plan.selected_figure_ids == (FIGURE_ID,)
    assert plan.tasks[0].sample_order == EXPECTED_SAMPLE_ORDER
    assert (
        manifest["result"]["terminal_render_requests"][0]["resolved_figure_task"]
        == plan.tasks[0].to_payload()
    )
    assert plan_source_figure_ids(plan) == {
        artifact: FIGURE_ID
        for artifact in plan.outcomes[0].artifacts
        if Path(artifact).suffix.casefold() in {".vsz", ".pdf", ".tiff"}
    }
    delivery = manifest["delivery_package"]
    assert [item["figure_id"] for item in delivery["project_documents"]] == [FIGURE_ID]
    assert {item["figure_id"] for item in delivery["figures"]} == {FIGURE_ID}
    assert len(delivery["project_documents"]) == 1
    assert len(delivery["figures"]) == 2
    assert manifest["publish_gates"]["passed"] is True, manifest["publish_gates"]


@pytest.mark.comprehensive
def test_dsc_workflow_render_failure_restores_existing_managed_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "workflow_output"
    (output_dir / "figures").mkdir(parents=True)
    (output_dir / "figures" / "old.pdf").write_bytes(b"old-pdf")
    (output_dir / "manifest.json").write_text('{"state":"ready"}', encoding="utf-8")
    (output_dir / "notes.txt").write_text("keep", encoding="utf-8")
    before = _snapshot(output_dir)
    request_path = tmp_path / "workflow_request.json"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(_fixture()),
                "output": str(output_dir),
                "rule_id": RULE_ID,
                "exports": ["pdf", "tiff_300"],
            }
        ),
        encoding="utf-8",
    )

    def reject_render(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("synthetic DSC Workflow render failure")

    monkeypatch.setattr(single_task_bundle_module, "render_to_dir", reject_render)

    with pytest.raises(RuntimeError, match="DSC Workflow render failure"):
        workflow.run_request(request_path)

    assert _snapshot(output_dir) == before
    assert not list(
        output_dir.parent.glob(f".{output_dir.name}.sciplot-managed-backup-*")
    )


@pytest.mark.comprehensive
def test_dsc_workflow_uses_its_bound_snapshot_after_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_source(tmp_path)
    output_dir = tmp_path / "workflow_output"
    request_path = tmp_path / "workflow_request.json"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(source),
                "output": str(output_dir),
                "rule_id": RULE_ID,
                "exports": ["pdf", "tiff_300"],
            }
        ),
        encoding="utf-8",
    )
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
    assert (output_dir / "manifest.json").is_file()


def test_dsc_curve_rejects_cycle_workbooks_before_workflow_writes(
    tmp_path: Path,
) -> None:
    cycle_root = tmp_path / "cycle"
    cycle_root.mkdir()
    (cycle_root / "sample.xlsx").write_bytes(b"not an authorized cycle fixture")
    request_path = tmp_path / "cycle_request.json"
    output_dir = tmp_path / "cycle_output"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(cycle_root),
                "output": str(output_dir),
                "rule_id": RULE_ID,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="dsc_curve_transform_invalid",
    ):
        workflow.run_request(request_path)

    assert not (output_dir / "manifest.json").exists()
    assert not (output_dir / "figures").exists()


def test_dsc_global_resolver_rejects_cycle_workbook_identity(tmp_path: Path) -> None:
    workbook = tmp_path / "cycle.xlsx"
    workbook.write_bytes(b"not an authorized cycle fixture")

    with pytest.raises(FigurePlanResolutionError) as exc_info:
        from sciplot_core.figure_plan import resolve_figure_plan

        resolve_figure_plan(
            rule_id=RULE_ID,
            template="curve",
            study_model={},
            input_path=workbook,
            request={"template": "curve"},
        )

    assert exc_info.value.reason_code == "dsc_curve_transform_invalid"
