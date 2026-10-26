"""Confirmed mapping query verifies live domains without creating cold IO views."""
import hashlib
import json
from pathlib import Path

from test_project_query_readonly_sources import inventory, no_views
from sciplot_core.data_mapping import create_data_mapping_confirmation, execute_data_mapping_proposal
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.project_query_evidence import source_indicators


def mapped_project(tmp_path, *, physical_data=False):
    project, task = tmp_path / "project", tmp_path / "external-task"
    project.mkdir(parents=True)
    task.mkdir()
    source_root = project if physical_data else task
    names = ("first",) if physical_data else ("first", "second")
    source = source_root / ("raw.csv" if physical_data else "raw")
    if not physical_data:
        source.mkdir()
    raw_paths = [source] if physical_data else [source / (name + ".csv") for name in names]
    for path in raw_paths:
        path.write_text("Wavelength (nm),Absorbance (a.u.)\n400,0.3\n450,0.7\n")
    base = task / "base.json"
    base.write_text(json.dumps({"input": str(source), "rule_id": "uvvis_spectrum", "template": "curve"}))
    proposal = DataMappingProposal(proposal_id="exact-two-tables", base_request_sha256=file_sha256(base),
        provider="external_task", sources=tuple(DataSourceReference(name, str(path.relative_to(source_root)), file_sha256(path))
                                                for name, path in zip(names, raw_paths, strict=True)),
        columns=tuple(column for name in names for column in (
            DataColumnMapping(name, 0, "Wavelength (nm)", "x", expected_header="Wavelength (nm)"),
            DataColumnMapping(name, 1, "Absorbance (a.u.)", "y", expected_header="Absorbance (a.u.)"))),
        sample_labels={name: name for name in names},
        request_patch={"rule_id": "uvvis_spectrum", "template": "curve"})
    confirmation = create_data_mapping_confirmation(proposal, source_root=source_root, request_path=base,
        output_root=task / "mappings", confirmed_by="test")
    execution = execute_data_mapping_proposal(proposal, confirmation, source_root=source_root,
        request_path=base, output_root=task / "mappings")
    request = json.loads(base.read_bytes())
    request["data_mapping_execution"] = str(Path(execution["output_root"]) / "execution.json")
    request["data_mapping_proposal_id"] = proposal.proposal_id
    request["resolved_figure_plan"] = {"source_sha256": source_tree_sha256(Path(execution["effective_input"]))}
    (project / "plot_request.json").write_text(json.dumps(request))
    spec = project / "studio/spec.json"
    spec.parent.mkdir()
    records = [{"path": item["path"], "sha256": item["sha256"]} for item in execution["outputs"]]
    spec.write_text(json.dumps({"series": [{"source_artifacts": records}]}))
    outputs = [Path(item["path"]) for item in execution["outputs"]]
    locations = {"mapping": ResourceRoot(outputs[0].parent, tuple(path.name for path in outputs))} if physical_data else {}
    store = FileProjectStore(project, locations=locations)
    before = store.snapshot(import_legacy=True)
    paths = [Path(request["data_mapping_execution"])] if physical_data else [*raw_paths, *outputs]
    mutation = ProjectMutation({}, {}, prepared_sources=tuple(PreparedSource(
        hashlib.sha256(str(path).encode()).hexdigest()[:32], str(path), file_sha256(path), path.read_bytes(),
        mode=path.stat().st_mode & 0o777) for path in paths))
    command = ProjectCommand.create("attachment_import", "exact-mapping-inputs", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)
    assert Path(execution["effective_input"]).is_file() if physical_data else Path(execution["effective_input"]).is_dir()
    return store, request, task, spec, execution


def inspect(store, request, spec):
    with project_runtime(store):
        return source_indicators(store.root, request, [{"status": "ready", "spec": str(spec)}])


def test_live_external_mapping_directory_verifies_complete_domain_without_source_views(tmp_path, monkeypatch):
    store, request, _task, spec, execution = mapped_project(tmp_path)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = inspect(store, request, spec)
    assert result["current"] is True and result["input"]["mapping_verified"] is True
    assert result["input"]["effective_sha256"] == request["resolved_figure_plan"]["source_sha256"]
    assert result["raw"]["current"] is True
    assert inventory(tmp_path) == before
    extra = Path(execution["effective_input"]) / "unregistered.csv"
    extra.write_bytes(b"outside declared mapped domain")
    before = inventory(tmp_path)
    result = inspect(store, request, spec)
    assert result["current"] is False and result["input"]["mapping_verified"] is False
    assert inventory(tmp_path) == before


def test_official_cold_mapping_query_is_unknown_without_numeric_replay_or_views(tmp_path, monkeypatch):
    store, request, task, spec, _execution = mapped_project(tmp_path / "original")
    live, live_request, _live_task, live_spec, _live_execution = mapped_project(tmp_path / "independent-live")
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    store.root.rename(tmp_path / "original-project-offline")
    task.rename(tmp_path / "original-task-offline")
    cold_spec = cold.root / spec.relative_to(store.root)
    assert not (cold.root / ".sciplot_store/sources").exists()
    before = inventory(tmp_path)
    no_views(monkeypatch)
    result = inspect(cold, request, cold_spec)
    assert result["current"] is None and result["input"]["current"] is None
    assert result["input"]["mapping_verified"] is None
    assert "selected sealed source bindings" in result["input"]["error"]
    assert result["prepared"]["current"] is True
    assert not (cold.root / ".sciplot_store/sources").exists()
    assert selected_source_resolver() is None and inventory(tmp_path) == before
    restored_live = inspect(live, live_request, live_spec)
    assert restored_live["current"] is True and restored_live["input"]["mapping_verified"] is True
    assert selected_source_resolver() is None and inventory(tmp_path) == before


def test_cold_external_execution_is_unknown_even_with_physical_raw_and_mapped_output(tmp_path, monkeypatch):
    from sciplot_core.project_store.runtime import inspect_runtime_source_file

    store, request, task, spec, execution = mapped_project(tmp_path / "original", physical_data=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    store.root.rename(tmp_path / "original-project-offline")
    task.rename(tmp_path / "original-task-offline")
    cold_spec = cold.root / spec.relative_to(store.root)
    before = inventory(tmp_path)
    no_views(monkeypatch)
    with project_runtime(cold):
        assert inspect_runtime_source_file(request["input"]).physical == cold.root / "raw.csv"
        output = execution["outputs"][0]
        assert inspect_runtime_source_file(output["path"], expected_sha256=output["sha256"]).physical is not None
        result = source_indicators(cold.root, request, [{"status": "ready", "spec": str(cold_spec)}])
    assert result["current"] is None and result["input"]["current"] is None
    assert result["input"]["mapping_verified"] is None
    assert result["prepared"]["current"] is True
    assert not (cold.root / ".sciplot_store/sources").exists()
    assert selected_source_resolver() is None and inventory(tmp_path) == before
