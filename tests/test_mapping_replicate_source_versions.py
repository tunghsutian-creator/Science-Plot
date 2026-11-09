"""Original confirmation replay retains its exact registered raw byte version."""
import json
from pathlib import Path

import pytest

from sciplot_core import task_control, task_execution
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from test_task_raw_replicate_mapping import original
from test_task_raw_replicate_source_update import bound as bound, expanded, mapped_plan


def test_registered_replicate_confirmation_replay_preserves_its_raw_byte_proof(tmp_path, monkeypatch):
    source, request, mapping = original(tmp_path)
    monkeypatch.setattr(task_execution, "create_project", lambda *_a, **_kw: {
        "project_dir": str(tmp_path / "not-native"), "studio_run": {"ready_to_use": True}})
    monkeypatch.setattr(task_control, "inspect_project", lambda *_a: {"source": {"current": True}})
    result = task_control.start_task({**request, "mapping": mapping}, task_dir=tmp_path / "task")
    assert result["status"] == "complete", result
    reference = result["data_mapping"]["data_mapping_execution"]
    with mapping_input_reads(reference) as reads:
        expected = load_data_mapping_execution(reference)
    project = tmp_path / "project"
    project.mkdir()
    (project / "plot_request.json").write_text(json.dumps({"input": str(source), "data_mapping_execution": reference}))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    command = ProjectCommand.create("figure_set", "raw-replicate-proof", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=reads.prepared_sources(before)))
    with project_runtime(store):
        assert load_data_mapping_execution(reference) == expected
    assert Path(reference).read_bytes() == reads.files[reference].data


def test_new_replicate_confirmation_is_admitted_during_same_project_expansion(bound, tmp_path, monkeypatch):
    from sciplot_core.data_mapping.plan_binding import verify_replicate_source_expansion

    source, project, mapping, previous = bound
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    target = tmp_path / "new-confirmation"
    target.mkdir()
    plan = mapped_plan(source, expanded(mapping), target, monkeypatch)
    selection = {**plan["data_mapping"], "rule_id": "impact_metric", "template": "box"}
    with project_runtime(store):
        verify_replicate_source_expansion(previous, source, selection, plan)
    assert store.snapshot()["generation"] == before["generation"]


@pytest.mark.parametrize("extended", [False, True], ids=["concrete", "extension"])
def test_resolved_sealed_mapping_input_admits_history_once_without_retaining_a_proof(tmp_path, monkeypatch, extended):
    from sciplot_core.data_mapping.execution_inputs import mapping_file_bytes
    from sciplot_core.foundation.source_locations import source_location_scope
    from sciplot_core.project_store.incoming_sources import SourceExpectation, source_expectation_scope
    from sciplot_core.project_store.io import owned_io
    from sciplot_core.project_store.source_resolver import ProjectSourceResolver
    from test_project_store_read_windows import store_with_files, external_source, count_reads, corrupt_object

    store, _snapshot = store_with_files(tmp_path)
    raw, source = external_source(store, tmp_path)
    class Extended(ProjectSourceResolver):
        pass
    resolver = (Extended if extended else ProjectSourceResolver)(store)
    expectation = SourceExpectation(str(raw), source.source_id, source.version)
    with source_expectation_scope(resolver.snapshot, "sealed", [expectation], store=store), source_location_scope(resolver):
        reads, _gets = count_reads(monkeypatch)
        assert mapping_file_bytes(raw, expected_sha256=source.version) == source.data
        assert reads["head.json"] == (2 if extended else 1)
        assert owned_io(store.root) is None
        corrupt_object(store, resolver.snapshot["files"]["B.bin"])
        with pytest.raises(ValueError, match="identity"):
            mapping_file_bytes(raw, expected_sha256=source.version)


def test_resolved_mapping_source_read_still_expires_an_active_history_proof(tmp_path):
    from sciplot_core.data_mapping.execution_inputs import mapping_file_bytes
    from sciplot_core.project_store import state
    from sciplot_core.project_store.incoming_sources import SourceExpectation
    from sciplot_core.project_store.io import owned_io
    from sciplot_core.project_store.runtime import sealed_source_runtime
    from test_project_store_read_windows import store_with_files, external_source

    store, _snapshot = store_with_files(tmp_path)
    raw, source = external_source(store, tmp_path)
    expectation = SourceExpectation(str(raw), source.source_id, source.version)
    with sealed_source_runtime(store, [expectation]), store._validation_window():
        io = owned_io(store.root)
        borrowed = state.checked_head(io)
        assert mapping_file_bytes(raw, expected_sha256=source.version) == source.data
        with pytest.raises(ValueError, match="boundary"):
            borrowed.require(io, borrowed.current)


@pytest.mark.parametrize("change", ["identity", "version", "name", "bytes"])
def test_resolved_mapping_view_keeps_exact_identity_and_fresh_bytes(tmp_path, monkeypatch, change):
    from sciplot_core.data_mapping.execution_inputs import mapping_file_bytes
    from sciplot_core.project_store.incoming_sources import SourceExpectation
    from sciplot_core.project_store.runtime import sealed_source_runtime
    from sciplot_core.project_store.source_resolver import ProjectSourceResolver
    from test_project_store_read_windows import store_with_files, external_source

    store, _snapshot = store_with_files(tmp_path)
    raw, source = external_source(store, tmp_path)
    expectation = SourceExpectation(str(raw), source.source_id, source.version)
    original = ProjectSourceResolver.resolve_path
    def changed(resolver, *args, **kwargs):
        actual = original(resolver, *args, **kwargs)
        if change == "bytes":
            actual.unlink()
            actual.write_bytes(b"different content")
            return actual
        identity = "b" * 32 if change == "identity" else source.source_id
        version = "0" * 64 if change == "version" else source.version
        name = "foreign.csv" if change == "name" else raw.name
        foreign = store.root / ".sciplot_store/sources" / identity / version / name
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_bytes(source.data)
        return foreign
    monkeypatch.setattr(ProjectSourceResolver, "resolve_path", changed)
    with sealed_source_runtime(store, [expectation]), pytest.raises(ValueError, match="hash changed|identity/version"):
        mapping_file_bytes(raw, expected_sha256=source.version)


@pytest.mark.parametrize("selection", ["current", "committed-old", "orphan", "current-source-removed"])
def test_resolved_mapping_view_requires_a_committed_selected_generation(tmp_path, selection):
    from contextlib import nullcontext
    from copy import deepcopy
    from uuid import uuid4
    from sciplot_core.data_mapping.execution_inputs import mapping_file_bytes
    from sciplot_core.project_store import state
    from sciplot_core.project_store.incoming_sources import SourceExpectation
    from sciplot_core.project_store.io import StoreIO, digest
    from sciplot_core.project_store.runtime import sealed_source_runtime
    from test_project_store_read_windows import store_with_files, external_source, publish

    store, _snapshot = store_with_files(tmp_path)
    raw, source = external_source(store, tmp_path)
    old = store.snapshot()
    publish(store, {"A.bin": b"a later generation"})
    current = store.snapshot()
    generation = old["generation"] if selection in {"committed-old", "current-source-removed"} else None
    if selection == "orphan":
        orphan = deepcopy(current)
        generation = orphan["generation"] = uuid4().hex
        with StoreIO(store.root, {}).locked() as io:
            state.write_generation(io, orphan)  # Complete file, never published by head.
    elif selection == "current-source-removed":
        with StoreIO(store.root, {}).locked() as io:
            base = state.head(io)
            successor = {**deepcopy(base), "generation": uuid4().hex, "parent": base["generation"],
                         "parent_sha256": digest(base), "sequence": base["sequence"] + 1, "sources": {}}
            state.write_generation(io, successor)
            state.publish_head(io, successor, expected=base)
        current = successor
    expectation = SourceExpectation(str(raw), source.source_id, source.version)
    with sealed_source_runtime(store, [expectation], generation=generation):
        refusal = ("not committed project history" if selection == "orphan" else
                   "not in this project" if selection == "current-source-removed" else None)
        with pytest.raises(ValueError, match=refusal) if refusal is not None else nullcontext():
            assert mapping_file_bytes(raw, expected_sha256=source.version) == source.data
    assert store.snapshot()["generation"] == current["generation"]
