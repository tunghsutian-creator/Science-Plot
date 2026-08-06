from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sciplot_core.semantic as semantic_module
import sciplot_core.studio_core.figure_set_prepare as figure_set_prepare_module
from sciplot_core import workflow
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.delivery.plan_binding import plan_source_figure_ids
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.materials_rules import get_rule
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.publish_run import publish_studio_export_run


RULE_ID = "rheology_temperature_sweep"
EXPECTED_FIGURE_IDS = (
    "storage_modulus_vs_temperature",
    "tan_delta_vs_temperature",
)
EXPECTED_SAMPLE_ORDER = ("PA-2", "D-PA", "SD-PA", "S-PA")


def _temperature_fixture() -> Path:
    fixture = resolve_fixture_path(str(get_rule(RULE_ID).fixture_path or ""))
    assert fixture.is_dir()
    return fixture


def _write_project(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    request_path.write_text(
        json.dumps(
            {
                "input": str(_temperature_fixture()),
                "rule_id": RULE_ID,
                "template": "point_line",
                "explicit_template_selection": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return project_dir, request_path


@pytest.mark.comprehensive
def test_temperature_studio_activates_exact_two_task_plan_with_one_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir, request_path = _write_project(tmp_path)
    preparation_calls: list[Path] = []
    real_prepare = semantic_module.prepare_semantic_source

    def prepare_spy(source: Path, **kwargs: Any) -> dict[str, Any]:
        preparation_calls.append(source.expanduser().resolve())
        return real_prepare(source, **kwargs)

    monkeypatch.setattr(semantic_module, "prepare_semantic_source", prepare_spy)

    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )

    assert preparation_calls == [_temperature_fixture().resolve()]
    request = json.loads(request_path.read_text(encoding="utf-8"))
    plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    assert plan.selected_figure_ids == EXPECTED_FIGURE_IDS
    assert plan.status == "planned"
    assert all(task.sample_order == EXPECTED_SAMPLE_ORDER for task in plan.tasks)

    registry_path = project_dir / "studio" / "figure_set.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["version"] == 2
    assert [item["figure_id"] for item in registry["figures"]] == list(
        EXPECTED_FIGURE_IDS
    )
    editable_plan = ResolvedFigurePlan.from_payload(registry["resolved_figure_plan"])
    assert editable_plan.plan_sha256 == plan.plan_sha256
    assert editable_plan.status == "editable"
    assert Path(str(prepared["document"])).is_file()
    for task, entry in zip(plan.tasks, registry["figures"], strict=True):
        assert entry["resolved_figure_task"] == task.to_payload()
        document = Path(entry["document"])
        spec = json.loads(Path(entry["spec"]).read_text(encoding="utf-8"))
        assert document.is_file()
        assert spec["source_request"]["resolved_figure_task"] == task.to_payload()
        assert [item["label"] for item in spec["series"]] == list(EXPECTED_SAMPLE_ORDER)

    preparation_steps = [
        step
        for step in request["transform_ledger"]["steps"]
        if step.get("implementation_ref")
        == "sciplot_core.semantic.prepare_semantic_source"
    ]
    assert len(preparation_steps) == 1
    assert "source_attestation" not in request
    assert "_terminal_source_prepared" not in request


@pytest.mark.comprehensive
def test_temperature_studio_second_task_failure_rolls_back_both_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir, request_path = _write_project(tmp_path)
    original_request = request_path.read_bytes()

    def reject_secondary(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic temperature secondary failure")

    monkeypatch.setattr(
        figure_set_prepare_module,
        "_write_veusz_document",
        reject_secondary,
    )

    with pytest.raises(RuntimeError, match="temperature secondary failure"):
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
    assert not list((project_dir / "studio").rglob("*.vsz"))


@pytest.mark.comprehensive
def test_temperature_studio_publication_delivers_two_complete_figure_members(
    tmp_path: Path,
) -> None:
    project_dir, request_path = _write_project(tmp_path)
    prepared = generate_studio_document(
        project_dir=project_dir,
        request_path=request_path,
        rule_id=None,
        template=None,
        project_name=None,
    )
    document = Path(str(prepared["document"]))
    exported = export_studio_document(
        document,
        formats=["pdf", "tiff_300"],
    )

    studio_run = publish_studio_export_run(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document,
        exports=exported["exports"],
        export_document_sha256=str(exported["document_sha256"]),
    )

    assert studio_run["figure_set_export_scope"]["supported_figure_ids"] == list(
        EXPECTED_FIGURE_IDS
    )
    completed = ResolvedFigurePlan.from_payload(studio_run["resolved_figure_plan"])
    assert completed.status == "ready"
    assert completed.selected_figure_ids == EXPECTED_FIGURE_IDS
    assert all(outcome.delivery_artifacts_complete for outcome in completed.outcomes)
    assert studio_run["delivery_package"]["full_figure_set_complete"] is True
    assert studio_run["delivery_verification"]["passed"] is True

    manifest = json.loads(Path(studio_run["manifest"]).read_text(encoding="utf-8"))
    assert manifest["resolved_figure_plan"] == completed.to_payload()
    assert len(manifest["veusz_documents"]) == 2
    assert {item["figure_id"] for item in manifest["result"]["exports"]} == set(
        EXPECTED_FIGURE_IDS
    )
    delivery = studio_run["delivery_package"]
    assert {item["figure_id"] for item in delivery["figures"]} == set(
        EXPECTED_FIGURE_IDS
    )
    assert {item["figure_id"] for item in delivery["project_documents"]} == set(
        EXPECTED_FIGURE_IDS
    )
    assert len(delivery["figures"]) == 4
    assert len(delivery["project_documents"]) == 2


@pytest.mark.comprehensive
def test_temperature_workflow_delivers_the_same_completed_two_task_plan(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "workflow_request.json"
    output_dir = tmp_path / "workflow_output"
    request_path.write_text(
        json.dumps(
            {
                "recipe": "auto",
                "input": str(_temperature_fixture()),
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
    assert plan.selected_figure_ids == EXPECTED_FIGURE_IDS
    assert all(task.sample_order == EXPECTED_SAMPLE_ORDER for task in plan.tasks)
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
    delivery = manifest["delivery_package"]
    assert {item["figure_id"] for item in delivery["figures"]} == set(
        EXPECTED_FIGURE_IDS
    )
    assert [item["figure_id"] for item in delivery["project_documents"]] == list(
        EXPECTED_FIGURE_IDS
    )
    assert len(delivery["figures"]) == 4
    assert len(delivery["project_documents"]) == 2
    preparation_steps = [
        step
        for step in manifest["transform_ledger"]["steps"]
        if step.get("implementation_ref")
        == "sciplot_core.semantic.prepare_semantic_source"
    ]
    assert len(preparation_steps) == 1
    assert manifest["publish_gates"]["passed"] is True
