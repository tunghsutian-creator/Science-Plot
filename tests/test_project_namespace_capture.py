"""Finite namespace observation reads latest legacy bytes without changing authority."""

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError
from sciplot_core.project_store import namespace_io


def fixture_namespace(tmp_path):
    project = tmp_path / "project"
    namespace = project / ".sciplot_documents/known"
    namespace.mkdir(parents=True)
    (namespace / "head.json").write_bytes(b'{"revision":1}')
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    return store, before, namespace


def test_capture_latest_known_namespace_preserves_old_generation_and_exact_origin(tmp_path):
    store, before, namespace = fixture_namespace(tmp_path)
    (namespace / "head.json").write_bytes(b'{"revision":2}')
    (namespace / "transaction.json").write_bytes(b'{"new":"legacy authority"}')
    observed = store.capture_namespace(".sciplot_documents/known")
    assert observed["origin_root"] == observed["path"] == str(namespace)
    assert observed["members"]["head.json"]["data"] == b'{"revision":2}'
    assert observed["members"]["transaction.json"]["data"] == b'{"new":"legacy authority"}'
    assert store.snapshot()["generation"] == before["generation"]
    assert store.read_bytes(".sciplot_documents/known/head.json") == b'{"revision":1}'
    assert (namespace / "head.json").read_bytes() == b'{"revision":2}'
    with pytest.raises(ProjectStoreError):
        store.capture_namespace(".sciplot_documents/unregistered")


def test_namespace_capture_refuses_inode_swap_without_reading_replacement(tmp_path, monkeypatch):
    store, _before, namespace = fixture_namespace(tmp_path)
    capture = namespace_io.census
    def swap(fd, **kwargs):
        result = capture(fd, **kwargs)
        namespace.rename(namespace.with_name("original-owned"))
        namespace.mkdir()
        (namespace / "private-unrelated.json").write_bytes(b"must stay untouched")
        return result
    monkeypatch.setattr(namespace_io, "census", swap)
    with pytest.raises(ProjectConflict, match="replaced"):
        store.capture_namespace(".sciplot_documents/known")
    assert list(namespace.iterdir()) == [namespace / "private-unrelated.json"]
    assert (namespace / "private-unrelated.json").read_bytes() == b"must stay untouched"


def test_exact_root_literal_does_not_claim_unrelated_stale_member_bytes(tmp_path):
    store, _before, namespace = fixture_namespace(tmp_path)
    (namespace / "head.json").write_bytes(b"outside legacy update")
    assert store.literal_path(store.root) == str(store.root)
    with pytest.raises(ProjectConflict):
        store.resolve_path(namespace / "head.json")
