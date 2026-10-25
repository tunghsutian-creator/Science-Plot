"""Finite host resource caps cannot claim the unrelated sibling namespace."""

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path, selected_source_resolver
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError, ResourceRoot
from sciplot_core.project_store.runtime import project_runtime


def finite_store(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.csv").write_bytes(b"x,y\n1,2\n")
    archive = tmp_path / "project.zip"
    archive.write_bytes(b"generated zip member")
    selected = FileProjectStore(root, locations={"snapshot": ResourceRoot(tmp_path, (archive.name,))})
    baseline = selected.snapshot(import_legacy=True)
    return selected, baseline, archive


def test_finite_archive_parent_does_not_claim_an_explicit_new_source_sibling(tmp_path):
    store, baseline, archive = finite_store(tmp_path)
    incoming = tmp_path / "incoming.csv"
    incoming.write_bytes(b"x,y\n3,4\n")
    with project_runtime(store):
        assert resolve_source_path(incoming) == incoming
        assert resolve_source_path(incoming, expected_sha256=file_sha256(incoming)) == incoming
        assert literal_source_path(incoming) == str(incoming)
        # Ordinary explicitly selected outside IO does not acquire a resource ID.
        with pytest.raises(ProjectStoreError):
            store.logical_path(incoming)
        with pytest.raises(ProjectStoreError):
            resolve_source_path(incoming, source_id="wire-cannot-register", expected_sha256=file_sha256(incoming))
    assert store.snapshot()["generation"] == baseline["generation"]
    assert archive.read_bytes() == b"generated zip member" and selected_source_resolver() is None


def test_finite_directory_view_never_enumerates_or_registers_parent_siblings(tmp_path):
    store, _baseline, archive = finite_store(tmp_path)
    canary = tmp_path / "not-in-the-archive-cap.csv"
    canary.write_bytes(b"unrelated original")
    with project_runtime(store):
        view = resolve_source_path(tmp_path)
        assert view != tmp_path and sorted(path.name for path in view.iterdir()) == [archive.name]
        assert literal_source_path(view) == str(tmp_path)
        assert resolve_source_path(archive).read_bytes() == b"generated zip member"
    assert canary.read_bytes() == b"unrelated original"


@pytest.mark.parametrize("drift", ["hash", "source_id", "changed_bytes"])
def test_finite_registered_member_keeps_its_exact_version_and_identity_refusal(tmp_path, drift):
    store, _baseline, archive = finite_store(tmp_path)
    expected = file_sha256(archive)
    if drift == "changed_bytes":
        archive.write_bytes(b"outside archive edit")
    with project_runtime(store), pytest.raises((ProjectStoreError, ProjectConflict)):
        resolve_source_path(archive, expected_sha256="0" * 64 if drift == "hash" else expected,
                            source_id="unrelated-identity" if drift == "source_id" else None)


def test_whole_host_root_still_rejects_unknown_members_without_same_name_fallback(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "document.vsz").write_bytes(b"generated native")
    whole = tmp_path / "whole"
    whole.mkdir()
    (whole / "known.csv").write_bytes(b"x,y\n1,2\n")
    store = FileProjectStore(root, locations={"whole": whole})
    store.snapshot(import_legacy=True)
    unknown = whole / "unknown.csv"
    unknown.write_bytes(b"x,y\n1,2\n")
    with project_runtime(store), pytest.raises(ProjectStoreError):
        resolve_source_path(unknown)


def test_cold_finite_original_cap_keeps_only_members_while_new_sibling_stays_explicit(tmp_path):
    store, _baseline, archive = finite_store(tmp_path)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    store.root.rename(tmp_path / "project-offline")
    incoming = tmp_path / "incoming.csv"
    incoming.write_bytes(b"new explicit source")
    with project_runtime(cold):
        assert resolve_source_path(archive).read_bytes() == b"generated zip member"
        assert resolve_source_path(incoming) == incoming and literal_source_path(incoming) == str(incoming)
        assert cold.location_members["snapshot"] == ("project.zip",)
    assert not (cold.root / ".sciplot_resources/snapshot/incoming.csv").exists()
