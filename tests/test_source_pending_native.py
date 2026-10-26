"""A real reviewed Veusz source candidate moves and applies without reexecution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from test_project_source_update_native import _cli, _files, _native, _source
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process.session import _close_workers
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio import export_native_document_artifacts
from sciplot_core.studio_core import source_update
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.studio_core.project_query import inspect_project

pytestmark = pytest.mark.comprehensive


def pending_native_scenario(root: Path, project: Path, monkeypatch) -> None:
    incoming = root / "pending-current.csv"
    incoming.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nA,A,B,B\n"
                        "400,11,400,12\n450,12,450,13\n500,13,500,14\n")
    original_input = incoming.read_bytes()
    raw = _files(project / "raw"), _files(project / "source")
    saved_native = (project / "studio/document.vsz").read_bytes()
    starts, popen = [], subprocess.Popen
    def observe(*args, **kwargs):
        process = popen(*args, **kwargs)
        starts.append(process)
        return process
    monkeypatch.setattr(subprocess, "Popen", observe)
    try:
        review = source_update.preview_project_source_update(project, incoming)
        assert review["status"] == "ready" and review["version"] == 2, review
        assert (project / "studio/document.vsz").read_bytes() == saved_native
        assert (_files(project / "raw"), _files(project / "source")) == raw
        repository = project_store(project, with_snapshot=True)
        record = repository.query(review["command_key"])
        assert record["phase"] == "needs_review" and record["decision_id"] == review["decision_id"]
        frozen = record["draft"]["writes"]["studio/document.vsz"]["sha256"]
        assert frozen != file_sha256(project / "studio/document.vsz")
        _close_workers()
        assert starts and all(process.poll() is not None for process in starts)
        prepared_count = len(starts)
        bundle = repository.export_bundle(root / "pending-bundle")
        moved = FileProjectStore.import_bundle(bundle, root / "moved")
        project.rename(root / "previous-project-offline")
        incoming.rename(root / "incoming-offline.csv")
        with monkeypatch.context() as frozen_apply:
            frozen_apply.setattr(source_update, "prepare_candidate", lambda *_a, **_kw: pytest.fail("moved source review must not prepare again"))
            result = source_update.apply_project_source_update(moved.root, review)
            assert result["status"] == "updated" and result["ready_to_use"] is False
            assert len(starts) == prepared_count
            assert source_update.apply_project_source_update(moved.root, review)["status"] == "already_applied"
            assert len(starts) == prepared_count
        assert file_sha256(moved.root / "studio/document.vsz") == frozen
        assert (_files(moved.root / "raw"), _files(moved.root / "source")) == raw
        state = _native(moved.root / "studio/document.vsz")
        assert state["series"]["A"]["y"] == [11, 12, 13]
        assert state["series"]["B"]["y"] == [12, 13, 14]
        current = inspect_project(moved.root, native=False)
        assert current["status"] == "ok" and current["source"]["current"] is True
        exported = export_native_document_artifacts(moved.root / "studio/document.vsz", formats=["pdf", "tiff_300"])
        assert exported["standalone_export"]["export_ready"] is True
        assert exported["document_audit"]["status"] == "passed"
        assert file_sha256(moved.root / "studio/document.vsz") == frozen
        assert not project.exists() and not incoming.exists()
        assert (root / "incoming-offline.csv").read_bytes() == original_input
        (root / "pending-native-evidence.json").write_text(json.dumps({
            "pid": os.getpid(), "parent_pid": os.getppid(), "project_id": record["project_id"],
            "command_key": review["command_key"], "decision_id": review["decision_id"],
            "prepared_workers": prepared_count, "apply_added_workers": 0,
            "native_sha256": frozen, "public_source_current": True,
            "audit_status": exported["document_audit"]["status"], "requested_formats": ["pdf", "tiff_300"],
            "checks": ["real_native_preview", "unchanged_old_project", "pending_bundle_move",
                       "exact_original_decision", "no_prepare_or_native_on_apply", "raw_source_preserved",
                       "public_current_query", "public_native_export_and_scientific_audit"]}, indent=2))
    finally:
        _close_workers()
        assert all(process.poll() is not None for process in starts)
        (root / "pending-native-workers.json").write_text(json.dumps([
            {"pid": process.pid, "returncode": process.returncode} for process in starts], indent=2))


def test_real_pending_source_review_moves_and_applies_the_same_native_candidate(tmp_path, monkeypatch):
    initial = tmp_path / "initial.csv"
    _source(initial)
    created = _cli(initial, "--out", tmp_path / "visible", "--rule", "uvvis_spectrum", "--export", "pdf,tiff_300")
    pending_native_scenario(tmp_path, Path(created["project_dir"]), monkeypatch)
