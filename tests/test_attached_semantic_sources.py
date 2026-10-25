"""Only admitted exact scientific source declarations can enter an attachment."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_figure_document import request_for_figure
from test_managed_source_append import append_request
from test_attached_semantic_repository import application
from managed_plot_helpers import patch, request_for_source
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import DocumentError
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


def create_figure(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    wire = request_for_figure(project)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(wire)
    root = Path(created["plot"])
    with repository_scope(app.repository, capabilities=COMPATIBILITY_CAPABILITIES):
        document = app.repository.load_head(root)["document"]
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    return store, app, root, document, append_request(document, incoming)


def test_admitted_append_freezes_exact_source_with_first_journal_and_cold_exports(tmp_path):
    store, app, root, document, request = create_figure(tmp_path)
    original_science = document["scientific_hash"]
    planned = app.patch(root, request)
    assert planned["status"] == "needs_review"
    source = request["changes"][0]["value"]["source"]
    source_bytes = Path(source["path"]).read_bytes()
    saved = [entry for versions in store.snapshot()["sources"].values() for sha, entry in versions.items()
             if sha == source["sha256"] and entry["locator"] == source["path"]]
    assert len(saved) == 1 and source["source_id"] in saved[0]["aliases"]
    complete = app.decide(root, planned["next_step"]["request"])
    assert complete["revision"] == 1 and complete["scientific_hash"] != original_science
    assert Path(source["path"]).read_bytes() == source_bytes
    bundle = store.export_bundle(tmp_path / "bundle")
    store.root.rename(tmp_path / "old-project")
    Path(source["path"]).parent.rename(tmp_path / "old-incoming")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    coldapp = application()
    with project_runtime(moved):
        cold = coldapp.open(moved.root, figure_id=complete["plot_id"])
        exported = coldapp.export(Path(cold["plot"]))
    assert exported["scientific_hash"] == complete["scientific_hash"] and exported["plot_id"] == complete["plot_id"]


@pytest.mark.parametrize("invalid", ["intent", "revision", "sha"])
def test_source_scope_cannot_admit_wrong_intent_revision_or_bytes(tmp_path, monkeypatch, invalid):
    store, app, root, _document, request = create_figure(tmp_path)
    request = deepcopy(request)
    before = deepcopy(store.snapshot()["sources"])
    if invalid == "intent":
        request["intent_class"] = "presentation"
    elif invalid == "revision":
        request["base_revision"] += 1
    else:
        request["changes"][0]["value"]["source"]["sha256"] = "0" * 64
    if invalid != "sha":
        from sciplot_core.project_lifecycle import attachment_admission

        monkeypatch.setattr(attachment_admission, "capture_source", lambda *_: pytest.fail("Unadmitted source read"))
    with pytest.raises((EngineError, DocumentError)):
        app.patch(root, request)
    assert store.snapshot()["sources"] == before


def test_tracked_source_refresh_observes_raw_once_and_cold_history_uses_its_recorded_generation(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    request = request_for_source(project)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(request)
    root = Path(created["plot"])
    before = store.snapshot()
    revision0 = next(name for name in before["files"] if name.endswith("/revisions/00000000.json"))
    old_revision = store.read_bytes(revision0)
    old_source = source.read_bytes()
    source.write_text("Time,Signal\ns,V\n0,3\n1,6\n2,12\n")
    new_source = source.read_bytes()
    observed = source.stat()
    change = patch(created, "refresh", "source.sha256", file_sha256(source), "source:A", scientific=True)
    original_write = Path.write_bytes

    def no_raw_write(path, data):
        assert path != source, "Scientific refresh rewrote the original input"
        return original_write(path, data)

    monkeypatch.setattr(Path, "write_bytes", no_raw_write)
    refreshed = app.patch(root, change)
    assert refreshed["scientific_hash"] != created["scientific_hash"] and refreshed["revision"] == 1
    after = store.snapshot()
    assert after["projection_status"] == "current" and after["files"]["A.csv"]["sha256"] == file_sha256(source)
    assert source.read_bytes() == new_source and (source.stat().st_ino, source.stat().st_mtime_ns) == (observed.st_ino, observed.st_mtime_ns)
    assert store.read_bytes(revision0) == old_revision
    records = [item for item in store.commands() if item["metadata"].get("source_adoptions")]
    assert len(records) == 1 and "A.csv" not in records[0]["write_set"]
    bundle = store.export_bundle(tmp_path / "bundle")
    project.rename(tmp_path / "offline")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "cold")
    coldapp = application()
    with project_runtime(moved):
        current = coldapp.open(moved.root, figure_id=created["plot_id"])
        current_root = Path(current["plot"])
        assert coldapp.export(current_root)["scientific_hash"] == refreshed["scientific_hash"]
        # Clear scientific results through their real storage owner, then
        # reconstruct both revisions from their exact immutable source versions.
        from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation

        snapshot = moved.snapshot()
        removed = {name: None for name in snapshot["files"] if "/transform-cache/" in name}
        assert removed
        deletion = ProjectMutation(removed, {})
        command = ProjectCommand.create("semantic_record", "clear-scientific-cache", project_id=snapshot["project_id"],
            expected_generation=snapshot["generation"], read_set={name: snapshot["files"][name]["sha256"] for name in removed},
            write_set=sorted(removed), request={"prepared_digest": deletion.prepared_digest})
        ProjectCommands(moved).publish_prepared(command, deletion)
        with repository_scope(coldapp.repository, capabilities=COMPATIBILITY_CAPABILITIES):
            past = coldapp.repository.load_revision(current_root, 0)
            present = coldapp.repository.load_head(current_root)
            from sciplot_core.foundation.source_locations import resolve_source_path

            for envelope, expected in ((past, old_source), (present, new_source)):
                with coldapp.repository.binding_scope(envelope["binding"]):
                    bound = envelope["document"]["scientific"]["data_sources"][0]
                    actual = resolve_source_path(bound["path"], expected_sha256=bound["sha256"], source_id=bound["source_id"])
                    assert actual.read_bytes() == expected
                    from sciplot_core.plot_engine.managed_resolution import resolve_science

                    rebuilt, evidence = resolve_science(current_root, envelope["document"])
                    assert rebuilt["scientific_hash"] == envelope["document"]["scientific_hash"] and evidence["executed"]
            assert "_semantic_project_generation" in past["binding"] and "_semantic_project_generation" not in present["binding"]
    assert moved.read_bytes(revision0) == old_revision
