"""Saved raw-replicate query projects the independently verified composite file."""
import hashlib
import json
from pathlib import Path
from dataclasses import replace
from copy import deepcopy

import pytest

from test_project_query import project as legacy_project
from test_project_query_readonly_sources import inventory, no_views
from test_task_raw_replicate_mapping import original, native_boundary
from sciplot_core import task_control as control
from sciplot_core.data_mapping.plan_binding import resolve_mapping_plan_request
from sciplot_core.data_mapping.request_resolution import resolve_data_mapping_request
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.figure_plan import FigureOutcome, ResolvedFigurePlan
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.project_query_sources import mapping_source_files
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.figure_task_evidence import figure_registry_projection_from_task, figure_task_metric_projection


def saved_replicate_project(tmp_path, monkeypatch, *, omit_composite=False, legacy_live=False):
    source, intent, mapping = original(tmp_path)
    with monkeypatch.context() as setup:
        calls = native_boundary(setup, tmp_path)
        state = control.start_task({**intent, "mapping": mapping}, task_dir=tmp_path / "task")
        assert state["status"] == "complete" and len(calls) == 1
        plan = calls[0]["expected_plan"]
    request, binding = resolve_mapping_plan_request(source, state["data_mapping"])
    request["data_mapping_plan_binding"] = binding
    request["resolved_figure_plan"] = plan["resolved_figure_plan"]
    _effective_request, application = resolve_data_mapping_request(request, base_dir=tmp_path)
    effective = Path(application["effective_input"])
    assert binding["mapping_shape"] == "replicates" and effective.name == "selected_pairs.csv"
    assert str(effective) not in {record["path"] for record in application["mapped_outputs"]}
    project = legacy_project.__wrapped__(tmp_path / "saved")
    document, primary_spec = project / "studio/document.vsz", project / "studio/spec.json"
    figure_plan = ResolvedFigurePlan.from_payload(request["resolved_figure_plan"])
    assert len(figure_plan.tasks) == 1
    task = figure_plan.tasks[0]
    figure_plan = replace(figure_plan, outcomes=(FigureOutcome(task.figure_id, "editable", artifacts=(str(document), str(primary_spec))),))
    request["resolved_figure_plan"] = figure_plan.to_payload()
    for spec in (project / "studio").rglob("*.json"):
        payload = json.loads(spec.read_bytes())
        if "series" in payload:
            payload["series"][0]["source_artifacts"] = [{"path": item["path"], "sha256": item["sha256"]}
                                                       for item in application["mapped_outputs"]]
            payload["template"] = task.template
            payload["source_request"] = {"template": task.template, "resolved_figure_task": task.to_payload(),
                **figure_task_metric_projection(task, include_singular_metric=False)}
            spec.write_text(json.dumps(payload))
    (project / "plot_request.json").write_text(json.dumps(request))
    native_sha = file_sha256(document)
    registry = {"kind": "sciplot_studio_figure_set", "version": 2, "rule_id": figure_plan.rule_id,
        "plan_id": figure_plan.plan_id, "plan_sha256": figure_plan.plan_sha256, "status": "ready",
        "primary_figure_id": task.figure_id, "generated_from": str(project / "plot_request.json"),
        "primary_document": str(document), "registry_path": str(project / "studio/figure_set.json"),
        "resolved_figure_plan": figure_plan.to_payload(), "figures": [{**figure_registry_projection_from_task(task),
            "status": "ready", "document": str(document), "spec": str(primary_spec), "generated_hash": native_sha,
            "document_state": {"kind": "sciplot_vsz_document_state", "generated_hash": native_sha, "current_hash": native_sha}}]}
    (project / "studio/figure_set.json").write_text(json.dumps(registry))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    execution_root = Path(application["execution"]).parent
    paths = ([source, *(Path(item["path"]) for item in application["mapped_outputs"])] if legacy_live else
             [source, *(path for path in execution_root.rglob("*") if path.is_file())])
    if omit_composite:
        paths.remove(effective)
    prepared = tuple(PreparedSource(hashlib.sha256(str(path).encode()).hexdigest()[:32], str(path),
        file_sha256(path), path.read_bytes(), mode=path.stat().st_mode & 0o777) for path in paths)
    mutation = ProjectMutation({}, {}, prepared_sources=prepared)
    command = ProjectCommand.create("attachment_import", "replicate-facts", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)
    return project, store, source, effective, application


def test_public_saved_replicate_query_observes_registered_effective_composite_without_writes(tmp_path, monkeypatch):
    project, _store, source, effective, application = saved_replicate_project(tmp_path, monkeypatch)
    scientific_application = json.loads(json.dumps(application))
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = inspect_project(project)
    assert result["source"]["current"] is True, result["source"]
    assert result["source"]["input"]["mapping_verified"] is True
    assert result["source"]["input"]["effective_input"] == str(effective)
    assert result["source"]["raw"]["current"] is True
    assert application == scientific_application and source.is_file()
    assert inventory(tmp_path) == before


def test_verified_replicate_facts_include_the_distinct_registered_effective_file(tmp_path, monkeypatch):
    _project, store, _source, effective, application = saved_replicate_project(tmp_path, monkeypatch)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(store):
        facts = mapping_source_files(application, {})
    assert str(effective) in facts
    assert facts[str(effective)] == file_sha256(effective)
    assert {item["path"] for item in application["mapped_outputs"]}.issubset(facts)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("failure", ["missing", "versions", "changed", "foreign-effective"])
def test_replicate_composite_fact_requires_its_unique_unchanged_execution_binding(tmp_path, monkeypatch, failure):
    project, store, _source, effective, application = saved_replicate_project(
        tmp_path, monkeypatch, omit_composite=failure == "missing")
    supplied = deepcopy(application)
    if failure == "changed":
        effective.write_bytes(b"unknown composite replacement")
    elif failure == "versions":
        effective.write_bytes(effective.read_bytes() + b"\n")
        before = store.snapshot()
        source = PreparedSource(hashlib.sha256(str(effective).encode()).hexdigest()[:32], str(effective),
            file_sha256(effective), effective.read_bytes(), mode=effective.stat().st_mode & 0o777)
        mutation = ProjectMutation({}, {}, prepared_sources=(source,))
        command = ProjectCommand.create("figure_set", "another-composite-version", project_id=before["project_id"],
            expected_generation=before["generation"], read_set={}, write_set=[], request={})
        ProjectCommands(store).execute(command, lambda: mutation)
    elif failure == "foreign-effective":
        supplied["effective_input"] = str(tmp_path / "unbound-foreign.csv")
    scientific_application = deepcopy(supplied)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(store), pytest.raises(ProjectConflict):
        mapping_source_files(supplied, {})
    assert supplied == scientific_application and inventory(tmp_path) == before
    if failure != "foreign-effective":
        result = inspect_project(project)
        # Missing historical registration alone is not stale when the public
        # call obtains a fresh complete numeric witness. The naked fact port
        # above still rejects that request without the verified invocation.
        expected = failure == "missing"
        assert result["source"]["current"] is expected and result["source"]["input"]["mapping_verified"] is expected
        assert inventory(tmp_path) == before


def test_legacy_live_inspection_uses_current_witness_without_registering_missing_history(tmp_path, monkeypatch):
    project, store, _source, effective, application = saved_replicate_project(tmp_path, monkeypatch, legacy_live=True)
    snapshot = store.snapshot()
    unregistered = {str(effective), application["execution"]}
    assert not any(entry["locator"] in unregistered for versions in snapshot["sources"].values() for entry in versions.values())
    scientific_application = deepcopy(application)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = inspect_project(project)
    assert result["source"]["current"] is True and result["source"]["input"]["mapping_verified"] is True
    assert result["source"]["raw"]["current"] is True and result["source"]["prepared"]["current"] is True
    assert store.snapshot() == snapshot and application == scientific_application
    with project_runtime(store), pytest.raises(ProjectConflict):
        mapping_source_files(application, {})
    assert inventory(tmp_path) == before


def test_cold_partial_history_never_claims_numeric_verification_or_creates_views(tmp_path, monkeypatch):
    project, store, source, _effective, _application = saved_replicate_project(tmp_path, monkeypatch, legacy_live=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    project.rename(tmp_path / "project-offline")
    (tmp_path / "task").rename(tmp_path / "task-offline")
    source.rename(tmp_path / "raw-offline.csv")
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = inspect_project(cold.root)
    assert result["source"]["input"]["mapping_verified"] is None and result["source"]["input"]["current"] is None
    assert not (cold.root / ".sciplot_store/sources").exists()
    assert inventory(tmp_path) == before
