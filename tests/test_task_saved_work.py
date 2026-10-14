"""Saved-work discovery never promotes hashes, copies or stale records to authority."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sciplot_core import task_saved_work as work
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.launchers import write_delivery_launcher
from sciplot_core.launchers.delivery_binding import DeliveryBinding
from sciplot_core.plot_engine.storage import commit
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task
from test_managed_external_mutation import _canonical


def inventory(root):
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


@pytest.fixture
def managed(tmp_path):
    root, document, binding = _canonical(tmp_path)
    commit(root, document, binding, "managed_creation")
    return root, Path(document["scientific"]["data_sources"][0]["path"]), binding


def legacy(root, source):
    (root / "studio").mkdir(parents=True)
    (root / "plot_request.json").write_text(json.dumps({"input": str(source)}))
    (root / "studio/document.vsz").write_text("saved native")
    (root / "studio/spec.json").write_text(json.dumps({"series": [{
        "source_artifacts": [{"path": str(source), "sha256": file_sha256(source)}]}]}))
    return root


def receipt(root, source, project=None, **values):
    root.mkdir(parents=True)
    save_task(root, {"kind": "sciplot_task", "version": 1, "task_dir": str(root),
                     "request": {"version": 1, "action": "create", "source": str(source)},
                     "source_sha256": source_tree_sha256(source), "status": "complete", "phase": "finished",
                     "project": str(project) if project else None, **values})
    return root


def delivery(root, source, owner=None):
    (root / "project").mkdir(parents=True)
    native = root / "project/figure.vsz"
    native.write_text("portable native")
    binding = DeliveryBinding(root=str(root), source=str(source),
        request=str(owner / "plot_request.json") if owner else str(root.parent / "gone/plot_request.json"),
        primary=native.name, documents=((native.name, file_sha256(native)),))
    write_delivery_launcher(root, binding=binding)
    return root


def test_managed_discovery_and_continuation_use_existing_seals_without_native_or_writes(managed, tmp_path, monkeypatch):
    root, source, _ = managed
    before = inventory(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("read started native worker"))
    found = work.find_saved_work(source, search_roots=[tmp_path])
    assert found["scan_complete"] and found["match_count"] == 1
    assert found["matches"][0]["target"] == str(root)
    assert found["matches"][0]["authority"] == "sciplot_document"
    continued = work.continue_saved_work(source, search_roots=[tmp_path])
    assert continued["status"] == "current"
    assert continued["next_step"]["arguments"] == {"target": str(root)}
    assert continued["ready_to_use"] is None and not continued["readiness_evaluated"]
    assert inventory(tmp_path) == before
    from sciplot_core.plot_engine.service import PlotService
    service = PlotService()
    try:
        # The returned arguments enter the actual existing open owner. Missing
        # disposable native artifacts stay dirty, while semantic IDs are current.
        opened = service.open(Path(continued["next_step"]["arguments"]["target"]))
        assert opened["plot_id"] == continued["current"]["plot_id"]
        assert opened["scientific_hash"] == continued["current"]["scientific_hash"]
    finally:
        service.close()


def test_renamed_or_copied_source_is_candidate_evidence_without_rebinding(managed, tmp_path):
    root, source, _ = managed
    renamed = tmp_path / "renamed.csv"
    shutil.copy2(source, renamed)
    before = inventory(tmp_path)
    found = work.find_saved_work(renamed, search_roots=[root])
    assert found["matches"][0]["source_relation"] == "same_content_other_path"
    assert work.continue_saved_work(renamed, search_roots=[root])["status"] == "current"
    source.unlink()
    stale = work.continue_saved_work(renamed, search_roots=[root])
    assert stale["status"] == "blocked" and stale["reason_code"] == "document_conflict"
    assert inventory(tmp_path) == {path: value for path, value in before.items() if path != str(source)}


def test_same_name_different_bytes_never_match(managed, tmp_path):
    root, source, _ = managed
    other = tmp_path / "elsewhere" / source.name
    other.parent.mkdir()
    other.write_text("different content")
    assert work.find_saved_work(other, search_roots=[root])["match_count"] == 0


def test_exact_path_changed_bytes_reports_conflict_not_a_fresh_authority(managed):
    root, source, _ = managed
    source.write_text("different content")
    continued = work.continue_saved_work(source, search_roots=[root])
    assert continued["status"] == "blocked"
    assert str(source) in continued["selected"]["document"]["changed_inputs"]


def test_copied_managed_root_cannot_operate_original_absolute_binding(managed, tmp_path):
    root, source, _ = managed
    copied = tmp_path / "copied"
    shutil.copytree(root, copied)
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[copied])
    assert found["match_count"] == 0 and not found["scan_complete"]
    assert "another authority root" in found["issues"][0]["message"]
    assert work.continue_saved_work(source, search_roots=[copied], target=copied)["status"] == "blocked"
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("mutation", ["untracked", "external"])
def test_managed_native_external_save_is_a_conflict(managed, mutation):
    root, source, binding = managed
    native = Path(binding["document"])
    native.parent.mkdir(parents=True)
    native.write_text("native bytes")
    if mutation == "external":
        (native.parent / "build.json").write_text(json.dumps({"ir_hash": binding["ir_hash"],
            "document_sha256": "a" * 64}))
    found = work.find_saved_work(source, search_roots=[root])
    assert found["matches"][0]["state"] == "document_conflict"
    assert not found["matches"][0]["continuation_available"]


def test_tampered_managed_canonical_model_is_not_a_continuable_head(managed, tmp_path):
    root, source, binding = managed
    Path(binding["canonical_document"]).write_text("{}")
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[root])
    assert not found["matches"] and not found["scan_complete"]
    assert inventory(tmp_path) == before


def test_pending_managed_transaction_requires_its_existing_owner(managed):
    from sciplot_core.plot_engine.storage import reserve
    root, source, _ = managed
    reserve(root, {"id": "pending-edit", "phase": "applying",
                   "request": {"idempotency_key": "unfinished"}})
    continued = work.continue_saved_work(source, search_roots=[root])
    assert continued["status"] == "blocked" and continued["reason_code"] == "document_conflict"
    assert continued["selected"]["document"]["pending"]["phase"] == "applying"


def test_multiple_same_source_projects_are_not_deduplicated_or_auto_selected(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    first = legacy(tmp_path / "first", source)
    second = tmp_path / "second"
    shutil.copytree(first, second)
    found = work.find_saved_work(source, search_roots=[tmp_path], limit=1)
    assert found["match_count"] == 2 and found["selection_required"] and found["has_more_matches"]
    assert work.continue_saved_work(source, search_roots=[tmp_path])["status"] == "needs_selection"
    selected = work.continue_saved_work(source, search_roots=[tmp_path], target=second)
    assert selected["reason_code"] == "source_evidence_missing"  # No full raw-tree creation evidence.


def test_project_directory_names_do_not_hide_candidates(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    project = legacy(tmp_path / "raw", source)
    found = work.find_saved_work(source, search_roots=[tmp_path])
    assert found["matches"][0]["target"] == str(project)


def test_missing_history_still_finds_document_authority(managed):
    root, source, _ = managed
    found = work.find_saved_work(source, search_roots=[root])
    assert not found["tasks"] and found["matches"][0]["continuation_available"]


def test_missing_project_record_is_historical_and_never_recreated(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source, tmp_path / "gone")
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[task.parent])
    assert found["matches"][0]["state"] == "historical_task"
    continued = work.continue_saved_work(source, search_roots=[task.parent])
    assert continued["status"] == "blocked"
    assert continued["next_step"]["arguments"] == {"task": str(task)}
    assert inventory(tmp_path) == before and not (tmp_path / "gone").exists()


def test_task_for_renamed_source_is_findable_but_cannot_replay_original_location(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source)
    renamed = source.with_name("renamed.csv")
    source.rename(renamed)
    found = work.find_saved_work(renamed, search_roots=[task.parent])
    assert found["tasks"][0]["source_relation"] == "same_content_other_path"
    assert not found["tasks"][0]["resume_available"]
    assert work.continue_saved_work(renamed, search_roots=[task.parent])["status"] == "blocked"


def test_moved_task_receipt_is_not_treated_as_a_new_resumable_task(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source)
    task.rename(task.parent / "moved")
    found = work.find_saved_work(source, search_roots=[task.parent])
    assert found["tasks"] == [] and not found["scan_complete"]
    assert found["issues"][0]["reason_code"] == "invalid_task"


def test_snapshot_only_and_relocated_delivery_never_claim_current(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    package = delivery(tmp_path / "snapshot", source)
    copied = tmp_path / "copied-export"
    package.rename(copied)
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[copied])
    assert found["matches"][0]["state"] == "export_snapshot"
    continued = work.continue_saved_work(source, search_roots=[copied])
    assert continued["status"] == "blocked" and continued["reason_code"] == "export_snapshot"
    assert continued["ready_to_use"] is None and inventory(tmp_path) == before


def test_snapshot_with_missing_project_is_associated_only_by_valid_creation_receipt(tmp_path):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    gone = tmp_path / "gone"
    task = receipt(tmp_path / "tasks/a", source, gone)
    package = delivery(tmp_path / "snapshot", gone / "source", gone)
    copied_source = source.with_name("renamed.csv")
    shutil.copy2(source, copied_source)
    found = work.find_saved_work(copied_source, search_roots=[package, task.parent])
    snapshots = [item for item in found["matches"] if item["kind"] == "delivery"]
    assert snapshots[0]["state"] == "export_snapshot"
    assert snapshots[0]["recorded_source"] == str(source)
    assert work.continue_saved_work(copied_source, search_roots=[package, task.parent], target=package)["status"] == "blocked"


@pytest.mark.parametrize("change", ["bytes", "inventory"])
def test_unmerged_visible_edit_blocks_the_canonical_project_as_well(tmp_path, change):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    project = legacy(tmp_path / "owner", source)
    package = delivery(tmp_path / "visible", source, project)
    request = json.loads((project / "plot_request.json").read_text())
    request["delivery_output"] = str(package)
    (project / "plot_request.json").write_text(json.dumps(request))
    if change == "bytes":
        (package / "project/figure.vsz").write_text("visible saved edits")
    else:
        (package / "project/second.vsz").write_text("another saved native figure")
    before = inventory(tmp_path)
    found = work.find_saved_work(source, search_roots=[project, package])
    owner = next(item for item in found["matches"] if item["target"] == str(project))
    assert owner["state"] == "visible_edits_require_recovery" and not owner["continuation_available"]
    continued = work.continue_saved_work(source, search_roots=[project, package], target=project)
    assert continued["reason_code"] == "visible_edits_require_recovery"
    narrow = work.continue_saved_work(source, search_roots=[project], target=project)
    assert narrow["reason_code"] == "visible_edits_require_recovery"
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("fault", ["symlink_source", "symlink_scope", "symlink_record", "malformed_path", "malformed_json"])
def test_unsafe_or_malformed_paths_fail_closed(tmp_path, fault):
    source = tmp_path / "raw.csv"
    source.write_text("x,y\n1,2\n")
    task = receipt(tmp_path / "tasks/a", source)
    if fault == "symlink_source":
        linked = source.with_name("linked.csv")
        linked.symlink_to(source)
        with pytest.raises(ValueError, match="symlink"):
            work.find_saved_work(linked, search_roots=[task.parent])
    elif fault == "symlink_scope":
        linked = tmp_path / "linked"
        linked.symlink_to(task.parent, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            work.find_saved_work(source, search_roots=[linked])
    else:
        if fault == "symlink_record":
            original = task / "task.json"
            original.rename(task / "original.json")
            original.symlink_to(task / "original.json")
        elif fault == "malformed_json":
            (task / "task.json").write_text("broken JSON")
        else:
            state = json.loads((task / "task.json").read_text())
            state["project"] = ""
            save_task(task, state)
        found = work.find_saved_work(source, search_roots=[task.parent])
        assert not found["scan_complete"] and found["issue_count"]
        assert work.continue_saved_work(source, search_roots=[task.parent])["status"] == "blocked"


def test_scan_and_read_budgets_do_not_hide_unknown_candidates(managed, tmp_path, monkeypatch):
    root, source, _ = managed
    monkeypatch.setattr(work, "MAX_SCAN_ENTRIES", 1)
    found = work.find_saved_work(source, search_roots=[tmp_path])
    assert not found["scan_complete"] and found["selection_required"]
    monkeypatch.setattr(work, "MAX_SCAN_ENTRIES", 2000)
    monkeypatch.setattr(work, "MAX_RECORD_BYTES", 1)
    found = work.find_saved_work(source, search_roots=[root])
    assert not found["scan_complete"] and not found["matches"]


def test_default_scopes_are_source_adjacent_named_paths_and_broad_scopes_are_rejected(managed):
    _, source, _ = managed
    found = work.find_saved_work(source)
    assert str(source.parent) not in found["search_roots"]
    assert all(Path(path).parent == source.parent or Path(path).parent.parent == source.parent
               for path in found["search_roots"])
    with pytest.raises(TaskControlError, match="too broad"):
        work.find_saved_work(source, search_roots=[Path("/")])
    with pytest.raises(TaskControlError):
        work.find_saved_work(source, search_roots=[])


def test_explicit_target_must_belong_to_discovered_candidates(managed, tmp_path):
    root, source, _ = managed
    result = work.continue_saved_work(source, search_roots=[root], target=tmp_path / "other")
    assert result["status"] == "blocked" and result["reason_code"] == "selected_target_not_discovered"
