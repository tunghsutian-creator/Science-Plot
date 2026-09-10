from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core import source_update_commit as transaction
from sciplot_core import task_source_update as helper


@pytest.fixture
def revisions(tmp_path):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    for root, value in ((project, "old"), (candidate, "new")):
        for name in ("raw", "source", "studio"):
            (root / name).mkdir(parents=True)
        (root / "plot_request.json").write_text("{}")
        (root / "intake_manifest.json").write_text("{}")
        (root / "studio/spec.json").write_text("{}")
        (root / "studio/document.vsz").write_text(value)
        (root / "raw/data.csv").write_text(value)
        (root / "source/data.csv").write_text(value)
    source = tmp_path / "replacement.csv"
    source.write_text("new")
    review = {"kind": "sciplot_project_source_update", "version": 1, "status": "ready",
              "project": str(project), "source": str(source), "changes": {}, "styles": []}
    return project, candidate, source, review


def _install(project, candidate, review, **kwargs):
    return transaction.install_source_update(
        project, candidate, expected=transaction.project_inventory(project),
        review=review, validate=kwargs.pop("validate", lambda: None), **kwargs,
    )


def test_source_update_recovery_verifies_current_project_and_old_archive(revisions):
    project, candidate, _, review = revisions
    archive = _install(project, candidate, review)
    audits = []
    assert transaction.prior_source_update_result(project, review, validate=lambda: audits.append(True)) == archive
    assert audits == [True]
    (archive / "source/data.csv").write_text("changed archive")
    with pytest.raises(ValueError, match="archive changed"):
        transaction.prior_source_update_result(project, review, validate=lambda: None)


def test_lost_source_update_success_receipt_recovers_without_reinstall(revisions, monkeypatch):
    project, candidate, _, review = revisions
    write = transaction.atomic_write_json

    def lose_success(path, record):
        if record.get("status") == "applied":
            raise OSError("lost success receipt")
        return write(path, record)

    monkeypatch.setattr(transaction, "atomic_write_json", lose_success)
    with pytest.raises(OSError, match="lost success receipt"):
        _install(project, candidate, review)
    assert (project / "studio/document.vsz").read_text() == "new"
    monkeypatch.setattr(transaction, "atomic_write_json", write)
    archive = transaction.prior_source_update_result(project, review, validate=lambda: None)
    assert archive is not None and (archive / "studio/document.vsz").read_text() == "old"
    record = json.loads(transaction._outcome_path(project, review).read_text())
    assert record["status"] == "applied"


def test_interrupted_source_update_with_mixed_parts_never_guesses_success(revisions):
    project, candidate, _, review = revisions
    archive = _install(project, candidate, review)
    path = transaction._outcome_path(project, review)
    record = json.loads(path.read_text())
    record["status"] = "pending"
    path.write_text(json.dumps(record))
    (project / "studio/document.vsz").write_bytes((archive / "studio/document.vsz").read_bytes())
    before = transaction.project_inventory(project)
    with pytest.raises(ValueError, match="interrupted or its result has changed"):
        transaction.prior_source_update_result(project, review, validate=lambda: pytest.fail("must not audit mixed state"))
    assert transaction.project_inventory(project) == before
    assert archive.exists()


def test_source_update_rollback_is_retryable_and_keeps_original_bytes(revisions):
    project, candidate, _, review = revisions
    before = transaction.project_inventory(project)

    def fail_audit():
        raise ValueError("audit failed")

    with pytest.raises(ValueError, match="audit failed"):
        _install(project, candidate, review, validate=fail_audit)
    assert transaction.project_inventory(project) == before
    assert transaction.prior_source_update_result(project, review, validate=lambda: None) is None
    archive = _install(project, candidate, review)
    assert transaction.prior_source_update_result(project, review, validate=lambda: None) == archive


def test_pending_intent_without_any_install_can_retry(revisions, monkeypatch):
    project, candidate, _, review = revisions
    mkdir = Path.mkdir

    def fail_archive(path, *args, **kwargs):
        if ".source_update_history" in path.parts:
            raise OSError("stopped before archive")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_archive)
    with pytest.raises(OSError, match="stopped before archive"):
        _install(project, candidate, review)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    assert transaction.prior_source_update_result(project, review, validate=lambda: None) is None
    archive = _install(project, candidate, review)
    assert transaction.prior_source_update_result(project, review, validate=lambda: None) == archive


@pytest.mark.parametrize("changed", ["source", "delivery"])
def test_completed_source_update_recovery_still_checks_external_inputs(revisions, monkeypatch, changed):
    from sciplot_core.studio_core import source_update

    project, candidate, source, review = revisions
    visible = project.parent / "visible"
    for root in (project, candidate):
        (root / "plot_request.json").write_text(json.dumps({"delivery_output": str(visible)}))
    review.update(source_files=transaction.file_inventory(source),
                  delivery_sha256=source_update.payload_hash(None))
    _install(project, candidate, review)
    if changed == "source":
        source.write_text("another revision")
    else:
        visible.mkdir()
        (visible / "visible.vsz").write_text("external edit")
    before = transaction.project_inventory(project)
    monkeypatch.setattr(source_update, "verify_project_science", lambda *a: pytest.fail("changed external inputs must fail before audit"))
    monkeypatch.setattr(source_update, "_prepared_update", lambda *a: pytest.fail("must not prepare after proven install"))
    with pytest.raises(ValueError, match="selected source or visible delivery changed"):
        source_update.apply_project_source_update(project, review)
    assert transaction.project_inventory(project) == before


@pytest.fixture
def rendered_review(revisions, monkeypatch, tmp_path):
    project, candidate, source, review = revisions

    def preview(_project, _source, *, worksheet, on_candidate):
        assert worksheet == "Data"
        on_candidate(candidate, review)
        return review

    def render(_command, document, _out, output):
        output.write_bytes(b"PNG " + document.read_bytes())
        return {"document": {"path": str(document), "sha256": file_sha256(document)},
                "preview": {"path": str(output), "sha256": file_sha256(output)}}

    monkeypatch.setattr(helper, "preview_project_source_update", preview)
    monkeypatch.setattr(helper, "project_figures", lambda root: {
        "f": (root / "studio/document.vsz", root / "studio/spec.json")})
    monkeypatch.setattr(helper, "run_document_worker", render)
    result = helper.prepare_source_update_review(
        project, source, review_path=tmp_path / "task/review.json", worksheet="Data",
    )
    return project, review, result


def test_task_review_preserves_before_and_candidate_images_and_exact_evidence(rendered_review, monkeypatch):
    project, review, result = rendered_review
    assert [item["scope"] for item in result["previews"]] == ["before", "candidate"]
    assert [Path(item["preview"]["path"]).read_bytes() for item in result["previews"]] == [b"PNG old", b"PNG new"]
    path = Path(result["review_path"])
    assert json.loads(path.read_text()) == result
    seen = []

    def apply(current, bound):
        seen.append((current, bound))
        return {"status": "updated", "ready_to_use": False, "next_action": "save_and_export"}

    monkeypatch.setattr(helper, "apply_project_source_update", apply)
    applied = helper.apply_source_update_review(project, review_path=path, expected_revision_id=result["revision_id"])
    assert seen == [(project, review)]
    assert applied["status"] == "updated" and applied["ready_to_use"] is False


@pytest.mark.parametrize("change", ["image", "review", "revision"])
def test_task_rejects_changed_review_before_any_source_apply(rendered_review, monkeypatch, change):
    project, _, result = rendered_review
    monkeypatch.setattr(helper, "apply_project_source_update", lambda *a: pytest.fail("must not apply"))
    path, identity = Path(result["review_path"]), result["revision_id"]
    if change == "image":
        Path(result["previews"][1]["preview"]["path"]).write_bytes(b"different image")
    elif change == "review":
        result["source_update"]["source"] = "/different/source"
        path.write_text(json.dumps(result))
    else:
        identity = "0" * 64
    with pytest.raises(ValueError, match="changed|变化"):
        helper.apply_source_update_review(project, review_path=path, expected_revision_id=identity)


def test_helper_rejects_new_source_directory_for_saved_review(revisions):
    project, _, source, _ = revisions
    source.unlink()
    source.mkdir()
    (source / "data.csv").write_text("new")
    with pytest.raises(ValueError, match="审阅路径"):
        helper.prepare_source_update_review(project, source, review_path=source / "review.json")
    assert sorted(path.name for path in source.iterdir()) == ["data.csv"]


def test_annotation_source_guard_still_blocks_task_review(revisions, monkeypatch, tmp_path):
    from sciplot_core.studio_core import source_update

    project, _, source, _ = revisions
    spec = project / "studio/spec.json"
    spec.write_text(json.dumps({"native_annotations": {"version": 1, "items": [{"id": "retained"}]}}))
    monkeypatch.setattr(source_update, "project_figures", lambda _: {"f": (project / "studio/document.vsz", spec)})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *a, **k: pytest.fail("must not prepare annotated project"))
    result = helper.prepare_source_update_review(project, source, review_path=tmp_path / "task/review.json")
    assert result["status"] == "blocked" and result["previews"] == []
    assert "annotation_source_revision_required" in result["source_update"]["reason"]
