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
    from sciplot_core.project_store import FileProjectStore
    project, document, candidate, review = edit_case
    source = (project / "source/data.csv").read_bytes()
    before = document.read_bytes()
    result = commit.commit_document_edit(project, document, candidate, review)
    assert result["status"] == "applied" and result["export_required"] is True
    assert document.read_bytes() == candidate.read_bytes()
    assert Path(result["archive"]).read_bytes() == before
    assert (project / "source/data.csv").read_bytes() == source
    record = FileProjectStore(project).query(review["operation_id"])
    assert record["phase"] == "complete"
    assert not history_directory(project, review["operation_id"]).exists()
    assert commit.prior_edit_result(project, review)["status"] == "already_applied"
    document.write_bytes(b"later valid native edit")
    with pytest.raises(ValueError, match="since changed"):
        commit.prior_edit_result(project, review)


def test_applied_native_edit_chain_requires_contiguous_archives_and_reviewed_sources(edit_case, tmp_path):
    project, document, candidate, _ = edit_case
    spec = document.with_name("spec.json")
    spec.write_text('{"series":[],"color":"old"}')
    candidate_spec = tmp_path / "candidate.spec.json"
    candidate_spec.write_text('{"series":[],"color":"new"}')
    baseline = {str(project / name): digest for name, digest in edit_state(project)["project_files"].items()}

    def apply():
        review = {"kind": "sciplot_document_edit_preview", "version": 2, "status": "ready",
            "project": str(project), "figure_id": "f", "document": str(document),
            "document_sha256": file_sha256(document), "spec": str(spec),
            "base_state": edit_state(project), "changes": [], "operations": [],
            "candidate_spec": {"sha256": file_sha256(candidate_spec)}, "scientific_audit": {"status": "passed"}}
        review["operation_id"] = preview_identity(review)
        commit.commit_document_edit(project, document, candidate, review, spec=spec, candidate_spec=candidate_spec)
        return review

    first = apply()
    candidate.write_bytes(b"second legal native save")
    second = apply()
    arguments = dict(figure_id="f", document=document, spec=spec, baseline_files=baseline)
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
    assert commit.applied_native_edit_chain(project, **arguments) == [first["operation_id"], second["operation_id"]]
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()} == before
    from sciplot_core.project_store import FileProjectStore
    receipt = FileProjectStore(project).query(first["operation_id"])
    archive = Path(receipt["artifact_paths"]["after.vsz"])
    saved = archive.read_bytes()
    archive.chmod(0o600)
    archive.write_bytes(b"tampered archived native")
    with pytest.raises(ValueError, match="sealed|immutable|archive"):
        commit.applied_native_edit_chain(project, **arguments)
    archive.write_bytes(saved)
    preview_path = Path(receipt["artifact_paths"]["preview.json"])
    saved_preview = preview_path.read_bytes()
    preview_path.chmod(0o600)
    preview = json.loads(saved_preview)
    preview["changes"] = [{"unreviewed": True}]
    preview_path.write_text(json.dumps(preview))
    with pytest.raises(ValueError, match="sealed|immutable|reviewed"):
        commit.applied_native_edit_chain(project, **arguments)
    preview_path.write_bytes(saved_preview)
    source_path = str(project / "source/data.csv")
    with pytest.raises(ValueError, match="source or project baseline"):
        commit.applied_native_edit_chain(project, **{**arguments, "baseline_files": {**baseline, source_path: "f" * 64}})
    current = document.read_bytes()
    document.write_bytes(b"external save after legal edits")
    assert commit.applied_native_edit_chain(project, **arguments) is None
    document.write_bytes(current)
    assert commit.applied_native_edit_chain(project, **arguments) == [first["operation_id"], second["operation_id"]]


def test_failed_success_journal_restores_original_bytes_and_mode(edit_case, monkeypatch):
    from sciplot_core.project_store import state
    project, document, candidate, review = edit_case
    document.chmod(0o640)
    before = document.read_bytes()
    from sciplot_core.studio_core.project_command_scope import project_store

    project_store(project).snapshot(import_legacy=True)
    boundary = state.boundary
    def fail(name):
        if name == "before_head":
            raise OSError("head publication disk fault")
        boundary(name)
    monkeypatch.setattr(state, "boundary", fail)
    with pytest.raises(OSError, match="head publication disk fault"):
        commit.commit_document_edit(project, document, candidate, review)
    assert document.read_bytes() == before
    assert document.stat().st_mode & 0o777 == 0o640
    assert commit.read_edit_operation(project, review["operation_id"])["status"] == "pending"
    monkeypatch.setattr(state, "boundary", boundary)
    assert commit.prior_edit_result(project, review)["status"] == "already_applied"
    assert document.read_bytes() == candidate.read_bytes()
    assert document.stat().st_mode & 0o777 == 0o640
    assert not list(document.parent.glob(".external-edit-*"))


def test_install_failure_keeps_canonical_and_retry_succeeds(edit_case, monkeypatch):
    from sciplot_core.project_store import state
    project, document, candidate, review = edit_case
    boundary = state.boundary
    def fail(name):
        if name == "before_projection":
            raise OSError("projection fault")
        boundary(name)
    monkeypatch.setattr(state, "boundary", fail)
    with pytest.raises(OSError, match="projection fault"):
        commit.commit_document_edit(project, document, candidate, review)
    from sciplot_core.project_store import ProjectRecoveryRequired
    with pytest.raises(ProjectRecoveryRequired):
        edit_state(project)
    assert document.read_bytes() == b"old native file"
    monkeypatch.setattr(state, "boundary", boundary)
    result = commit.prior_edit_result(project, review)
    assert result["status"] == "already_applied"
    assert document.read_bytes() == candidate.read_bytes()
    assert Path(result["archive"]).read_bytes() == b"old native file"


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
    archive = Path(result["archive"])
    archive.chmod(0o600)  # Simulate corruption beyond the sealed view's permissions.
    archive.write_bytes(b"wrong baseline")
    with pytest.raises(ValueError, match="sealed|immutable|archive"):
        commit.prior_edit_result(project, review)
    assert file_sha256(document) == file_sha256(candidate)


def test_preview_location_validation_does_not_hash_project_or_delivery(edit_case, tmp_path, monkeypatch):
    from sciplot_core.studio_core import document_edit_state as state
    project, _, _, _ = edit_case
    def unnecessary(*args):
        pytest.fail("Path validation must not read and hash the project/export inventory")
    monkeypatch.setattr(state, "project_inventory", unnecessary)
    monkeypatch.setattr(state, "file_inventory", unnecessary)
    assert new_preview_directory(project, tmp_path / "preview").is_dir()


@pytest.mark.parametrize("key", ["input", "input_path", "data_dir"])
def test_preview_location_resolves_relative_source_against_project(edit_case, tmp_path, key):
    project, _, _, _ = edit_case
    source = tmp_path / "external_source"
    source.mkdir()
    (project / "plot_request.json").write_text(json.dumps({key: "../external_source"}))
    with pytest.raises(ValueError, match="new preview directory"):
        new_preview_directory(project, source / "preview")
    assert not (source / "preview").exists()


@pytest.mark.parametrize("protected", ["project", "delivery", "source", "symlink"])
def test_preview_location_retains_path_boundaries_without_inventory(edit_case, tmp_path, protected):
    project, _, _, _ = edit_case
    delivery, source = tmp_path / "visible", tmp_path / "original"
    delivery.mkdir()
    source.mkdir()
    (project / "plot_request.json").write_text(json.dumps({
        "input": str(source), "delivery_output": str(delivery)}))
    if protected == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path / "outside", target_is_directory=True)
        target = alias / "preview"
    else:
        target = {"project": project, "delivery": delivery, "source": source}[protected] / "preview"
    with pytest.raises(ValueError):
        new_preview_directory(project, target)
    assert not target.exists()


@pytest.mark.comprehensive
def test_process_exit_after_replace_reconciles_durable_pending_outcome(edit_case):
    project, document, candidate, review = edit_case
    preview_file = candidate.with_suffix(".json")
    preview_file.write_text(json.dumps(review))
    code = """
import json, os, sys
from pathlib import Path
from sciplot_core.studio_core import document_edit_commit as edit
from sciplot_core.project_store import state
project, document, candidate, review = map(Path, sys.argv[1:])
def stop_after_projection(name):
    if name == "after_projection":
        os._exit(86)
state.boundary = stop_after_projection
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
    assert commit.prior_edit_result(project, review)["status"] == "already_applied"
    assert document.read_bytes() == candidate.read_bytes()


def test_preview_detects_save_between_expected_hash_and_inventory(edit_case, tmp_path, monkeypatch):
    from sciplot_core.studio_core import document_edit_commands as commands
    project, document, _, _ = edit_case
    (project / "studio/spec.json").write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(project / "source/data.csv"), "sha256": file_sha256(project / "source/data.csv")}
    ]}]}))
    expected = file_sha256(document)
    original = commands.observed_figure_read_state
    def changed_inventory(*args, **kwargs):
        document.write_bytes(b"saved by native writer after SHA check")
        return original(*args, **kwargs)
    monkeypatch.setattr(commands, "observed_figure_read_state", changed_inventory)
    with pytest.raises(ValueError, match="changed while capturing|unregistered outside"):
        edits.preview_document_edit(project, [], output_dir=tmp_path / "preview",
                                    expected_document_sha256=expected)
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


@pytest.fixture
def edit_case_with_delivery(edit_case, tmp_path):
    project, document, candidate, review = edit_case
    delivery = tmp_path / "visible"
    visible_document = delivery / "project" / "document.vsz"
    visible_document.parent.mkdir(parents=True)
    visible_document.write_bytes(document.read_bytes())
    request = json.loads((project / "plot_request.json").read_text())
    request["delivery_output"] = str(delivery)
    (project / "plot_request.json").write_text(json.dumps(request))
    review["base_state"] = edit_state(project)
    review["operation_id"] = preview_identity(review)
    return project, document, candidate, review, delivery


@pytest.mark.parametrize("location", ["", "project", "project/view"])
def test_edit_acceptance_preserves_finder_changes_since_preview(
    edit_case_with_delivery, location,
):
    project, document, candidate, review, delivery = edit_case_with_delivery
    metadata = delivery / location / ".DS_Store"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_bytes(b"Finder opened the delivery after preview")
    assert edit_state(project) == review["base_state"]
    metadata.write_bytes(b"Finder changed its view before acceptance")
    result = commit.commit_document_edit(project, document, candidate, review)
    assert result["status"] == "applied"
    assert document.read_bytes() == candidate.read_bytes()
    assert metadata.read_bytes() == b"Finder changed its view before acceptance"


@pytest.mark.parametrize("changed", ["visible_vsz", "other_dotfile", "source_metadata", "project_metadata"])
def test_edit_acceptance_finder_exception_keeps_real_revision_guards(
    edit_case_with_delivery, changed,
):
    project, document, candidate, review, delivery = edit_case_with_delivery
    (delivery / ".DS_Store").write_bytes(b"incidental Finder state")
    target = {
        "visible_vsz": delivery / "project" / "document.vsz",
        "other_dotfile": delivery / ".personal_notes",
        "source_metadata": project / "source" / ".DS_Store",
        "project_metadata": project / ".DS_Store",
    }[changed]
    target.write_bytes(b"this change remains inside its strict baseline")
    before = document.read_bytes()
    with pytest.raises(ValueError, match="changed after preview"):
        commit.commit_document_edit(project, document, candidate, review)
    assert document.read_bytes() == before
    assert not history_directory(project, review["operation_id"]).exists()


@pytest.mark.parametrize("linked", ["symlink", "hardlink"])
def test_edit_acceptance_never_ignores_linked_finder_name(
    edit_case_with_delivery, tmp_path, linked,
):
    project, document, candidate, review, delivery = edit_case_with_delivery
    target = tmp_path / "precious_file"
    target.write_bytes(b"outside content")
    metadata = delivery / "project" / ".DS_Store"
    if linked == "symlink":
        metadata.symlink_to(target)
    else:
        metadata.hardlink_to(target)
    with pytest.raises(ValueError, match="symbolic links|changed after preview"):
        commit.commit_document_edit(project, document, candidate, review)
    assert document.read_bytes() == b"old native file"
    assert target.read_bytes() == b"outside content"
    assert not history_directory(project, review["operation_id"]).exists()


def test_pending_middle_native_generation_is_never_skipped_as_a_contiguous_chain(edit_case, monkeypatch):
    from sciplot_core.project_store import ProjectRecoveryRequired, state
    project, document, candidate, _ = edit_case
    spec = document.with_name("spec.json")
    spec.write_text('{"series":[]}')
    baseline = {str(project / name): digest for name, digest in edit_state(project)["project_files"].items()}
    review = {"base_state": edit_state(project), "figure_id": "f", "changes": ["first"]}
    review["operation_id"] = preview_identity(review)
    commit.commit_document_edit(project, document, candidate, review)
    candidate.write_bytes(b"second frozen native revision")
    pending = {"base_state": edit_state(project), "figure_id": "f", "changes": ["second"]}
    pending["operation_id"] = preview_identity(pending)
    boundary = state.boundary
    def fail(name):
        if name == "before_projection":
            raise OSError("pending middle generation")
        boundary(name)
    monkeypatch.setattr(state, "boundary", fail)
    with pytest.raises(OSError, match="pending middle"):
        commit.commit_document_edit(project, document, candidate, pending)
    monkeypatch.setattr(state, "boundary", boundary)
    with pytest.raises(ProjectRecoveryRequired, match="recover.*contiguous"):
        commit.applied_native_edit_chain(project, figure_id="f", document=document, spec=spec, baseline_files=baseline)
    assert document.read_bytes() == b"new native file"
