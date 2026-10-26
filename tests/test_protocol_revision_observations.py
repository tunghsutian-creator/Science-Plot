"""Protocol history observations use the selected generation, never empty views."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from managed_plot_helpers import patch, request_for_source
from test_attached_semantic_repository import application
from test_plot_protocol_native import _revision_snapshot

from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


def test_protocol_revision_observation_reads_attached_history_without_physical_globs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    wire = request_for_source(project)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(wire)
    root = Path(created["plot"])
    edited = app.patch(root, patch(created, "style", "style.line.width", "1.2pt", "series:A"))
    assert edited["revision"] == 1
    glob = Path.glob

    def no_revision_views(path, pattern):
        return iter(()) if path == root / "revisions" else glob(path, pattern)

    monkeypatch.setattr(Path, "glob", no_revision_views)
    snapshot = _revision_snapshot(root, created["scientific_hash"], repository=app.repository)
    assert len(snapshot) == 2 and all(snapshot.values())
    assert _revision_snapshot(root, created["scientific_hash"], repository=app.repository) == snapshot


@pytest.mark.parametrize("members", [[], ["00000000.json"]])
def test_protocol_revision_observation_refuses_empty_or_partial_history(members):
    root = Path("/generated/plot")
    repository = SimpleNamespace(invocation_scope=nullcontext,
        json_members=lambda *_: [root / "revisions" / name for name in members],
        load_revision=lambda *_: pytest.fail("Incomplete history reached revision reads"))
    with pytest.raises(AssertionError):
        _revision_snapshot(root, "generated scientific hash", repository=repository)
