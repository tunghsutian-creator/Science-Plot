"""Only an explicit private clone may serialize manifests without a generation."""

import json

import pytest

from sciplot_core.project_manifest import edit_intake_project_manifest, private_project_manifest_scope
from sciplot_core.project_store import FileProjectStore


def test_private_manifest_edits_preserve_mirrors_without_creating_store_or_head(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir(mode=0o700)
    for name in ("intake_manifest.json", "candidate.sciplot.json"):
        (candidate / name).write_text('{"native":"old"}')
    with private_project_manifest_scope(candidate):
        with edit_intake_project_manifest(candidate, require_existing=True) as payload:
            payload["native"] = "private new"
    assert json.loads((candidate / "intake_manifest.json").read_text()) == {"native": "private new"}
    assert (candidate / "intake_manifest.json").read_bytes() == (candidate / "candidate.sciplot.json").read_bytes()
    assert not (candidate / ".sciplot_store").exists()
    assert not (tmp_path / ".sciplot_session_locks").exists()


def test_private_manifest_capability_refuses_committed_project_and_path_swap(tmp_path):
    active = tmp_path / "active"
    active.mkdir(mode=0o700)
    (active / "intake_manifest.json").write_bytes(b"{}")
    FileProjectStore(active).snapshot(import_legacy=True)
    with pytest.raises(ValueError, match="identity"):
        with private_project_manifest_scope(active):
            pytest.fail("Committed project was admitted as a private candidate")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / "intake_manifest.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="identity"):
        with private_project_manifest_scope(private):
            private.rename(tmp_path / "owned-original")
            private.mkdir(mode=0o700)
            with edit_intake_project_manifest(private):
                pytest.fail("A replacement directory stole the private capability")
    assert not list(private.iterdir())
