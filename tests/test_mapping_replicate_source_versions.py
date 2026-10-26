"""Original confirmation replay retains its exact registered raw byte version."""
import json
from pathlib import Path

from sciplot_core import task_control, task_execution
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from test_task_raw_replicate_mapping import original


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
