"""Ownership transfer has one atomic old-writer refusal and explicit acceptance."""
import json
from pathlib import Path

import pytest

from test_attached_semantic_history import bytes_in, old_managed
from test_attached_semantic_history import standalone
from managed_plot_helpers import request_for_source
from test_attached_semantic_repository import application
from sciplot_core.project_lifecycle import attachment_transfer
from sciplot_core.project_lifecycle.attachment_index import OWNER
from sciplot_core.project_store import state
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


class TransferCrash(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["before_fence", "after_fence", "after_publication", "before_head", "after_head", "before_projection"])
def test_frozen_transfer_restarts_without_recapturing_or_executing_science(tmp_path, monkeypatch, boundary):
    _restart(tmp_path, monkeypatch, boundary, tracked=False)


@pytest.mark.parametrize("boundary", ["before_fence", "after_fence", "after_publication", "before_head", "after_head", "before_projection"])
def test_tracked_transfer_restarts_with_its_exact_original_backup_capability(tmp_path, monkeypatch, boundary):
    _restart(tmp_path, monkeypatch, boundary, tracked=True)


def _restart(tmp_path, monkeypatch, boundary, *, tracked):
    project = tmp_path / "project"
    if tracked:
        project.mkdir()
        created = standalone().create(request_for_source(project))
        old = Path(created["plot"])
    else:
        _sources, old, created = old_managed(tmp_path)
    original = bytes_in(old)
    project.mkdir(exist_ok=True)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)

    def crash(name):
        if name == boundary:
            raise TransferCrash(name)

    with monkeypatch.context() as injected:
        injected.setattr(attachment_transfer, "transfer_boundary", crash)
        injected.setattr(state, "boundary", crash)
        with project_runtime(store), pytest.raises(TransferCrash):
            application().open(old)
    records = [item for item in store.commands() if item["metadata"]["kind"] == "attachment_import"]
    assert len(records) == 1 and records[0]["phase"] in {"needs_review", "accepted", "complete"}
    assert bool(records[0]["metadata"].get("namespace_transfers")) == tracked
    if boundary == "before_fence":
        assert bytes_in(old) == original
        assert records[0]["phase"] == "needs_review"
    else:
        assert set(bytes_in(old)) == {OWNER, "head.json"}
        assert "revision" not in json.loads((old / "head.json").read_bytes())
    # Once staged, even removing every original raw source cannot retarget the
    # transfer. The candidate and backup, rather than a new source parse, own it.
    from sciplot_core.project_lifecycle import attachment_sources
    def injected_read(*_):
        pytest.fail("Frozen transfer recaptured original sources")
    monkeypatch.setattr(attachment_sources, "_read_source", injected_read)
    app = application()
    with project_runtime(store) if boundary != "after_head" and boundary != "before_projection" else __import__("contextlib").nullcontext():
        result = app.open(old)
    assert result["plot_id"] == created["plot_id"]
    owner = json.loads((old / OWNER).read_bytes())
    backup = Path(owner["history_root"])
    assert {key: data for key, data in bytes_in(backup).items() if key != OWNER} == original
    assert store.snapshot()["projection_status"] == "current"
    assert len([item for item in store.commands() if item["metadata"]["kind"] == "attachment_import"]) == 1
