"""Runtime paths and invocation capabilities cannot rewrite scientific evidence."""
from copy import deepcopy
import json

import pytest

from managed_plot_helpers import request_for_source
from test_attached_semantic_repository import application
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_lifecycle.attachment_import import entry_for
from sciplot_core.project_lifecycle.attachment_index import Attachment, INDEX, OWNER, encode
from sciplot_core.project_lifecycle.attachment_projection import metadata_view
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


def test_only_metadata_paths_move_and_invocation_capabilities_never_enter_history(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    old = tmp_path / "original-namespace"
    entry = entry_for(store, key="legacy:test", figure_id="test", origin=old, plot_id="test")
    attachment = Attachment(store, entry)
    literal = str(old / "literal scientific sample")
    value = {"document": {"kind": "sciplot_document", "scientific": {"sample": literal}},
             "request": {"changes": [{"value": literal}]}, "diff": [{"before": literal, "after": literal}],
             "binding": {"root": str(old), "targets": {"sample": {"label": literal}},
                         "scientific_content_files": {str(old / "content/x.json"): "a" * 64}},
             "error": {"diagnostic": str(old / "transactions/id/diagnostic.json")}}
    original = deepcopy(value)
    moved = metadata_view(value, attachment)
    assert value == original and moved["document"] == original["document"]
    assert moved["request"] == original["request"] and moved["diff"] == original["diff"]
    assert moved["binding"]["targets"] == original["binding"]["targets"]
    assert moved["binding"]["_semantic_attachment_id"] == entry["id"]
    assert moved["binding"]["root"] == str(attachment.root)
    assert str(attachment.root / "content/x.json") in moved["binding"]["scientific_content_files"]
    assert metadata_view(moved, attachment, storing=True) == original


def test_same_project_legacy_bindings_select_exact_attachment_and_ambiguous_binding_refuses(tmp_path):
    store = FileProjectStore(tmp_path)
    store.snapshot(import_legacy=True)
    repository = ComposedProjectRepository()
    entries = [entry_for(store, key="legacy:" + name, figure_id=name, origin=tmp_path / name, plot_id=name)
               for name in ("A", "B")]
    with repository_scope(repository, capabilities=COMPATIBILITY_CAPABILITIES):
        owners = [repository.select(Attachment(store, entry)) for entry in entries]
        for owner in owners:
            binding = {"project": str(tmp_path), "_semantic_attachment_id": owner.attachment.entry["id"]}
            with repository.binding_scope(binding):
                assert selected_source_resolver() is owner._source.get()
                assert owner._source.get() is not None
        with pytest.raises(EngineError, match="exact selected"):
            with repository.binding_scope({"project": str(tmp_path)}):
                pytest.fail("Ambiguous legacy scope escaped")
    assert selected_source_resolver() is None


def test_forged_old_namespace_pointer_cannot_route_or_repair_some_other_attachment(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    request = request_for_source(project)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        app.create(request)
    snapshot = store.snapshot()
    entry = next(iter(json.loads(store.read_bytes(INDEX))["attachments"].values()))
    forged = tmp_path / "unrelated-old-root"
    forged.mkdir()
    (forged / OWNER).write_bytes(encode({"kind": "sciplot_semantic_owner", "version": 1,
        "origin_root": str(forged), "project": str(project), "project_id": snapshot["project_id"],
        "attachment_id": entry["id"], "figure_id": entry["figure_id"]}))
    monkeypatch.setattr(FileProjectStore, "recover", lambda *_: pytest.fail("Forged pointer triggered storage repair"))
    with project_runtime(store), pytest.raises(EngineError) as error:
        app.open(forged)
    assert error.value.reason_code == "semantic_attachment_owner_conflict"
    assert store.snapshot()["generation"] == snapshot["generation"]
