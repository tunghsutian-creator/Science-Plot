from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import subprocess
from pathlib import Path

import pytest

from sciplot_core import task_discovery as discovery
from sciplot_core.cli import main
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "UVvis.csv"
    path.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n450,2\n500,1\n")
    return path


def record(root, name, source, **values):
    task = root / name
    task.mkdir(parents=True)
    state = {"kind": "sciplot_task", "version": 1, "task_dir": str(task),
             "request": {"version": 1, "action": "create", "source": str(source)},
             "source_sha256": source_tree_sha256(source), "status": "complete", "phase": "finished",
             "project": str(root / "historical_project"), "selection": {"rule_id": "uvvis_spectrum"}, **values}
    save_task(task, state)
    return task


def inventory(root):
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def test_default_history_recovers_task_without_preparing_rendering_or_writing(source, monkeypatch):
    root = resolve_user_output_layout(source).workspace_root.parent / "tasks"
    task = record(root, "a", source)
    before = inventory(source.parent)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("lookup started a worker"))
    found = discovery.find_tasks(source)
    assert found["tasks_root"] == str(root) and found["match_count"] == 1
    assert found["matches"][0]["task_dir"] == str(task)
    assert found["matches"][0]["source_current"] is True
    assert found["matches"][0]["project"] == str(root / "historical_project")
    assert found["ready_to_use"] is None and found["readiness_evaluated"] is False
    assert found["scan_complete"] and not found["selection_required"]
    assert inventory(source.parent) == before


def test_missing_history_is_explicitly_scoped_and_never_created(source):
    before = inventory(source.parent)
    found = discovery.find_tasks(source)
    assert found["match_count"] == 0 and found["matches"] == []
    assert found["tasks_root_exists"] is False and found["scan_complete"]
    assert not Path(found["tasks_root"]).exists() and inventory(source.parent) == before


def test_same_name_and_identical_bytes_at_another_path_do_not_match(source, tmp_path):
    other = tmp_path / "other" / source.name
    other.parent.mkdir()
    other.write_bytes(source.read_bytes())
    root = tmp_path / "history"
    correct = record(root, "right", source)
    record(root, "same_name", other)
    found = discovery.find_tasks(source, tasks_root=root)
    assert [item["task_dir"] for item in found["matches"]] == [str(correct)]


@pytest.mark.parametrize("missing", [False, True])
def test_changed_or_missing_original_source_is_not_reported_current(source, tmp_path, missing):
    root = tmp_path / "history"
    record(root, "a", source)
    expected = source_tree_sha256(source)
    if missing:
        source.unlink()
    else:
        source.write_text(source.read_text().replace("450,2", "450,9"))
    found = discovery.find_tasks(source, tasks_root=root)
    assert found["match_count"] == 1
    assert found["matches"][0]["source_current"] is False
    assert found["matches"][0]["recorded_source_sha256"] == expected


def test_directory_source_uses_the_same_tree_identity_as_creation(tmp_path):
    source = tmp_path / "data"
    source.mkdir()
    (source / "a.csv").write_text("x,y\n1,2\n")
    root = tmp_path / "history"
    record(root, "a", source)
    assert discovery.find_tasks(source, tasks_root=root)["matches"][0]["source_current"] is True
    (source / "b.csv").write_text("x,y\n3,4\n")
    assert discovery.find_tasks(source, tasks_root=root)["matches"][0]["source_current"] is False


def test_pending_scientific_choice_is_findable_without_implicitly_resuming(source, tmp_path):
    root = tmp_path / "history"
    task = record(root, "pending", source, status="needs_input", phase="scientific_choice", project=None)
    before = (task / "task.json").read_bytes()
    found = discovery.find_tasks(source, tasks_root=root)
    assert found["matches"][0]["status"] == "needs_input" and found["matches"][0]["project"] is None
    assert (task / "task.json").read_bytes() == before


def test_multiple_matches_are_not_auto_selected_and_limit_does_not_hide_ambiguity(source, tmp_path):
    root = tmp_path / "history"
    record(root, "a", source)
    latest = record(root, "b", source, project=str(tmp_path / "different_project"))
    found = discovery.find_tasks(source, tasks_root=root, limit=1)
    assert found["match_count"] == 2 and len(found["matches"]) == 1
    assert found["matches"][0]["task_dir"] == str(latest)
    assert found["selection_required"] and found["has_more_matches"] and found["scan_complete"]


@pytest.mark.parametrize("fault", ["json", "hash", "summary"])
def test_bad_receipt_does_not_hide_valid_matches_and_search_is_marked_incomplete(source, tmp_path, fault):
    root = tmp_path / "history"
    good = record(root, "good", source)
    bad = record(root, "bad", source)
    path = bad / "task.json"
    if fault == "json":
        path.write_text("{broken")
    else:
        state = json.loads(path.read_text())
        state["updated_at"] = 123
        if fault == "hash":
            path.write_text(json.dumps(state))
        else:
            state["selection"] = ["invalid"]
            save_task(bad, state)
    found = discovery.find_tasks(source, tasks_root=root)
    assert [item["task_dir"] for item in found["matches"]] == [str(good)]
    assert found["skipped_records"] == 1 and not found["scan_complete"]
    assert len(found["issues"]) == 1


def test_explicit_task_root_does_not_scan_arbitrary_deeper_directories(source, tmp_path):
    root = tmp_path / "history"
    task = record(root, "direct", source)
    record(root / "old" / "nested", "deep", source)
    assert discovery.find_tasks(source, tasks_root=root)["match_count"] == 1
    assert discovery.find_tasks(source, tasks_root=task)["matches"][0]["task_dir"] == str(task)


def test_symbolic_task_directory_is_never_followed(source, tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    task = record(tmp_path / "outside", "linked", source)
    (root / "link").symlink_to(task, target_is_directory=True)
    assert discovery.find_tasks(source, tasks_root=root)["matches"] == []
    with pytest.raises(ValueError, match="symlink"):
        discovery.find_tasks(source, tasks_root=root / "link")


def test_scan_and_record_size_budgets_do_not_claim_a_complete_search(source, tmp_path, monkeypatch):
    root = tmp_path / "history"
    for name in ("a", "b", "c"):
        record(root, name, source)
    monkeypatch.setattr(discovery, "MAX_SCAN_RECORDS", 2)
    found = discovery.find_tasks(source, tasks_root=root)
    assert found["scanned_records"] == 2 and not found["scan_complete"]
    monkeypatch.setattr(discovery, "MAX_RECORD_BYTES", 1)
    found = discovery.find_tasks(source, tasks_root=root)
    assert not found["matches"] and found["skipped_records"] == 2


@pytest.mark.parametrize("limit", [True, 0, 101, 1.5])
def test_find_limit_is_closed_and_typed(source, limit):
    with pytest.raises(TaskControlError):
        discovery.find_tasks(source, limit=limit)


def test_cli_and_mcp_find_use_the_same_read_only_service(source, tmp_path):
    pytest.importorskip("mcp")
    from sciplot_core.mcp_server.services import invoke_owner
    root = tmp_path / "history"
    record(root, "a", source)
    output = StringIO()
    with redirect_stdout(output):
        assert main(["task", "find", str(source), "--tasks-root", str(root), "--limit", "1", "--json"]) == 0
    expected = discovery.find_tasks(source, tasks_root=root, limit=1)
    assert json.loads(output.getvalue()) == expected
    assert invoke_owner("sciplot_task_find", {"source": str(source), "tasks_root": str(root), "limit": 1}) == expected
