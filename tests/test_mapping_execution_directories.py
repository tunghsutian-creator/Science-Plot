"""Finite data_dir receipts bind all mapped files, never a guessed parent."""
import json
from pathlib import Path

import pytest

from sciplot_core.data_mapping import create_data_mapping_confirmation, execute_data_mapping_proposal
from sciplot_core.data_mapping.request_resolution import resolve_data_mapping_request
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.data_mapping.execution_directories import mapping_execution_trees
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime, sealed_source_runtime
from sciplot_core.project_store.incoming_sources import SourceExpectation


def directory_execution(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    source = origin / "raw"
    source.mkdir()
    for name, value in (("one", "3"), ("two", "7")):
        (source / f"{name}.csv").write_text(f"Wavelength (nm),Absorbance (a.u.)\n400,{value}\n500,1\n")
    request_path = origin / "base.json"
    request_path.write_text(json.dumps({"input": str(source), "rule_id": "uvvis_spectrum", "template": "curve"}))
    proposal = DataMappingProposal(proposal_id="two_tables", provider="external_task",
        base_request_sha256=file_sha256(request_path),
        sources=tuple(DataSourceReference(name, f"{name}.csv", file_sha256(source / f"{name}.csv")) for name in ("one", "two")),
        columns=tuple(column for name in ("one", "two") for column in (
            DataColumnMapping(name, 0, "Wavelength (nm)", "x", expected_header="Wavelength (nm)"),
            DataColumnMapping(name, 1, "Absorbance (a.u.)", "y", expected_header="Absorbance (a.u.)"))),
        sample_labels={"one": "one", "two": "two"}, request_patch={"rule_id": "uvvis_spectrum", "template": "curve"})
    receipt = create_data_mapping_confirmation(proposal, source_root=source, request_path=request_path,
        output_root=origin / "executions", confirmed_by="finite directory test")
    execution = execute_data_mapping_proposal(proposal, receipt, source_root=source,
        request_path=request_path, output_root=origin / "executions")
    request = json.loads(Path(execution["request_seed"]).read_bytes())
    return origin, request, execution


def test_existing_directory_mapping_request_keeps_complete_effective_input(tmp_path):
    _origin, request, execution = directory_execution(tmp_path)
    assert execution["effective_input"] == execution["data_dir"]
    effective, application = resolve_data_mapping_request(request, base_dir=tmp_path)
    assert effective["input"] == execution["data_dir"]
    assert [record["rows"] for record in application["mapped_outputs"]] == [2, 2]
    assert [record["path"] for record in application["mapped_outputs"]] == [record["path"] for record in execution["outputs"]]
    assert application["source_hashes"] == execution["source_hashes"]


def registered_directory(tmp_path):
    origin, request, execution = directory_execution(tmp_path)
    reference = str(Path(execution["output_root"]) / "execution.json")
    with mapping_input_reads(reference) as reads:
        load_data_mapping_execution(reference)
    root = tmp_path / "project"
    root.mkdir()
    (root / "plot_request.json").write_text(json.dumps(request))
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    mutation = ProjectMutation({}, {}, prepared_sources=reads.prepared_sources(before))
    command = ProjectCommand.create("figure_set", "certify-complete-mapping", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={"execution": reference},
        source_trees=tuple(reads.trees.values()))
    ProjectCommands(store).execute(command, lambda: mutation)
    return origin, root, store, request, execution, mutation.prepared_sources


def test_cold_directory_replay_uses_exact_committed_tree_author_and_original_literals(tmp_path):
    origin, root, store, request, execution, sources = registered_directory(tmp_path)
    before = store.snapshot()
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    origin.rename(tmp_path / "origin-offline")
    root.rename(tmp_path / "project-offline")
    with project_runtime(cold):
        trees = mapping_execution_trees(request["data_mapping_execution"])
        assert len(trees) == 1 and trees[0].command_id == "certify-complete-mapping"
    expectations = [SourceExpectation(item.locator, item.source_id, item.version) for item in sources]
    with sealed_source_runtime(cold, expectations, trees=trees):
        effective, application = resolve_data_mapping_request(request, base_dir=cold.root)
        assert load_data_mapping_execution(request["data_mapping_execution"]) == execution
    assert effective["input"] == execution["data_dir"]
    assert [item["path"] for item in application["mapped_outputs"]] == [item["path"] for item in execution["outputs"]]
    assert application["source_hashes"] == execution["source_hashes"]
    assert cold.snapshot()["sources"] == before["sources"]
    assert not Path(execution["data_dir"]).exists()


@pytest.mark.parametrize("change", ["extra", "missing", "alias"])
def test_complete_directory_witness_rejects_membership_changes_before_head(tmp_path, monkeypatch, change):
    from sciplot_core.project_store import state

    _origin, root, store, request, execution, sources = registered_directory(tmp_path)
    before = store.snapshot()
    with project_runtime(store), mapping_input_reads(request["data_mapping_execution"]) as reads:
        load_data_mapping_execution(reads.execution)
    command = ProjectCommand.create("figure_set", "directory-change", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"ready.txt": None}, write_set=["ready.txt"],
        request={"change": change}, source_trees=tuple(reads.trees.values()))
    original = state.boundary

    def mutate(name):
        if name == "before_head":
            directory = Path(execution["data_dir"])
            target = Path(execution["outputs"][0]["path"])
            if change == "extra":
                (directory / "undeclared.csv").write_bytes(b"extra")
            elif change == "missing":
                target.unlink()
            else:
                target.unlink()
                target.symlink_to(Path(execution["outputs"][1]["path"]))
        original(name)

    monkeypatch.setattr(state, "boundary", mutate)
    with pytest.raises((ValueError, OSError)):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"ready.txt": b"ready"}, {}, prepared_sources=sources))
    assert store.snapshot()["generation"] == before["generation"] and not (root / "ready.txt").exists()
