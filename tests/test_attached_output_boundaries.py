"""A native output cannot become a second writer of canonical attachment state."""
from pathlib import Path

import pytest

from managed_plot_helpers import request_for_source
from test_attached_semantic_repository import application
from sciplot_core.project_lifecycle import managed_creation
from sciplot_core.project_lifecycle.attachment_index import INDEX, attachment_id
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


@pytest.mark.parametrize("location", ["namespace", "namespace_child", "store", "resources", "project", "alias"])
def test_reserved_output_is_rejected_before_scientific_admission_or_allocation(tmp_path, monkeypatch, location):
    project = tmp_path / "project"
    project.mkdir()
    wire = request_for_source(project)
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    identity = attachment_id(before["project_id"], "managed:" + wire["idempotency_key"])
    namespace = project / ".sciplot_semantic" / identity
    alias = project / "alias"
    alias.symlink_to(project / ".sciplot_semantic", target_is_directory=True)
    output = {"namespace": namespace, "namespace_child": namespace / "rendered", "store": project / ".sciplot_store/new",
              "resources": project / ".sciplot_resources/new", "project": project, "alias": alias / identity}[location]
    wire["out"] = str(output)
    monkeypatch.setattr(managed_creation, "admit_document_executors", lambda *_: pytest.fail("Output conflict reached science admission"))
    with project_runtime(store), pytest.raises(EngineError) as error:
        application().create(wire)
    assert error.value.reason_code == "managed_output_conflict"
    after = store.snapshot()
    assert after["generation"] == before["generation"] and INDEX not in after["files"]
    assert store.commands() == () and not namespace.exists()


def test_explicit_project_publication_output_remains_separate_from_its_semantic_owner(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    wire = request_for_source(project)
    wire["out"] = str(project / "publication")
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    with project_runtime(store):
        result = application().create(wire)
    assert result["ready_to_use"]
    assert Path(result["plot"]).parent == project / ".sciplot_semantic"
    assert all(Path(item["path"]).is_relative_to(project / "publication") for item in result["exports"])
    assert (Path(result["plot"]) / "head.json").is_file()
    assert not (project / "publication/head.json").exists()
