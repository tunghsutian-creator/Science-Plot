"""A source review reuses only the same immutable candidate and original read set."""
import json
import shutil

import pytest

from test_project_query import project as project
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core import source_update
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store
from sciplot_core.project_commands import ProjectCommands
from sciplot_core.studio_core.source_update_commands import source_review_binding, stage_source_update
from sciplot_core.studio_core.source_update_files import file_inventory, project_inventory
from sciplot_core.studio_core.source_update_review import payload_hash


def prepared(project, tmp_path):
    (project / "raw").mkdir()
    (project / "raw/original.csv").write_bytes(b"preserved instrument output")
    candidate = tmp_path / "frozen-source"
    shutil.copytree(project, candidate)
    (candidate / "source/data.csv").write_bytes(b"audited candidate table")
    source = tmp_path / "incoming.csv"
    source.write_bytes(b"confirmed new original source")
    review = {"kind": "sciplot_project_source_update", "version": 1, "status": "ready",
        "project": str(project), "source": str(source), "source_kind": "file", "worksheet": None,
        "source_files": file_inventory(source), "source_tree_sha256": source_tree_sha256(source),
        "annotation_decisions": [], "project_sha256": payload_hash(project_inventory(project)),
        "delivery_sha256": payload_hash(None), "changes": {}, "styles": []}
    return candidate, source, review


@pytest.mark.parametrize("deletion", [False, True])
def test_source_preview_replay_reconstructs_frozen_candidate_without_native_preparation(project, tmp_path, monkeypatch, deletion):
    candidate, source, review = prepared(project, tmp_path)
    if deletion:
        (project / "studio/old-metadata.json").write_bytes(b"old native preparation metadata")
        review["project_sha256"] = payload_hash(project_inventory(project))
    saved = stage_source_update(project, candidate, review)
    before = project_inventory(project)
    monkeypatch.setattr(source_update, "project_figures", lambda root: {"first": (root / "studio/document.vsz", root / "studio/spec.json")})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("must not reprepare a sealed candidate"))
    monkeypatch.setattr(source_update, "capture_project_styles", lambda *_a: pytest.fail("must not reinspect old native"))
    monkeypatch.setattr(source_update, "_audit_exact_document_data", lambda **_kw: pytest.fail("must not reaudit frozen science"))
    seen = []
    def preview(path, value):
        assert value == saved
        assert (path / "source/data.csv").read_bytes() == b"audited candidate table"
        assert not (path / "studio/old-metadata.json").exists()
        assert not (path / ".sciplot_store").exists()
        seen.append(path)
    assert source_update.preview_project_source_update(project, source, on_candidate=preview) == saved
    assert len(seen) == 1 and not seen[0].exists()
    assert project_inventory(project) == before
    assert len(ProjectCommands(project_store(project)).commands()) == 1


def test_unknown_source_preview_does_not_bypass_its_saved_key(project, tmp_path, monkeypatch):
    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    binding, intent, key = source_review_binding(store, snapshot, review)
    command = command_for_binding(store, binding, kind="source_update", key=key, writes=[], request=intent)
    store.reserve(key, command.command_digest, expected_generation=command.expected_generation,
        read_set=dict(command.read_set), write_set=[], metadata=command.to_payload())
    store.mark_applying(key, command.command_digest)
    monkeypatch.setattr(source_update, "project_figures", lambda root: {"first": (root / "studio/document.vsz", root / "studio/spec.json")})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("must not retry unknown preview"))
    result = source_update.preview_project_source_update(project, source)
    assert result["status"] == "blocked" and "already entered execution" in result["reason"]
    assert len(store.commands()) == 1 and store.query(key)["phase"] == "unknown"


def test_source_identity_and_entire_read_witness_are_part_of_the_normalized_intent(project, tmp_path):
    _candidate, source, review = prepared(project, tmp_path)
    store = project_store(project, with_snapshot=True)
    snapshot = store.snapshot(import_legacy=True)
    _binding, _intent, key = source_review_binding(store, snapshot, review)
    same_name = tmp_path / "other" / source.name
    same_name.parent.mkdir()
    same_name.write_bytes(source.read_bytes())
    assert source_review_binding(store, snapshot, {**review, "source": str(same_name)})[2] != key
    newer = json.loads(json.dumps(snapshot))
    newer["files"]["runs/late.json"] = {"sha256": "a" * 64, "size": 4, "mode": 0o644, "file_id": "b" * 32}
    assert source_review_binding(store, newer, review)[2] != key
