"""Readonly exact metadata facts do not create imported source views."""
import hashlib
import json

import pytest

from sciplot_core.data_mapping.execution_inputs import mapping_execution_is_sealed
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.runtime import project_runtime


def fixture(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    metadata = tmp_path / "task/execution.json"
    metadata.parent.mkdir()
    metadata.write_bytes(b'{"kind":"immutable observation only"}\n')
    (root / "plot_request.json").write_text(json.dumps({"data_mapping_execution": str(metadata)}))
    store = FileProjectStore(root)
    snapshot = store.snapshot(import_legacy=True)
    data = metadata.read_bytes()
    source = PreparedSource("a" * 32, str(metadata), hashlib.sha256(data).hexdigest(), data, mode=0o644)
    command = ProjectCommand.create("figure_set", "metadata-observation", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={}, write_set=[], request={"metadata": str(metadata)})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=(source,)))
    return root, metadata, store


def test_exact_metadata_observation_is_sealed_only_for_its_imported_identity_without_writes(tmp_path):
    root, metadata, store = fixture(tmp_path)
    with project_runtime(store):
        assert mapping_execution_is_sealed(metadata) is False
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    metadata.parent.rename(tmp_path / "task-offline")
    root.rename(tmp_path / "project-offline")
    before = {str(path.relative_to(cold.root)): (path.read_bytes(), path.stat().st_mode)
              for path in cold.root.rglob("*") if path.is_file()}
    with project_runtime(cold):
        assert mapping_execution_is_sealed(metadata) is True
        assert mapping_execution_is_sealed(tmp_path / "foreign/execution.json") is False
    assert {str(path.relative_to(cold.root)): (path.read_bytes(), path.stat().st_mode)
            for path in cold.root.rglob("*") if path.is_file()} == before
    assert not (cold.root / ".sciplot_store/sources").exists()


def test_metadata_observation_never_selects_one_of_multiple_versions(tmp_path):
    _root, metadata, store = fixture(tmp_path)
    metadata.write_bytes(metadata.read_bytes() + b" ")
    data = metadata.read_bytes()
    snapshot = store.snapshot()
    source = PreparedSource("a" * 32, str(metadata), hashlib.sha256(data).hexdigest(), data, mode=0o644)
    command = ProjectCommand.create("figure_set", "another-version", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={}, write_set=[], request={"metadata": str(metadata)})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=(source,)))
    with project_runtime(store), pytest.raises(ProjectConflict, match="one exact"):
        mapping_execution_is_sealed(metadata)
