"""Lower table readers reuse only an exact verified source in one invocation."""
from pathlib import Path

import pytest
from managed_plot_helpers import request_for_source
from test_attached_semantic_repository import application
from sciplot_core.project_lifecycle.attachment_sources import AttachmentSourceResolver
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


def test_new_external_source_reentrant_reads_remain_exact_after_first_journal_and_retry(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    inputs = tmp_path / "original-external"
    inputs.mkdir()
    request = request_for_source(inputs)
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        created = app.create(request)
        replayed = app.create(request)
    assert created["plot_id"] == replayed["plot_id"] and replayed["scientific_hash"] == created["scientific_hash"]
    source = request["data_binding"]["data_sources"][0]
    resolver = AttachmentSourceResolver(store)
    actual = resolver.resolve_path(source["path"], expected_sha256=source["sha256"], source_id=source["source_id"])
    resolver.refresh()
    assert resolver.resolve_path(actual).read_bytes() == Path(source["path"]).read_bytes()
    refused = AttachmentSourceResolver(store)
    with pytest.raises(ValueError):
        refused.resolve_path(source["path"])
    # A new block over the same bytes admits a second ID, not arbitrary IDs,
    # and must not hide the original block's existing registration.
    pending = {**source, "source_id": "append:block"}
    with refused.declaration_scope([pending]):
        for identity in (source["source_id"], pending["source_id"]):
            selected = refused.resolve_path(source["path"], expected_sha256=source["sha256"], source_id=identity)
            assert selected.read_bytes() == Path(source["path"]).read_bytes()
        with pytest.raises(EngineError) as wrong:
            refused.resolve_path(source["path"], expected_sha256=source["sha256"], source_id="not-admitted")
        assert wrong.value.reason_code == "semantic_source_declaration_conflict"
    Path(source["path"]).write_bytes(b"changed during same invocation")
    with pytest.raises(ValueError):
        resolver.resolve_path(actual)
