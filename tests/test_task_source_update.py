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
    (archive / "source/data.csv").chmod(0o600)
    (archive / "source/data.csv").write_text("changed archive")
    with pytest.raises(ValueError, match="archive changed|sealed candidate view.*bytes"):
        transaction.prior_source_update_result(project, review, validate=lambda: None)


@pytest.mark.parametrize("boundary", range(10))
def test_hard_interruption_restores_exact_baseline_at_every_replace_boundary(revisions, monkeypatch, boundary):
    """A head commit replaces rename rollback; every partial view needs explicit recovery."""
    from sciplot_core.project_store import state, ProjectRecoveryRequired
    from sciplot_core.studio_core.project_command_scope import project_store

    project, candidate, _, review = revisions
    baseline = transaction.project_inventory(project)
    replacement = transaction.project_inventory(candidate)
    store = project_store(project, with_snapshot=True)
    store.snapshot(import_legacy=True)
    names = ["before_storage", "after_generation", "before_head", "after_head"]
    selected = names[boundary] if boundary < 4 else ("before_projection" if boundary % 2 == 0 else "after_projection")
    occurrence = 1 if boundary < 4 else (boundary - 4) // 2 + 1
    original, count = state.boundary, 0
    def interrupt(name):
        nonlocal count
        if name == selected:
            count += 1
            if count == occurrence:
                raise OSError("controlled publication interruption")
        original(name)
    monkeypatch.setattr(state, "boundary", interrupt)
    with pytest.raises(OSError, match="controlled publication interruption"):
        _install(project, candidate, review)
    if boundary < 3:
        assert transaction.project_inventory(project) == baseline
    else:
        with pytest.raises(ProjectRecoveryRequired):
            store.snapshot()
    record = store.commands()[0]
    sealed = {name: Path(path).read_bytes() for name, path in record["staged_paths"].items()}
    monkeypatch.setattr(state, "boundary", original)
    archive = transaction.prior_source_update_result(project, review, validate=lambda: None)
    assert archive is not None and (archive / "studio/document.vsz").read_text() == "old"
    for name in ("raw/data.csv", "source/data.csv", "studio/document.vsz"):
        assert file_sha256(project / name) == replacement[name]
    assert {name: Path(path).read_bytes() for name, path in store.commands()[0]["staged_paths"].items()} == sealed
    assert store.snapshot()["sequence"] == 1
    assert not transaction._outcome_path(project, review).exists()


@pytest.mark.parametrize("after_final_restore", [False, True])
def test_recovery_can_resume_its_own_interruption_and_preserves_candidate(revisions, monkeypatch, after_final_restore):
    from sciplot_core.project_store import state, ProjectRecoveryRequired
    from sciplot_core.studio_core.project_command_scope import project_store

    project, candidate, _, review = revisions
    store = project_store(project, with_snapshot=True)
    store.snapshot(import_legacy=True)
    original = state.boundary
    def first(name):
        if name == "after_head":
            raise OSError("first interruption")
        original(name)
    monkeypatch.setattr(state, "boundary", first)
    with pytest.raises(OSError, match="first interruption"):
        _install(project, candidate, review)
    record = store.commands()[0]
    sealed = {name: Path(path).read_bytes() for name, path in record["staged_paths"].items()}
    def second(name):
        if name == ("after_projection" if after_final_restore else "before_projection"):
            raise OSError("second interruption")
        original(name)
    monkeypatch.setattr(state, "boundary", second)
    with pytest.raises(OSError, match="second interruption"):
        transaction.prior_source_update_result(project, review, validate=lambda: pytest.fail("pending views must not pass audit"))
    with pytest.raises(ProjectRecoveryRequired):
        store.snapshot()
    assert {name: Path(path).read_bytes() for name, path in store.commands()[0]["staged_paths"].items()} == sealed
    monkeypatch.setattr(state, "boundary", original)
    archive = transaction.prior_source_update_result(project, review, validate=lambda: None)
    assert archive is not None and (archive / "source/data.csv").read_text() == "old"
    assert (project / "source/data.csv").read_text() == "new"
    assert store.snapshot()["sequence"] == 1 and len(store.commands()) == 1


def test_lost_source_update_success_receipt_recovers_without_reinstall(revisions, monkeypatch):
    from sciplot_core.project_store import state
    from sciplot_core.studio_core.project_command_scope import project_store

    project, candidate, _, review = revisions
    original = state.boundary
    def lose_success(name):
        if name == "before_reply":
            raise OSError("lost success receipt")
        original(name)
    monkeypatch.setattr(state, "boundary", lose_success)
    with pytest.raises(OSError, match="lost success receipt"):
        _install(project, candidate, review)
    assert (project / "studio/document.vsz").read_text() == "new"
    store = project_store(project, with_snapshot=True)
    before = store.snapshot()
    monkeypatch.setattr(state, "boundary", lambda *_: pytest.fail("complete receipt must not reinstall"))
    archive = transaction.prior_source_update_result(project, review, validate=lambda: None)
    assert archive is not None and (archive / "studio/document.vsz").read_text() == "old"
    assert store.snapshot()["generation"] == before["generation"]
    assert store.commands()[0]["phase"] == "complete"


def test_interrupted_source_update_with_mixed_parts_never_guesses_success(revisions):
    project, candidate, _, review = revisions
    archive = _install(project, candidate, review)
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
    from sciplot_core.project_store import state
    from sciplot_core.studio_core.project_command_scope import project_store

    project, candidate, _, review = revisions
    baseline = transaction.project_inventory(project)
    original = state.boundary
    def stop(name):
        if name == "before_storage":
            raise OSError("stopped before archive publication")
        original(name)
    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(OSError, match="stopped before archive"):
        _install(project, candidate, review)
    assert transaction.project_inventory(project) == baseline
    store = project_store(project, with_snapshot=True)
    assert store.snapshot()["sequence"] == 0 and store.commands()[0]["phase"] == "accepted"
    monkeypatch.setattr(state, "boundary", original)
    archive = transaction.prior_source_update_result(project, review, validate=lambda: None)
    assert archive is not None and (archive / "raw/data.csv").read_text() == "old"
    assert transaction.prior_source_update_result(project, review, validate=lambda: None) == archive
    assert store.snapshot()["sequence"] == 1 and len(store.commands()) == 1


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


@pytest.mark.parametrize("outside", [False, True])
def test_legacy_pending_source_evidence_is_read_only_and_recovers_only_exact_known_bytes(revisions, outside):
    import shutil
    from sciplot_core.studio_core.source_update_recovery import installation_identity
    from sciplot_core.studio_core.project_command_scope import project_store

    project, candidate, _source, review = revisions
    baseline = transaction.project_inventory(project)
    archive = project.parent / ".source_update_history" / project.name / "old-reviewed-operation"
    shutil.copytree(project, archive)
    replacement = transaction.project_inventory(candidate)
    (project / "source/data.csv").write_bytes((candidate / "source/data.csv").read_bytes())
    record = {"version": 2, "status": "pending", "project": str(project), "review": review,
        "archive": str(archive), "base_files": baseline, "archived_files": baseline,
        "result_files": replacement, "replacement_names": ["plot_request.json", "intake_manifest.json", "raw", "source", "studio"]}
    record["installation_sha256"] = installation_identity(record)
    path = transaction._outcome_path(project, review)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    evidence = path.read_bytes()
    if outside:
        (project / "studio/document.vsz").write_bytes(b"unknown manual native bytes")
        current = transaction.project_inventory(project)
        with pytest.raises(ValueError, match="Unknown native/source bytes"):
            transaction.prior_source_update_result(project, review, validate=lambda: pytest.fail("unknown legacy state must not pass audit"))
        assert transaction.project_inventory(project) == current
        assert not (project / ".sciplot_store/head.json").exists()
    else:
        assert transaction.prior_source_update_result(project, review, validate=lambda: pytest.fail("a baseline restore is not completed source adoption")) is None
        assert transaction.project_inventory(project) == baseline
        store = project_store(project)
        generation = store.snapshot()["generation"]
        assert transaction.prior_source_update_result(project, review, validate=lambda: None) is None
        assert store.snapshot()["generation"] == generation
        assert len(store.commands()) == 1
    assert path.read_bytes() == evidence
    assert transaction.project_inventory(archive) == baseline


@pytest.fixture
def rendered_review(revisions, monkeypatch, tmp_path):
    project, candidate, source, review = revisions
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate

    # Only native generation is replaced. The callback now receives the real
    # private-project capability and the old generation's source inventory.
    (project / "studio/spec.json").write_text(json.dumps({"series": [{"source_artifacts": [{
        "path": str(project / "source/data.csv"), "sha256": file_sha256(project / "source/data.csv")
    }]}]}))
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)

    def preview(_project, _source, *, worksheet, on_candidate):
        assert worksheet == "Data"
        with studio_preparation_candidate(store) as private:
            private.write_member("studio/document.vsz", (candidate / "studio/document.vsz").read_bytes())
            on_candidate(private.project_dir, review)
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


def test_invalid_annotated_document_still_blocks_before_candidate(revisions, monkeypatch, tmp_path):
    from sciplot_core.studio_core import source_update

    project, _, source, _ = revisions
    spec = project / "studio/spec.json"
    spec.write_text(json.dumps({"native_annotations": {"version": 1, "items": [{"id": "retained"}]}}))
    monkeypatch.setattr(source_update, "project_figures", lambda _: {"f": (project / "studio/document.vsz", spec)})
    monkeypatch.setattr(source_update, "prepare_candidate", lambda *a, **k: pytest.fail("must not prepare annotated project"))
    result = helper.prepare_source_update_review(project, source, review_path=tmp_path / "task/review.json")
    assert result["status"] == "blocked" and result["previews"] == []
    assert "Annotations currently require ordinary Cartesian curves" in result["source_update"]["reason"]


def test_partial_annotation_answers_retain_prior_choices_after_reload(revisions, monkeypatch, tmp_path):
    from sciplot_core import task_source_execution as execution
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.studio_core.source_update_review import payload_hash

    project, _, _, _ = revisions
    review = {"source_update": {"project_sha256": payload_hash(transaction.project_inventory(project))}}
    identity = canonical_json_sha256(review, allow_nan=False)
    review["revision_id"] = identity
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review))
    first = {"figure_id": "f", "id": "peak1", "action": "remove"}
    second = {"figure_id": "f", "id": "peak2", "action": "remove"}
    state = json.loads(json.dumps({"request": {"project": str(project)}, "revision_id": identity,
        "question": {"review_path": str(review_path)}, "annotation_decisions": [first],
        "status": "needs_input"}))
    seen = []
    monkeypatch.setattr(execution, "save_task", lambda *args: None)
    monkeypatch.setattr(execution, "run_source_preview", lambda root, current: seen.append(current["annotation_decisions"]))
    execution.accept_annotation_response(tmp_path, state, {"expected_revision_id": identity, "annotation_choices": [second]})
    assert seen == [[first, second]]
    with pytest.raises(ValueError, match="重复"):
        execution.accept_annotation_response(tmp_path, state, {"expected_revision_id": identity, "annotation_choices": [second, second]})
    assert state["annotation_decisions"] == [first, second]
