"""Only admitted exact scientific source declarations can enter an attachment."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_figure_document import request_for_figure
from test_managed_source_append import append_request
from test_attached_semantic_repository import application
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
