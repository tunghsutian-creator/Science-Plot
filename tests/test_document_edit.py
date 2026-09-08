from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core import document_edit_commit as commit
from sciplot_core.studio_core import document_edit as edits
from sciplot_core.studio_core.document_edit_state import (
    edit_state,
    history_directory,
    new_preview_directory,
    preview_identity,
)


@pytest.fixture
def edit_case(tmp_path):
    project = tmp_path / "managed"
    document = project / "studio/document.vsz"
    document.parent.mkdir(parents=True)
    document.write_bytes(b"old native file")
    (project / "plot_request.json").write_text(
        json.dumps({"input": str(project / "source")})
    )
    source = project / "source/data.csv"
    source.parent.mkdir()
    source.write_text("x,y\n1,2\n")
    candidate = tmp_path / "candidate.vsz"
    candidate.write_bytes(b"new native file")
    review = {"base_state": edit_state(project), "changes": [{"test": "transaction"}]}
    review["operation_id"] = preview_identity(review)
    return project, document, candidate, review


def test_sample_mapping_drift_is_rejected_before_candidate_or_audit(edit_case, tmp_path, monkeypatch):
    project, document, _, _ = edit_case
    spec = project / "studio/spec.json"
    spec.write_text('{"series":[]}')
    monkeypatch.setattr(edits, "resolve_project_path", lambda _: project)
    monkeypatch.setattr(edits, "resolve_project_figure", lambda *a: {
        "document": str(document), "spec": str(spec), "figure_id": "f"})
    monkeypatch.setattr(edits, "audit_edited_document", lambda *a: pytest.fail("stale sample mapping audited"))
    output = tmp_path / "preview"
    with pytest.raises(ValueError, match="sample mapping changed"):
        edits.preview_document_edit(project, [], output_dir=output,
                                    expected_document_sha256=file_sha256(document),
                                    expected_spec_sha256="b" * 64, operations=[{"op": "set_style"}])
    assert not output.exists()


def test_commit_preserves_source_and_archives_then_reconciles_lost_response(edit_case):
    project, document, candidate, review = edit_case
    source = (project / "source/data.csv").read_bytes()
    before = document.read_bytes()
    result = commit.commit_document_edit(project, document, candidate, review)
    assert result["status"] == "applied" and result["export_required"] is True
    assert document.read_bytes() == candidate.read_bytes()
    assert Path(result["archive"]).read_bytes() == before
    assert (project / "source/data.csv").read_bytes() == source
    outcome = history_directory(project, review["operation_id"]) / "outcome.json"
    record = json.loads(outcome.read_text())
    record["status"] = "pending"  # Process ended after replace, before success journal.
    outcome.write_text(json.dumps(record))
    assert commit.prior_edit_result(project, review)["status"] == "already_applied"
    assert json.loads(outcome.read_text())["status"] == "applied"
    document.write_bytes(b"later valid native edit")
    with pytest.raises(ValueError, match="since changed"):
        commit.prior_edit_result(project, review)


def test_failed_success_journal_restores_original_bytes_and_mode(
    edit_case, monkeypatch
):
    project, document, candidate, review = edit_case
    document.chmod(0o640)
    before = document.read_bytes()
    write = commit.atomic_write_json

    def fail_once(path, payload):
        if path.name == "outcome.json" and payload.get("status") == "applied":
            raise OSError("journal disk fault")
        write(path, payload)

    monkeypatch.setattr(commit, "atomic_write_json", fail_once)
    with pytest.raises(OSError, match="journal disk fault"):
        commit.commit_document_edit(project, document, candidate, review)
    assert document.read_bytes() == before
    assert document.stat().st_mode & 0o777 == 0o640
    assert (
        commit.read_edit_operation(project, review["operation_id"])["status"]
        == "rolled_back"
    )
    assert not list(document.parent.glob(".external-edit-*"))


def test_install_failure_keeps_canonical_and_retry_succeeds(edit_case, monkeypatch):
    project, document, candidate, review = edit_case
    replace = commit._replace_current_document

    def fail(*_):
        raise OSError("replace fault")

    monkeypatch.setattr(commit, "_replace_current_document", fail)
    with pytest.raises(OSError, match="replace fault"):
        commit.commit_document_edit(project, document, candidate, review)
    assert edit_state(project) == review["base_state"]
    assert commit.prior_edit_result(project, review) is None
    monkeypatch.setattr(commit, "_replace_current_document", replace)
    assert (
        commit.commit_document_edit(project, document, candidate, review)["status"]
        == "applied"
    )


def test_source_revision_change_cannot_be_overwritten(edit_case):
    project, document, candidate, review = edit_case
    before = document.read_bytes()
    (project / "source/data.csv").write_text("x,y\n1,9\n")
    with pytest.raises(ValueError, match="changed after preview"):
        commit.commit_document_edit(project, document, candidate, review)
    assert document.read_bytes() == before
    assert not history_directory(project, review["operation_id"]).exists()


def test_operation_query_rejects_traversal_and_preview_refuses_source(
    edit_case, tmp_path
):
    project, _, _, review = edit_case
    root = history_directory(project, review["operation_id"])
    root.mkdir(parents=True)
    (root / "outcome.json").write_text(
        json.dumps({"document_relative": "studio/../../secret"})
    )
    with pytest.raises(ValueError, match="managed document"):
        commit.read_edit_operation(project, review["operation_id"])
    with pytest.raises(ValueError, match="new preview directory"):
        new_preview_directory(project, project / "source/preview")
    assert not (project / "source/preview").exists()
    outside = new_preview_directory(project, tmp_path / "preview")
    assert outside.is_dir()


def test_changed_recovery_archive_cannot_report_already_applied(edit_case):
    project, document, candidate, review = edit_case
    result = commit.commit_document_edit(project, document, candidate, review)
    Path(result["archive"]).write_bytes(b"wrong baseline")
    with pytest.raises(ValueError, match="archive changed"):
        commit.prior_edit_result(project, review)
    assert file_sha256(document) == file_sha256(candidate)


@pytest.mark.comprehensive
def test_process_exit_after_replace_reconciles_durable_pending_outcome(edit_case):
    project, document, candidate, review = edit_case
    preview_file = candidate.with_suffix(".json")
    preview_file.write_text(json.dumps(review))
    code = """
import json, os, sys
from pathlib import Path
from sciplot_core.studio_core import document_edit_commit as edit
project, document, candidate, review = map(Path, sys.argv[1:])
def stop_after_replace(staged, target):
    os.replace(staged, target)
    os._exit(86)
edit._replace_current_document = stop_after_replace
edit.commit_document_edit(project, document, candidate, json.loads(review.read_text()))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(project),
            str(document),
            str(candidate),
            str(preview_file),
        ],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 86, result.stderr
    outcome = commit.read_edit_operation(project, review["operation_id"])
    assert outcome["status"] == "pending" and outcome["result_is_current"] is True
    assert commit.prior_edit_result(project, review)["status"] == "already_applied"
    assert document.read_bytes() == candidate.read_bytes()


def test_preview_detects_save_between_expected_hash_and_inventory(
    edit_case, tmp_path, monkeypatch
):
    project, document, _, _ = edit_case
    expected = file_sha256(document)
    monkeypatch.setattr(edits, "resolve_project_path", lambda _: project)
    monkeypatch.setattr(
        edits,
        "resolve_project_figure",
        lambda *a: {
            "document": str(document),
            "spec": str(document.with_suffix(".json")),
            "figure_id": "primary",
        },
    )

    def changed_inventory(_):
        document.write_bytes(b"saved by native writer after SHA check")
        return edit_state(project)

    monkeypatch.setattr(edits, "edit_state", changed_inventory)
    with pytest.raises(ValueError, match="changed while capturing"):
        edits.preview_document_edit(
            project,
            [],
            output_dir=tmp_path / "preview",
            expected_document_sha256=expected,
        )
    assert not (tmp_path / "preview").exists()


def test_apply_rejects_inventory_with_different_expected_document_revision(
    edit_case, monkeypatch
):
    project, document, _, review = edit_case
    monkeypatch.setattr(edits, "resolve_project_path", lambda _: project)
    monkeypatch.setattr(
        edits,
        "resolve_project_figure",
        lambda *a: {
            "document": str(document),
            "spec": str(document.with_suffix(".json")),
        },
    )
    review.update(
        kind="sciplot_document_edit_preview",
        version=1,
        status="ready",
        project=str(project),
        figure_id="primary",
        document=str(document),
        document_sha256="0" * 64,
    )
    review["operation_id"] = preview_identity(review)
    with pytest.raises(ValueError, match="does not match its expected"):
        edits.apply_document_edit(project, review)
