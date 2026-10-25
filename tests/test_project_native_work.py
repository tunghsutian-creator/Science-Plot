"""Unknown native work retains bounded same-command evidence without replay."""

from pathlib import Path

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands
from sciplot_core.project_store import FileProjectStore, ProjectRecoveryRequired
from test_project_store import fixture_store


def unknown_creation(store, snapshot):
    command = ProjectCommand.create("native_create", "native create with spaces", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={}, write_set=[], request={})

    def prepare():
        workspace = store.claim_native_workspace(command.key, command.command_digest, "native_suite_create_v1")
        (workspace / "native-receipt.json").write_bytes(b"fixed native evidence")
        store.append_native_failure(command.key, command.command_digest, original_error="renderer returned failure",
            renderer_dispatch_entered=True, owned_invocation_closed=True)
        raise RuntimeError("renderer returned failure")

    with pytest.raises(RuntimeError, match="renderer returned failure"):
        ProjectCommands(store).execute(command, prepare)
    return command


def test_unknown_native_workspace_and_failure_fact_survive_cold_bundle_without_replay(tmp_path):
    store, snapshot = fixture_store(tmp_path)
    command = unknown_creation(store, snapshot)
    before = store.query(command.key)
    assert before["phase"] == "unknown"
    assert before["native_failures"] == [{"original_error": "renderer returned failure",
        "renderer_dispatch_entered": True, "owned_invocation_closed": True}]
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    after = cold.query(command.key)
    assert after["phase"] == "unknown"
    assert after["native_failures"] == before["native_failures"]
    workspace = cold.claim_native_workspace(command.key, command.command_digest, "native_suite_create_v1")
    assert (workspace / "native-receipt.json").read_bytes() == b"fixed native evidence"
    original_workspace = Path(before["native_workspace_path"])
    assert cold.literal_path(workspace) == str(original_workspace)
    assert cold.resolve_path(original_workspace / "native-receipt.json") == workspace / "native-receipt.json"
    assert cold.snapshot()["generation"] == snapshot["generation"]


def test_native_working_root_replacement_is_refused_without_promoting_unknown(tmp_path):
    store, snapshot = fixture_store(tmp_path)
    command = unknown_creation(store, snapshot)
    workspace = Path(store.query(command.key)["native_workspace_path"])
    workspace.rename(workspace.with_name("owned-original"))
    workspace.mkdir()
    with pytest.raises(ProjectRecoveryRequired, match="identity"):
        store.claim_native_workspace(command.key, command.command_digest, "native_suite_create_v1")
    assert store.snapshot()["generation"] == snapshot["generation"]


def test_only_exact_command_owned_work_paths_reenter_scoped_read_ports(tmp_path):
    from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path
    from sciplot_core.project_store.io import sha
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.project_store import ProjectConflict

    store, snapshot = fixture_store(tmp_path)
    command = unknown_creation(store, snapshot)
    workspace = Path(store.query(command.key)["native_workspace_path"])
    evidence = workspace / "native-receipt.json"
    with project_runtime(store):
        assert resolve_source_path(evidence, expected_sha256=sha(evidence.read_bytes())) == evidence
        assert literal_source_path(evidence) == str(evidence)
        assert resolve_source_path(workspace) == workspace
        with pytest.raises(ProjectConflict):
            resolve_source_path(evidence, expected_sha256="0" * 64)
        with pytest.raises(ProjectConflict):
            resolve_source_path(evidence, source_id="unrelated-scientific-source", expected_sha256=sha(evidence.read_bytes()))
        outside = tmp_path / "outside.json"
        outside.write_bytes(evidence.read_bytes())
        alias = workspace / "alias.json"
        alias.symlink_to(outside)
        with pytest.raises(ProjectConflict):
            resolve_source_path(alias)
    assert store.query(command.key)["phase"] == "unknown"
