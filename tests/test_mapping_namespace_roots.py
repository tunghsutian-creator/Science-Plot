"""Frozen mapping root metadata never grants an ambient parent directory."""

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.contracts import load_data_mapping_proposal, verify_data_mapping_sources
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectStoreError, ResourceRoot
from sciplot_core.project_store.incoming_sources import SourceExpectation
from sciplot_core.project_store.runtime import incoming_source_runtime, inspect_runtime_source_tree

from test_project_query_readonly_sources import inventory
from test_task_raw_replicate_source_update import bound as bound, expanded, mapped_plan


def fresh_mapping(bound, tmp_path, monkeypatch, *, snapshot_present=False):
    source, project, mapping, previous = bound
    plan = mapped_plan(source, expanded(mapping), tmp_path, monkeypatch)
    reference = plan["data_mapping"]["data_mapping_execution"]
    payload = json.loads(Path(reference).read_bytes())
    # The public host declares its possible ZIP output. An existing ZIP admits
    # that exact member; neither state admits the parent's other bytes.
    assert not (tmp_path / "project.zip").exists()
    if snapshot_present:
        with ZipFile(tmp_path / "project.zip", "w") as archive:
            archive.writestr("binding.txt", "Synthetic snapshot capability; never executed.")
    store = FileProjectStore(project, locations={"snapshot": ResourceRoot(tmp_path, ("project.zip",))})
    before = store.snapshot(import_legacy=True)
    identity = "a" * 32
    source_version = file_sha256(source)
    mutation = ProjectMutation({}, {}, prepared_sources=(PreparedSource(
        identity, str(source), source_version, source.read_bytes(), mode=source.stat().st_mode & 0o777),))
    command = ProjectCommand.create("attachment_import", "existing-raw-identity", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[],
        request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)
    assert payload["source_root"] == str(tmp_path)
    assert payload["source_root"] not in {entry["locator"] for versions in store.snapshot()["sources"].values()
                                         for entry in versions.values()}
    assert not any(entry["locator"] == reference for versions in store.snapshot()["sources"].values()
                   for entry in versions.values())
    return store, source, reference, payload, previous, SourceExpectation(str(source), identity, source_version)


@pytest.mark.parametrize("role", ["execution", "source-verification"])
@pytest.mark.parametrize("snapshot_present", [False, True])
def test_fresh_mapping_uses_literal_parent_namespace_without_parent_read_cap(bound, tmp_path, monkeypatch, role, snapshot_present):
    store, source, reference, payload, previous, expectation = fresh_mapping(bound, tmp_path, monkeypatch, snapshot_present=snapshot_present)
    old = load_data_mapping_execution(previous["data_mapping_execution"])
    snapshot, before = store.snapshot(), inventory(tmp_path)
    with incoming_source_runtime(store, [expectation]), mapping_input_reads(reference, expected_source=source):
        with pytest.raises(ProjectStoreError):
            inspect_runtime_source_tree(tmp_path)
        if role == "execution":
            result = load_data_mapping_execution(reference, expected_source=source)
            assert result["source_root"] == payload["source_root"]
            assert [item["rows"] for item in result["outputs"]] == [7, 7, 5]
            assert [item["sha256"] for item in result["outputs"][:2]] == [item["sha256"] for item in old["outputs"]]
        else:
            proposal = load_data_mapping_proposal(payload["proposal"])
            paths = verify_data_mapping_sources(proposal, source_root=payload["source_root"])
            assert set(paths.values()) == {source}
        with pytest.raises(ProjectStoreError):
            inspect_runtime_source_tree(tmp_path)
    assert inventory(tmp_path) == before and store.snapshot() == snapshot
    assert selected_source_resolver() is None


@pytest.mark.parametrize("failure", ["alias-root", "wrong-source", "raw-byte-change"])
def test_literal_namespace_never_bypasses_alias_exact_source_or_raw_version(bound, tmp_path, monkeypatch, failure):
    store, source, reference, payload, _previous, expectation = fresh_mapping(bound, tmp_path, monkeypatch)
    expected_source = source
    if failure == "alias-root":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
    elif failure == "wrong-source":
        expected_source = tmp_path / "foreign.csv"
        expected_source.write_bytes(source.read_bytes())
    else:
        source.write_bytes(source.read_bytes() + b"unconfirmed source version\n")
    snapshot, before = store.snapshot(), inventory(store.root)
    with incoming_source_runtime(store, [expectation]):
        with pytest.raises((ProjectStoreError, ValueError)):
            with mapping_input_reads(reference, expected_source=expected_source):
                if failure == "alias-root":
                    proposal = load_data_mapping_proposal(payload["proposal"])
                    verify_data_mapping_sources(proposal, source_root=alias)
                else:
                    load_data_mapping_execution(reference, expected_source=expected_source)
    assert inventory(store.root) == before and store.snapshot() == snapshot
    assert selected_source_resolver() is None
