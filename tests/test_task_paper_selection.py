"""One explicit group selection freezes existing paper version guards locally."""

from pathlib import Path
import json

import pytest

from sciplot_core import task_paper_selection as selection
from sciplot_core.cli.parsers import build_parser
from sciplot_core.cli.task_paper import dispatch_paper
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_storage import save_group


@pytest.fixture
def group(tmp_path, monkeypatch):
    root = tmp_path / "group"
    root.mkdir()
    sources, children = [], {}
    for name in ("A", "B"):
        task_dir = root / "tasks" / name
        source = tmp_path / (name + ".csv")
        source.write_text("x,y\n1,2\n")
        sources.append({"id": name, "label": name, "request": {"version": 1, "action": "create", "source": str(source)}})
        children[str(task_dir)] = {"status": "complete", "project": str(tmp_path / ("project-" + name))}
    state = {"kind": "sciplot_task_group", "version": 1, "group_dir": str(root),
             "request": {"version": 1, "title": "Current ordered group", "items": sources},
             "items": [{"id": item["id"], "label": item["label"], "status": "complete", "finished": True,
                        "steps": [{"task_dir": str(root / "tasks" / item["id"])}]} for item in sources]}
    save_group(root, state)
    monkeypatch.setattr(selection, "step_state", lambda step: children[step["task_dir"]])
    monkeypatch.setattr(selection, "project_snapshot", lambda project: ({}, "primary", [{"figure_id": "primary", "status": "ready"}]))
    captures = []

    def capture(project, figure_id):
        captures.append(str(project))
        return {"project": str(project), "version": {"document_sha256": "a" * 64}}

    monkeypatch.setattr(selection, "capture_selection", capture)
    saved = []
    monkeypatch.setattr(selection, "start_paper", lambda request, **options: saved.append((request, options)) or {"status": "complete"})
    return root, state, children, captures, saved


def test_default_order_and_explicit_item_order_capture_versions_once(group, tmp_path):
    root, _, _, captures, saved = group
    assert selection.start_group_paper(root, out=tmp_path / "out", paper_dir=tmp_path / "paper")["status"] == "complete"
    assert [Path(item["project"]).name for item in saved[0][0]["items"]] == ["project-A", "project-B"]
    assert all("expected_version" in item for item in saved[0][0]["items"])
    selection.start_group_paper(root, out=tmp_path / "out2", paper_dir=tmp_path / "paper2", item_ids=["B", "A"])
    assert [Path(item["project"]).name for item in saved[-1][0]["items"]] == ["project-B", "project-A"]
    assert len(captures) == 4


@pytest.mark.parametrize("change", ["not_finished", "pending_child", "duplicate", "unknown"])
def test_incomplete_or_ambiguous_selection_never_reaches_paper(group, tmp_path, change):
    root, state, children, _, saved = group
    ids = None
    if change == "not_finished":
        state["items"][0]["finished"] = False
        save_group(root, state)
    elif change == "pending_child":
        children[next(iter(children))]["status"] = "needs_review"
    else:
        ids = ["A", "A"] if change == "duplicate" else ["missing"]
    with pytest.raises(TaskControlError):
        selection.start_group_paper(root, out=tmp_path / "out", paper_dir=tmp_path / "paper", item_ids=ids)
    assert not saved


def test_existing_checkpoint_reads_frozen_selection_without_group_recapture(group, tmp_path, monkeypatch):
    root, _, _, captures, saved = group
    paper = tmp_path / "paper"
    paper.mkdir()
    out = tmp_path / "out"
    origin = {"kind": "current_group_selection", "group": str(root), "item_ids": None, "title": None, "out": str(out)}
    monkeypatch.setattr(selection, "_load", lambda _: {"selection_origin": {"request": origin}})
    monkeypatch.setattr(selection, "_current_summary", lambda *_: {"status": "blocked", "recorded_status": "complete"})
    monkeypatch.setattr(selection, "load_group", lambda *_: pytest.fail("Retry must not recapture changed group"))
    assert selection.start_group_paper(root, out=out, paper_dir=paper)["recorded_status"] == "complete"
    assert not saved and not captures
    with pytest.raises(TaskControlError):
        selection.start_group_paper(root, out=out, paper_dir=paper, item_ids=["B"])


def test_shared_public_cli_routes_group_and_rejects_mixed_request_options(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(selection, "start_group_paper", lambda group, **kw: calls.append((group, kw)) or {"status": "complete"})
    args = build_parser().parse_args(["task", "paper", "start", "--group", str(tmp_path / "group"), "--out", str(tmp_path / "out"),
                                     "--paper-dir", str(tmp_path / "paper"), "--item-id", "B", "--item-id", "A", "--json"])
    assert dispatch_paper(args) == 0
    assert calls[0][1]["item_ids"] == ["B", "A"]
    assert json.loads(capsys.readouterr().out)["status"] == "complete"
    request = tmp_path / "request.json"
    request.write_text("{}")
    args = build_parser().parse_args(["task", "paper", "start", "--request", str(request), "--out", str(tmp_path / "out"), "--paper-dir", str(tmp_path / "paper")])
    with pytest.raises(ValueError, match="closed wire"):
        dispatch_paper(args)


def test_group_read_is_stable_and_creates_no_original_metadata(group, tmp_path):
    root, _, _, _, _ = group
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    selection.start_group_paper(root, out=tmp_path / 'out', paper_dir=tmp_path / 'paper')
    assert before == {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert not (root.parent / '.sciplot_session_locks').exists()


def test_group_change_during_capture_blocks_before_start(group, tmp_path, monkeypatch):
    root, _, _, _, saved = group
    capture = selection.capture_selection

    def concurrent_change(*args):
        value = json.loads((root / 'group.json').read_text())
        value['request']['title'] = 'concurrent external revision'
        (root / 'group.json').write_text(json.dumps(value))
        return capture(*args)

    monkeypatch.setattr(selection, 'capture_selection', concurrent_change)
    with pytest.raises(ValueError):
        selection.start_group_paper(root, out=tmp_path / 'out', paper_dir=tmp_path / 'paper')
    assert not saved
