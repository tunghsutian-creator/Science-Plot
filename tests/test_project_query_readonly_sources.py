"""Source inspection reads exact live or cold facts without materializing views."""
import json
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path

import pytest
from test_project_query import project as legacy_project, _delivery
from test_project_query_source_versions import generation, indicator
from test_project_delivery_runtime import _project_and_delivery

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, directories
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.project_store.runtime import (
    incoming_source_runtime, sealed_source_runtime, project_candidate_runtime,
    inspect_runtime_source_file, inspect_runtime_source_tree,
)
from sciplot_core.project_store import ProjectConflict, ProjectStoreError
from sciplot_core.project_store.io import digest
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.project_query_paths import bound_delivery_project
from sciplot_core.studio_core.project_query_evidence import _exports_match
from sciplot_core.delivery.package_validation import verify_delivery_package


def inventory(root):
    return {str(path.relative_to(root)): (file_sha256(path), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def no_views(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("Read-only query attempted filesystem source-view materialization")

    def reject_directory_view(io, value, literal, *, expected_sha256=None):
        # External FILE resolution checks this dispatch first. Its exact
        # no-prefix branch returns None without creating any directory view.
        if directories._prefix(value, literal, {"": io.root, **io.locations}) is None:
            return None
        reject()

    monkeypatch.setattr(directories, "resolve", reject_directory_view)
    monkeypatch.setattr(FileProjectStore, "resolve_source", reject)


def processed_project(tmp_path):
    project = legacy_project.__wrapped__(tmp_path)
    original = tmp_path / "original.csv"
    original.write_bytes((project / "source/data.csv").read_bytes())
    for spec in (project / "studio").rglob("*.json"):
        value = json.loads(spec.read_bytes())
        if "series" in value:
            value["series"][0]["source_artifacts"] = [{"path": str(original), "sha256": file_sha256(original)}]
            spec.write_text(json.dumps(value))
    request_path = project / "plot_request.json"
    request = json.loads(request_path.read_bytes())
    request["input"] = str(project / "source")
    request_path.write_text(json.dumps(request))
    delivery = _delivery(project)
    store = FileProjectStore(project, locations={"delivery": delivery})
    before = store.snapshot(import_legacy=True)
    command = ProjectCommand.create("source_update", "fixture-source-facts", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={"fixture": "original source"})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=(
        PreparedSource("a" * 32, str(original), file_sha256(original), original.read_bytes()),)))
    return project, delivery, store


def test_public_processed_directory_inspection_is_completely_read_only(tmp_path, monkeypatch):
    project, _delivery_root, _store = processed_project(tmp_path)
    expected = source_tree_sha256(project / "source")
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = inspect_project(project)
    assert result["source"]["input"]["sha256"] == expected
    assert result["source"]["prepared"]["current"] is True
    assert inventory(tmp_path) == before


def test_delivery_entry_with_processed_directory_never_materializes(tmp_path, monkeypatch):
    project, delivery, store = processed_project(tmp_path)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(store):
        assert bound_delivery_project(delivery) == project
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("directory", [False, True])
def test_cold_source_facts_need_no_existing_or_new_source_views(tmp_path, monkeypatch, directory):
    store, request, source, _paths = generation(tmp_path, directory=directory)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    store.root.rename(tmp_path / "project-offline")
    source.rename(tmp_path / "raw-offline")
    assert not (cold.root / ".sciplot_store/sources").exists()
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = indicator(cold, request)
    assert result["current"] is True
    assert result["input"]["sha256"] == request["resolved_figure_plan"]["source_sha256"]
    assert not source.exists() and not (cold.root / ".sciplot_store/sources").exists()
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("mutation", ["bytes", "missing", "extra", "symlink"])
def test_live_directory_mutation_is_refused_without_creating_source_views(tmp_path, monkeypatch, mutation):
    project, _delivery_root, _store = processed_project(tmp_path)
    source = project / "source/data.csv"
    if mutation == "bytes":
        source.write_bytes(b"foreign prepared source")
    elif mutation == "missing":
        source.unlink()
    elif mutation == "extra":
        source.with_name("unknown.csv").write_bytes(b"unknown neighbor")
    else:
        source.unlink()
        source.symlink_to(tmp_path / "outside-not-readable")
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = inspect_project(project)
    assert result["source"]["input"]["error"]
    assert result["source"]["input"]["sha256"] is None
    assert inventory(tmp_path) == before


def test_malformed_delivery_file_record_rejects_directory_before_resolving(tmp_path, monkeypatch):
    project, delivery, store = _project_and_delivery(tmp_path)
    manifest = json.loads((project / "runs/studio_001/manifest.json").read_bytes())
    record = deepcopy(manifest["delivery_package"])
    record["data_csvs"][0]["path"] = str(delivery / "data")
    record["data_csvs"][0].pop("sha256")
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(store):
        assert verify_delivery_package(record, expected_root=delivery, expected_manifest=manifest)["passed"] is False
    assert inventory(tmp_path) == before


def test_malformed_qa_export_rejects_directory_before_resolving(tmp_path, monkeypatch):
    project, _delivery_root, store = _project_and_delivery(tmp_path)
    run = project / "runs/studio_001"
    manifest = json.loads((run / "manifest.json").read_bytes())
    manifest["result"]["exports"] = [{"path": str(run / "studio"),
        "sha256": source_tree_sha256(run / "studio"), "format": "pdf", "document": str(run / "studio/document.vsz")}]
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(store):
        assert _exports_match(run, manifest, []) is False
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("mode", ["incoming", "sealed"])
@pytest.mark.parametrize("candidate", [False, True])
def test_explicit_source_phase_never_reverts_to_parent_generation_or_creates_views(tmp_path, monkeypatch, mode, candidate):
    from test_project_incoming_sources import changed_external, private_clone

    store, raw, fresh, sealed, _old = changed_external(tmp_path)
    snapshot = store.snapshot()
    private = private_clone(store, tmp_path) if candidate else None
    selected = fresh if mode == "incoming" else sealed
    scope = incoming_source_runtime if mode == "incoming" else sealed_source_runtime
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with scope(store, [selected]), (project_candidate_runtime(store, private) if private else nullcontext()):
        observed = inspect_runtime_source_file(raw, expected_sha256=selected.sha256, source_id=selected.source_id)
        assert observed.sha256 == selected.sha256
        assert observed.physical == (raw if mode == "incoming" else None)
        assert inspect_runtime_source_tree(raw) == digest({"kind": "file", "content_sha256": selected.sha256})
        for wrong in ({"expected_sha256": "0" * 64}, {"source_id": "b" * 32}):
            with pytest.raises(ProjectConflict):
                inspect_runtime_source_file(raw, **wrong)
        with pytest.raises(ProjectStoreError):
            inspect_runtime_source_tree(raw.parent)
    assert selected_source_resolver() is None and store.snapshot() == snapshot
    assert inventory(tmp_path) == before
    with project_runtime(store), pytest.raises(ProjectConflict):
        inspect_runtime_source_file(raw, expected_sha256=sealed.sha256, source_id=sealed.source_id)


def test_private_candidate_observation_uses_its_actual_bytes_and_protects_sources(tmp_path, monkeypatch):
    from test_project_candidate_runtime import fixture_candidate

    store, snapshot, private = fixture_candidate(tmp_path)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_candidate_runtime(store, private):
        document = private / "studio/document.vsz"
        document.write_bytes(b"candidate-only document")
        observed = inspect_runtime_source_file(store.root / "studio/document.vsz")
        assert observed.physical == document and observed.sha256 == file_sha256(document)
        raw = private / "raw/source.csv"
        entry = snapshot["files"]["raw/source.csv"]
        assert inspect_runtime_source_file(store.root / "raw/source.csv",
            expected_sha256=entry["sha256"], source_id=entry["file_id"]).physical == raw
        raw.write_bytes(b"foreign raw candidate")
        with pytest.raises(ProjectConflict):
            inspect_runtime_source_tree(store.root / "raw")
    after = inventory(tmp_path)
    assert {key: value for key, value in after.items() if not key.startswith("private/")} == {
        key: value for key, value in before.items() if not key.startswith("private/")}


def test_mapping_query_uses_real_confirmed_loader_without_creating_source_views(tmp_path, monkeypatch):
    from test_task_mapping_plan import _mapped_case
    from sciplot_core.data_mapping.plan_binding import resolve_mapping_plan_request
    from sciplot_core.studio_core.project_query_evidence import source_indicators

    project = tmp_path / "project"
    project.mkdir()
    source, selection, execution = _mapped_case(project)
    request, binding = resolve_mapping_plan_request(source, selection)
    request["resolved_figure_plan"] = {"source_sha256": binding["effective_input_sha256"]}
    request["data_mapping_plan_binding"] = binding
    (project / "plot_request.json").write_text(json.dumps(request))
    spec = project / "studio/spec.json"
    spec.parent.mkdir()
    effective = Path(execution["effective_input"])
    spec.write_text(json.dumps({"series": [{"source_artifacts": [{"path": str(effective), "sha256": file_sha256(effective)}]}]}))
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(store):
        result = source_indicators(project, request, [{"status": "ready", "spec": str(spec)}])
    assert result["current"] is True and result["input"]["mapping_verified"] is True
    assert result["input"]["effective_input"] == str(effective)
    assert result["input"]["effective_sha256"] == binding["effective_input_sha256"]
    assert result["raw"]["current"] is True
    assert inventory(tmp_path) == before


def test_readonly_file_cap_never_expands_to_neighbor_or_complete_directory(tmp_path, monkeypatch):
    from sciplot_core.project_store import ResourceRoot

    project, raw = tmp_path / "project", tmp_path / "raw"
    project.mkdir()
    raw.mkdir()
    source = raw / "selected.csv"
    source.write_bytes(b"x,y\n1,2\n")
    (raw / "unselected.csv").write_bytes(b"neighbor not granted")
    store = FileProjectStore(project, locations={"raw": ResourceRoot(raw, (source.name,))})
    snapshot = store.snapshot(import_legacy=True)
    entry = snapshot["files"]["@raw/selected.csv"]
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(store):
        observed = inspect_runtime_source_file(source, expected_sha256=entry["sha256"], source_id=entry["file_id"])
        assert observed.sha256 == file_sha256(source) and observed.physical == source
        for target in (raw, raw / "unselected.csv", tmp_path / "foreign"):
            with pytest.raises(ProjectStoreError):
                inspect_runtime_source_tree(target)
        with pytest.raises(ProjectStoreError):
            inspect_runtime_source_file(raw / "unselected.csv")
        with pytest.raises(ProjectConflict):
            inspect_runtime_source_file(source, expected_sha256=source_tree_sha256(source))
    assert inventory(tmp_path) == before


def test_sealed_registered_member_precedes_private_candidate_without_creating_view(tmp_path, monkeypatch):
    from test_project_candidate_runtime import fixture_candidate
    from sciplot_core.project_store.incoming_sources import SourceExpectation

    store, snapshot, private = fixture_candidate(tmp_path)
    raw = store.root / "raw/source.csv"
    entry = snapshot["files"]["raw/source.csv"]
    selected = SourceExpectation(str(raw), entry["file_id"], entry["sha256"])
    before = inventory(tmp_path)
    assert not (store.root / ".sciplot_store/sources").exists()
    no_views(monkeypatch)
    with sealed_source_runtime(store, [selected]), project_candidate_runtime(store, private):
        observed = inspect_runtime_source_file(raw, expected_sha256=selected.sha256, source_id=selected.source_id)
        assert observed.physical is None and observed.sha256 == selected.sha256
        assert inspect_runtime_source_tree(raw) == digest({"kind": "file", "content_sha256": selected.sha256})
        document = private / "studio/document.vsz"
        document.write_bytes(b"current candidate document")
        assert inspect_runtime_source_file(store.root / "studio/document.vsz").physical == document
    after = inventory(tmp_path)
    assert {key: value for key, value in after.items() if not key.startswith("private/")} == {
        key: value for key, value in before.items() if not key.startswith("private/")}


@pytest.mark.parametrize("candidate", [False, True])
def test_incoming_file_scope_keeps_unrelated_registered_derived_tree_but_never_its_parent(tmp_path, monkeypatch, candidate):
    from test_project_incoming_sources import changed_external, private_clone

    store, raw, fresh, _sealed, _old = changed_external(tmp_path)
    private = private_clone(store, tmp_path) if candidate else None
    derived = store.root / "studio"
    expected = source_tree_sha256(derived)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with incoming_source_runtime(store, [fresh]), (project_candidate_runtime(store, private) if private else nullcontext()):
        assert inspect_runtime_source_tree(derived) == expected
        for target in (raw.parent, tmp_path / "unknown"):
            with pytest.raises(ProjectStoreError):
                inspect_runtime_source_tree(target)
    assert selected_source_resolver() is None and inventory(tmp_path) == before
