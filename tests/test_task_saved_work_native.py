"""A discovered relocated-source candidate really continues the existing native edit owner."""

import json
import shutil
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core.document_edit_state import audit_edited_document
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.task_control import resume_task, start_task
from sciplot_core.task_saved_work import continue_saved_work, find_saved_work
from sciplot_core import task_saved_work as work


@pytest.mark.comprehensive
def test_copied_source_discovery_returns_native_editable_original_and_explicit_source_revision(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n")
    raw_before = source.read_bytes()
    created = start_task({"version": 1, "action": "create", "source": str(source)}, task_dir=tmp_path / "creation")
    assert created["status"] == "complete", created
    project = Path(created["project"])
    copied_source = tmp_path / "renamed-source.csv"
    shutil.copy2(source, copied_source)
    authority_before = {str(path): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    found = find_saved_work(copied_source, search_roots=[project.parent])
    assert found["scan_complete"] and found["match_count"] == 1, found
    assert found["matches"][0]["source_relation"] == "same_content_other_path"
    continued = continue_saved_work(copied_source, search_roots=[project.parent])
    assert continued["status"] == "current", continued
    assert continued["current"]["scientific_audit"]["status"] == "passed"
    assert {str(path): path.read_bytes() for path in project.rglob("*") if path.is_file()} == authority_before
    request = continued["next_step"]["arguments"]["request"]
    old_document = request["expected_document_sha256"]
    request["operations"] = [{"op": "set_sample_style", "samples": ["E3"], "style": {"width": "1.1pt"}}]
    review = start_task(request, task_dir=tmp_path / "edit")
    assert review["status"] == "needs_review", review
    assert review["preview"]["scientific_audit"]["status"] == "passed"
    finished = resume_task(Path(review["task_dir"]), {"accept_preview": True, "expected_operation_id": review["operation_id"]})
    assert finished["status"] == "complete", finished
    current = inspect_project(project, native=True, figure_id=request["figure_id"])
    figure = current["selected_figure"]
    assert figure["document_sha256"] != old_document
    assert any(widget["type"] == "xy" and widget["settings"].get("PlotLine/width") == "1.1pt"
               for widget in figure["objects"].values()), figure["objects"]
    assert audit_edited_document(Path(figure["document"]), Path(figure["spec"]))["status"] == "passed"
    assert source.read_bytes() == copied_source.read_bytes() == raw_before
    # Exact historical source path alone cannot hide a later scientific revision,
    # even while the saved project's archived inputs remain intact and current.
    source.write_bytes(raw_before.replace(b"450,4", b"450,8"))
    revised = continue_saved_work(source, search_roots=[project], tasks_root=tmp_path / "creation", target=project)
    assert revised["reason_code"] == "source_revision_required", revised
    source_review = start_task(revised["next_step"]["arguments"]["request"], task_dir=tmp_path / "changed-source-review")
    assert source_review["status"] == "needs_review", source_review
    source.write_bytes(raw_before)
    # Two current projects from the same exact scientific source remain two choices.
    copied_project = tmp_path / "copied-project"
    shutil.copytree(project, copied_project)
    ambiguous = continue_saved_work(copied_source, search_roots=[project, copied_project])
    assert ambiguous["status"] == "needs_selection", ambiguous
    assert ambiguous["search"]["match_count"] == 2
    copy_conflict = continue_saved_work(copied_source, search_roots=[copied_project], target=copied_project)
    assert copy_conflict["status"] == "blocked" and copy_conflict["reason_code"] == "project_output_conflict", copy_conflict
    assert copy_conflict["selected"]["delivery_owner"] == str(project)
    # Original external input can move when the owning project's exact raw
    # snapshot remains complete. Discovery does not replace that snapshot.
    source.unlink()
    archived = continue_saved_work(copied_source, search_roots=[project], target=project)
    assert archived["status"] == "current", archived
    # Missing authoritative raw evidence blocks editing and uses explicit update.
    saved_request = json.loads((project / "plot_request.json").read_text())
    raw_snapshot = Path(saved_request["study_model"]["samples"][0]["replicates"][0]["source_file"]["raw_path"])
    raw_snapshot.unlink()
    missing = continue_saved_work(copied_source, search_roots=[project], target=project)
    assert missing["status"] == "blocked" and missing["reason_code"] == "source_revision_required", missing
    revision_request = missing["next_step"]["arguments"]["request"]
    assert revision_request == {"version": 1, "action": "update_source", "project": str(project), "source": str(copied_source)}
    revision = start_task(revision_request, task_dir=tmp_path / "source-revision")
    assert revision["status"] == "blocked", revision
    assert revision["blocker"]["reason_code"] == "source_update_blocked"
    assert "no readable files" in revision["blocker"]["message"]
    evidence = REPO_ROOT / ".tmp_verify/saved_work/native_continuation.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"status": "passed", "discovery": found, "continuation": continued,
        "edit": {"status": finished["status"], "document_sha256": figure["document_sha256"],
                 "before_sha256": old_document, "source_sha256": file_sha256(copied_source)},
        "ambiguous_status": ambiguous["status"], "missing_source": missing,
        "source_revision_status": revision["status"], "changed_source_review_status": source_review["status"]}, indent=2))


@pytest.mark.comprehensive
@pytest.mark.parametrize("source_kind", ["file", "directory"])
def test_legacy_search_source_race_after_final_project_owner_read_fails_closed(tmp_path, monkeypatch, source_kind):
    raw = tmp_path / "UVvis.csv"
    raw.write_text("Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n425,2\n450,4\n475,2\n500,1\n")
    source = raw
    if source_kind == "directory":
        source = tmp_path / "UVvis"
        source.mkdir()
        raw.rename(source / raw.name)
    creation = tmp_path / "creation"
    created = start_task({"version": 1, "action": "create", "source": str(source)}, task_dir=creation)
    assert created["status"] == "complete", created
    project = Path(created["project"])
    copied = tmp_path / ("renamed.csv" if source_kind == "file" else "renamed-data")
    if source_kind == "file":
        shutil.copy2(source, copied)
    else:
        shutil.copytree(source, copied)
    source_before = source_tree_sha256(source)
    authority_before = {str(path): file_sha256(path) for path in project.rglob("*") if path.is_file()}
    read_project = work.project_evidence
    reads = []

    def change_after_final_owner_read(*args, **kwargs):
        current = read_project(*args, **kwargs)
        assert current["continuation_available"]
        reads.append(current["target"])
        if len(reads) == 2:  # After native inspection/audit and the final project query.
            if source_kind == "file":
                copied.write_bytes(copied.read_bytes().replace(b"450,4", b"450,9"))
            else:
                (copied / "later.csv").write_text("new source member\n")
        return current

    monkeypatch.setattr(work, "project_evidence", change_after_final_owner_read)
    result = work.continue_saved_work(copied, search_roots=[project], tasks_root=creation, target=project)
    assert reads == [str(project), str(project)]
    assert result["status"] == "blocked", result
    assert result["reason_code"] == "source_changed_during_continuation"
    assert result["next_step"]["action"] == "find_saved_work_again"
    assert "current" not in result
    assert source_tree_sha256(source) == source_before
    assert {str(path): file_sha256(path) for path in project.rglob("*") if path.is_file()} == authority_before
