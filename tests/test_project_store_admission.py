"""Atomic explicit-open admission belongs to the existing project writer."""

import pytest

from sciplot_core.foundation.project_session_lease import ProjectSessionBusy
from sciplot_core.project_store import FileProjectStore, ProjectRecoveryRequired
from sciplot_core.project_store.io import StoreIO


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.csv").write_bytes(b"x,y\n1,2\n")
    return FileProjectStore(root)


def test_new_open_validates_before_metadata_creation_under_the_existing_writer(store):
    calls = []

    def validate():
        assert not (store.root / ".sciplot_store").exists()
        with pytest.raises(ProjectSessionBusy):
            FileProjectStore(store.root).snapshot(import_legacy=True)
        calls.append(True)

    before = (store.root / "source.csv").read_bytes()
    opened = store.admit_open(before_import=validate)
    assert calls == [True]
    assert opened["sequence"] == 0 and opened["origin"] == "explicit_legacy_import"
    assert store.snapshot()["generation"] == opened["generation"]
    assert (store.root / "source.csv").read_bytes() == before


def test_failed_open_validation_does_not_create_metadata_or_touch_source(store):
    before = (store.root / "source.csv").read_bytes()

    def reject():
        raise ValueError("scientific input preflight refused")

    with pytest.raises(ValueError, match="scientific input preflight refused"):
        store.admit_open(before_import=reject)
    assert not (store.root / ".sciplot_store").exists()
    assert (store.root / "source.csv").read_bytes() == before


@pytest.mark.parametrize("contents", ["empty", "partial"])
def test_existing_incomplete_metadata_cannot_gain_creation_provenance(store, contents):
    metadata = store.root / ".sciplot_store"
    metadata.mkdir()
    if contents == "partial":
        (metadata / "unfinished.json").write_bytes(b"keep interrupted writer evidence")
    before = {path.name: path.read_bytes() for path in metadata.iterdir()}
    with pytest.raises(ProjectRecoveryRequired):
        store.admit_open(before_import=lambda: pytest.fail("existing metadata is not new import work"))
    assert {path.name: path.read_bytes() for path in metadata.iterdir()} == before


def test_reopen_keeps_its_existing_head_without_running_new_import_validation(store):
    opened = store.admit_open(before_import=lambda: None)
    again = store.admit_open(before_import=lambda: pytest.fail("existing head is not a new import"))
    assert again["project_id"] == opened["project_id"]
    assert again["generation"] == opened["generation"]


def test_owned_pristine_io_admits_reentrantly_and_creation_does_not_survive_release(store):
    io = StoreIO(store.root, {})
    calls = []
    with io.locked():
        assert io.created_store is True
        opened = store.admit_open(before_import=lambda: calls.append(True))
        assert store.snapshot()["generation"] == opened["generation"]
    assert calls == [True] and io.created_store is False
    with io.locked():
        assert io.created_store is False
        assert store.admit_open(before_import=lambda: pytest.fail("reacquired IO is not a new store"))["generation"] == opened["generation"]


def test_created_empty_io_released_without_head_is_partial_at_the_next_admission(store):
    io = StoreIO(store.root, {})
    with io.locked():
        assert io.created_store is True
    assert io.created_store is False
    with pytest.raises(ProjectRecoveryRequired):
        store.admit_open(before_import=lambda: pytest.fail("old creation provenance escaped its IO"))
    assert not (store.root / ".sciplot_store/head.json").exists()


def test_current_owned_creation_cannot_authorize_import_over_partial_contents(store):
    io = StoreIO(store.root, {})
    with io.locked():
        assert io.created_store is True
        io.write("unfinished.json", {"retained": "incomplete own writer"})
        before = (store.root / ".sciplot_store/unfinished.json").read_bytes()
        with pytest.raises(ProjectRecoveryRequired):
            store.admit_open(before_import=lambda: pytest.fail("nonpristine creation is recovery work"))
        assert (store.root / ".sciplot_store/unfinished.json").read_bytes() == before
    assert not (store.root / ".sciplot_store/head.json").exists()
