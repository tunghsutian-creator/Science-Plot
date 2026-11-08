"""Generated mechanical preparation reaches real native and Store boundaries."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import pytest

from public_multitask_inputs import mechanical_source
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.mechanical_figure_contract import mechanical_figure_contract
from sciplot_core.native_process import run_cold_worker
from sciplot_core.native_process.session import _close_workers
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio import prepare_studio_document
from sciplot_core.studio_core.project_export import export_project_document
from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.workflow import run_request
from sciplot_core.workflow.project_requests import _publication_store


def _bound_files(store, paths):
    snapshot = store.snapshot()
    assert snapshot["outside_changes"] == {}
    result = {}
    for path in paths:
        content = path.read_bytes()
        logical = store.logical_path(path)
        assert store.read_bytes(logical, generation=snapshot["generation"]) == content
        assert snapshot["files"][logical]["sha256"] == file_sha256(path)
        result[path] = content
    return snapshot, result


def _spec_science(spec, task, expected_curves):
    contract = mechanical_figure_contract("compression_curve")
    expected = next(item for item in contract.tasks if item.figure_id == task.figure_id)
    assert spec["source_request"]["resolved_figure_task"] == task.to_payload()
    assert spec["template"] == task.template == expected.template
    assert spec["axes"]["x"]["label"] == expected.x_label
    assert spec["axes"]["y"]["label"] == expected.y_label
    series = spec["series"]
    if task.figure_id == contract.primary_task.figure_id:
        assert len(series) == 3
        assert [item["label"] for item in series] == list(task.sample_order)
        for item, points in zip(series, expected_curves, strict=True):
            assert tuple(zip(item["x_values"], item["y_values"], strict=True)) == points
    else:
        assert len(series) == 1
        assert series[0]["label"] == "Cedar"
        assert series[0]["y_values"] == [10., 20., 40.]
        categorical = spec["categorical"]
        assert categorical["summary_statistic"] == "median_iqr"
        assert categorical["raw_values_preserved"] is True
        group = categorical["groups"][0]
        assert group["replicate_count"] == 3
        assert group["raw_values"] == [10., 20., 40.]
        assert group["descriptive_statistics"]["median"] == 20.
        assert group["raw_points_visible"] is True
    return [{key: item[key] for key in ("label", "x_values", "y_values")}
            for item in series]


def _cold_reopen_export(store, plan, documents, specs, expected_curves, output):
    before, bound = _bound_files(store, [*documents, *specs])
    result, science = [], []
    with project_runtime(store, generation=before["generation"]):
        for task, document, specification in zip(plan.tasks, documents, specs, strict=True):
            spec = json.loads(bound[specification])
            science.append(_spec_science(spec, task, expected_curves))
            for item in spec["series"]:
                assert item["source_artifacts"]
                for artifact in item["source_artifacts"]:
                    actual = resolve_source_path(Path(artifact["path"]), expected_sha256=artifact["sha256"])
                    assert file_sha256(actual) == artifact["sha256"]
            command = [sys.executable, "-m", "sciplot_core.veusz_worker", "export-document",
                       str(document), "--formats", "pdf,tiff_300", "--out",
                       str(output / task.figure_id), "--audit-spec", str(specification)]
            completed = run_cold_worker(command, text=True, capture_output=True, check=True,
                                        timeout=180, env=veusz_worker_environment())
            assert completed.returncode == 0
            payload = json.loads(completed.stdout)
            audit = payload["document_audit"]
            assert audit["status"] == "passed"
            assert audit["document"]["sha256"] == file_sha256(document)
            assert audit["spec"]["sha256"] == file_sha256(specification)
            assert audit["unit_count"] == len(audit["units"]) > 0
            assert all(dataset["value_sha256"] and dataset["shape"]
                       for unit in audit["units"] for dataset in unit["datasets"])
            exports = payload["exports"]
            assert {item["format"] for item in exports} == {"pdf", "tiff_300"}
            assert all(Path(item["path"]).stat().st_size > 0 for item in exports)
            result.append({"task": task.to_payload(), "returncode": completed.returncode,
                           "document_sha256": file_sha256(document),
                           "spec_sha256": file_sha256(specification), "audit": audit,
                           "exports": exports})
    assert {path: path.read_bytes() for path in bound} == bound
    assert store.snapshot() == before
    return science, result


@pytest.mark.focused
def test_generated_mechanical_workflow_and_studio_cold_native_lifecycle(tmp_path):
    source = mechanical_source(tmp_path / "original", "compression_curve")
    raw = source.read_bytes()
    rows = list(csv.reader(raw.decode().splitlines()))
    assert rows[1] == ["%", "MPa"] * 3
    expected_curves = tuple(tuple((float(row[c]), float(row[c + 1])) for row in rows[3:])
                            for c in (0, 2, 4))
    expected_labels = tuple(f"Cedar__repeat {n}" for n in (1, 2, 3))
    options = {"input": str(source), "rule_id": "compression_curve", "recipe": "auto", "template": "curve",
               "replicate_mode": "individual", "exports": ["pdf", "tiff_300"]}
    evidence = {}
    try:
        workflow_root = tmp_path / "workflow"
        workflow_root.mkdir()
        workflow_request = workflow_root / "plot_request.json"
        workflow_request.write_text(json.dumps({**options,
            "output": str(workflow_root / "runs/run_001"),
            "delivery_output": str(tmp_path / "workflow_delivery")}))
        (workflow_root / "intake_manifest.json").write_text(json.dumps({
            "kind": "sciplot_intake_project", "version": 1,
            "project_slug": workflow_root.name}))
        workflow_store = _publication_store(workflow_root)
        workflow_before = workflow_store.snapshot(import_legacy=True)
        workflow = run_request(workflow_request)
        workflow_manifest = Path(workflow["output"]) / "manifest.json"
        workflow_after, committed = _bound_files(workflow_store, [workflow_manifest])
        assert workflow_after["sequence"] == workflow_before["sequence"] + 1
        canonical_workflow = json.loads(committed[workflow_manifest])
        assert canonical_workflow["resolved_figure_plan"] == workflow["resolved_figure_plan"]
        workflow_plan = ResolvedFigurePlan.from_payload(canonical_workflow["resolved_figure_plan"])
        assert workflow_plan.status == "ready"
        assert canonical_workflow["ready_to_use"] is True
        assert canonical_workflow["publish_gates"]["passed"] is True
        assert len(canonical_workflow["result"]["exports"]) == 4
        workflow_documents = list(map(Path, canonical_workflow["result"]["veusz_documents"]))
        workflow_specs = list(map(Path, canonical_workflow["result"]["veusz_specs"]))
        workflow_science, evidence["workflow"] = _cold_reopen_export(
            workflow_store, workflow_plan, workflow_documents, workflow_specs,
            expected_curves, tmp_path / "cold_workflow")

        studio_root = tmp_path / "studio_project"
        studio_root.mkdir()
        studio_request = studio_root / "plot_request.json"
        studio_request.write_text(json.dumps({**options,
            "delivery_output": str(tmp_path / "studio_delivery")}))
        prepared = prepare_studio_document(studio_request)
        studio_store = project_store(studio_root, with_snapshot=True)
        registry_path = studio_root / "studio/figure_set.json"
        _, registered = _bound_files(studio_store, [registry_path])
        registry = json.loads(registered[registry_path])
        entries = registry["figures"]
        assert len(entries) == 2 and all(item["status"] == "ready" for item in entries)
        studio_documents = [Path(item["document"]) for item in entries]
        studio_specs = [Path(item["spec"]) for item in entries]
        _, native_before = _bound_files(studio_store, [*studio_documents, *studio_specs])
        published = export_project_document(project_dir=studio_root,
            request_path=studio_request, document_path=Path(prepared["document"]),
            formats=["pdf", "tiff_300"])
        summary = published.run_payload
        assert published.ready_to_use and summary["project_command"]["phase"] == "complete"
        studio_store = project_store(studio_root, with_snapshot=True)
        assert studio_store.locations["delivery"] == tmp_path / "studio_delivery"
        published_generation = studio_store.snapshot()
        assert summary["project_command"]["generation"] == published_generation["generation"]
        manifest_path = Path(summary["manifest"])
        _, committed = _bound_files(studio_store, [manifest_path])
        studio_manifest = json.loads(committed[manifest_path])
        assert studio_manifest["result"]["exports"] == summary["exports"] == published.exports
        assert len(published.exports) == 4
        assert studio_manifest["delivery_verification"]["passed"] is True
        studio_plan = ResolvedFigurePlan.from_payload(studio_manifest["resolved_figure_plan"])
        assert studio_plan.status == "ready"
        assert studio_plan.plan_sha256 == workflow_plan.plan_sha256
        assert studio_plan.tasks == workflow_plan.tasks
        assert studio_plan.tasks[0].sample_order == expected_labels
        assert studio_plan.tasks[0].replicate_counts == tuple((label, 1) for label in expected_labels)
        assert studio_plan.tasks[1].replicate_counts == (("Cedar", 3),)
        reopened = prepare_studio_document(studio_root)
        assert reopened["preserved_existing_document"] is True
        assert Path(reopened["document"]) == Path(prepared["document"])
        assert {path: path.read_bytes() for path in native_before} == native_before
        studio_science, evidence["studio"] = _cold_reopen_export(
            studio_store, studio_plan, studio_documents, studio_specs,
            expected_curves, tmp_path / "cold_studio")
        assert studio_science == workflow_science
        assert [item["audit"]["units"] for item in evidence["studio"]] == [
            item["audit"]["units"] for item in evidence["workflow"]]
        assert source.read_bytes() == raw
        evidence.update({"source_sha256": file_sha256(source),
            "plan_sha256": studio_plan.plan_sha256,
            "workflow_generation": workflow_store.snapshot()["generation"],
            "studio_generation": studio_store.snapshot()["generation"]})
        (tmp_path / "mechanical-native-lifecycle-evidence.json").write_text(json.dumps(evidence, indent=2))
    finally:
        _close_workers()
