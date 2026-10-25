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
