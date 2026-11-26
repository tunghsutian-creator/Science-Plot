"""One explicit group selection freezes existing paper version guards locally."""

from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from sciplot_core import task_paper_selection as selection, task_papers as paper
from sciplot_core.cli.parsers import build_parser
from sciplot_core.cli.task_paper import dispatch_paper
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_storage import save_group


_REGISTERED_VERSION = {"document_sha256": "a" * 64, "spec_sha256": "b" * 64}


@pytest.fixture
def group(tmp_path, monkeypatch):
    root = tmp_path / "group"
    root.mkdir()
    sources, children = [], {}
    for name in ("A", "B"):
        task_dir = root / "tasks" / name
        source = tmp_path / (name + ".csv")
        source.write_text("x,y\n1,2\n")
        sources.append({"id": name, "label": {"A": "P0.3/0.7 log", "B": "P0.5/0.5 linear"}[name], "request": {"version": 1, "action": "create", "source": str(source)}})
        children[str(task_dir)] = {"status": "complete", "project": str(tmp_path / ("project-" + name))}
    state = {"kind": "sciplot_task_group", "version": 1, "group_dir": str(root),
             "request": {"version": 1, "title": "Current ordered group", "items": sources},
             "items": [{"id": item["id"], "label": item["label"], "status": "complete", "finished": True,
                        "steps": [{"task_dir": str(root / "tasks" / item["id"])}]} for item in sources]}
    save_group(root, state)
    monkeypatch.setattr(selection, "step_state", lambda step: children[step["task_dir"]])
    monkeypatch.setattr(selection, "observe_legacy_project", lambda _: SimpleNamespace(
        figures=[{"figure_id": "primary", "status": "ready", **_REGISTERED_VERSION}], require_current=lambda: None))
    saved = []
    monkeypatch.setattr(selection, "start_paper", lambda request, **options: saved.append((request, options)) or {"status": "complete"})
    monkeypatch.setattr(selection, "inspect_paper", lambda _: {"status": "complete", "ready_to_use": True})
    return root, state, children, saved


def test_default_order_and_explicit_item_order_capture_versions_once(group, tmp_path):
    root, _, _, saved = group
    assert selection.start_group_paper(root, out=tmp_path / "out", paper_dir=tmp_path / "paper")["status"] == "complete"
    assert [Path(item["project"]).name for item in saved[0][0]["items"]] == ["project-A", "project-B"]
    assert all(item["expected_version"] == _REGISTERED_VERSION for item in saved[0][0]["items"])
    assert [item["label"] for item in saved[0][0]["items"]] == ["P0_3_0_7_log", "P0_5_0_5_linear"]
    selection.start_group_paper(root, out=tmp_path / "out2", paper_dir=tmp_path / "paper2", item_ids=["B", "A"])
    assert [Path(item["project"]).name for item in saved[-1][0]["items"]] == ["project-B", "project-A"]
    assert [item["label"] for item in saved[-1][0]["items"]] == ["P0_5_0_5_linear", "P0_3_0_7_log"]
    with pytest.raises(TaskControlError, match="distinct existing group item IDs"):
        selection.start_group_paper(root, out=tmp_path / "out3", paper_dir=tmp_path / "paper3", item_ids=[])
    assert len(saved) == 2


@pytest.mark.parametrize("change", ["not_finished", "pending_child", "duplicate", "unknown"])
def test_incomplete_or_ambiguous_selection_never_reaches_paper(group, tmp_path, change):
    root, state, children, saved = group
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
    root, _, _, saved = group
    paper = tmp_path / "paper"
    paper.mkdir()
    out = tmp_path / "out"
    origin = {"kind": "current_group_selection", "group": str(root), "item_ids": None, "title": None, "out": str(out)}
    monkeypatch.setattr(selection, "_load", lambda _: {"selection_origin": {"request": origin}})
    monkeypatch.setattr(selection, "_inspect", lambda *_: {"status": "blocked", "recorded_status": "complete"})
    monkeypatch.setattr(selection, "load_group", lambda *_: pytest.fail("Retry must not recapture changed group"))
    assert selection.start_group_paper(root, out=out, paper_dir=paper)["recorded_status"] == "complete"
    assert not saved
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
    root, _, _, _ = group
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    selection.start_group_paper(root, out=tmp_path / 'out', paper_dir=tmp_path / 'paper')
    assert before == {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert not (root.parent / '.sciplot_session_locks').exists()


def test_group_change_during_capture_blocks_before_start(group, tmp_path, monkeypatch):
    root, _, _, saved = group
    monkeypatch.setattr(selection, "start_paper", paper.start_paper)
    monkeypatch.setattr(paper, "_validate_locations", lambda *_: None)
    monkeypatch.setattr(paper, "capture_publication", lambda *_: pytest.fail("A changed group cannot capture publication"))

    checkpoint, out = tmp_path / "paper", tmp_path / "out"
    for key in _REGISTERED_VERSION:
        monkeypatch.setattr(paper, "capture_selection", lambda project, figure_id, key=key: {
            "project": str(project), "figure_id": figure_id, "version": {**_REGISTERED_VERSION, key: "c" * 64},
        })
        with pytest.raises(TaskControlError) as changed:
            selection.start_group_paper(root, out=out, paper_dir=checkpoint)
        assert changed.value.reason_code == "paper_selection_changed"
        assert not checkpoint.exists() and not out.exists()

    def concurrent_change(project, figure_id):
        value = json.loads((root / "group.json").read_text())
        value["request"]["title"] = "concurrent external revision"
        (root / "group.json").write_text(json.dumps(value))
        return {"project": str(project), "figure_id": figure_id}

    monkeypatch.setattr(paper, "capture_selection", concurrent_change)
    with pytest.raises(ValueError, match="paper current group selection changed"):
        selection.start_group_paper(root, out=out, paper_dir=checkpoint)
    assert not saved and not checkpoint.exists() and not out.exists()


def test_only_multi_figure_projects_add_titles_or_necessary_stable_identity(group, tmp_path, monkeypatch):
    root, _, _, saved = group
    figures = [{"figure_id": "internal-A", "title": "Observed curve", "status": "ready", **_REGISTERED_VERSION},
               {"figure_id": "internal-B", "title": "Reference", "status": "ready", **_REGISTERED_VERSION}]
    monkeypatch.setattr(selection, "observe_legacy_project",
                        lambda _: SimpleNamespace(figures=figures, require_current=lambda: None))
    selection.start_group_paper(root, out=tmp_path / "out", paper_dir=tmp_path / "paper", item_ids=["A"])
    assert [item["label"] for item in saved[-1][0]["items"]] == ["P0_3_0_7_log_Observed_curve", "P0_3_0_7_log_Reference"]
    figures[1]["title"] = "Observed curve"
    selection.start_group_paper(root, out=tmp_path / "out2", paper_dir=tmp_path / "paper2", item_ids=["A"])
    assert [item["label"] for item in saved[-1][0]["items"]] == ["P0_3_0_7_log_internal-A", "P0_3_0_7_log_internal-B"]
    refs = [["B", "internal-B"], ["A", "internal-A"], ["B", "internal-A"]]
    selection.start_group_paper(root, out=tmp_path / "out3", paper_dir=tmp_path / "paper3", figure_refs=refs)
    assert [(Path(item["project"]).name, item["figure_id"]) for item in saved[-1][0]["items"]] == [
        ("project-B", "internal-B"), ("project-A", "internal-A"), ("project-B", "internal-A")]
    assert saved[-1][1]["selection_origin"]["request"]["figure_refs"] == refs
    with pytest.raises(TaskControlError, match="distinct item/figure pairs") as duplicate:
        selection.start_group_paper(root, out=tmp_path / "out4", paper_dir=tmp_path / "paper4", figure_refs=[refs[0]] * 2)
    assert duplicate.value.reason_code == "paper_group_figures_invalid"




def test_first_group_completion_returns_fresh_owner_result_and_never_promotes_blocked(group, tmp_path, monkeypatch):
    root, _, _, _ = group
    checked = []
    current = {"status": "blocked", "recorded_status": "complete", "ready_to_use": False,
               "readiness_evaluated": True, "delivery_current": False,
               "readiness_scope": "Frozen package and selected source byte identities; no fresh native audit.",
               "blocker": {"reason_code": "paper_delivery_changed"}}
    monkeypatch.setattr(selection, "inspect_paper", lambda path: checked.append(path) or current)
    result = selection.start_group_paper(root, out=tmp_path / "out", paper_dir=tmp_path / "paper")
    assert result is current and result["ready_to_use"] is False
    assert checked == [tmp_path / "paper"]
    healthy = {"status": "complete", "recorded_status": "complete", "ready_to_use": True,
               "source_versions_current": True, "delivery_current": True, "readiness_evaluated": True,
               "readiness_scope": current["readiness_scope"]}
    monkeypatch.setattr(selection, "inspect_paper", lambda path: checked.append(path) or healthy)
    assert selection.start_group_paper(root, out=tmp_path / "healthy-out", paper_dir=tmp_path / "healthy-paper") is healthy
    source_drift = {**current, "delivery_current": True, "source_versions_current": False,
                    "blocker": {"reason_code": "paper_selection_changed"}}
    monkeypatch.setattr(selection, "inspect_paper", lambda path: source_drift)
    assert selection.start_group_paper(root, out=tmp_path / "source-out", paper_dir=tmp_path / "source-paper") is source_drift
    monkeypatch.setattr(selection, "start_paper", lambda *_, **__: {"status": "blocked", "blocker": {"reason_code": "paper_publication_changed"}})
    monkeypatch.setattr(selection, "inspect_paper", lambda *_: pytest.fail("An incomplete publication cannot acquire current delivery readiness"))
    assert selection.start_group_paper(root, out=tmp_path / "out2", paper_dir=tmp_path / "paper2")["status"] == "blocked"


def _saved_handle(child):
    handle = {"plot": child["project"], "plot_id": "plot:sealed", "plot_type": "ManagedPlot", "revision": 0}
    child["result"] = {"plot_objects": [handle]}
    return handle


def test_mixed_authority_lists_exact_members_before_any_publisher(group, tmp_path, monkeypatch):
    root, _, children, saved = group
    first = next(iter(children.values()))
    handle = _saved_handle(first)
    monkeypatch.setattr(selection, "start_managed_group_paper", lambda *a, **k: pytest.fail("Mixed selection cannot package"))
    monkeypatch.setattr(selection, "observe_plot_head", lambda *_: pytest.fail("Mixed selection cannot dispatch Managed reads"))
    paper, out = tmp_path / "paper", tmp_path / "out"
    with pytest.raises(TaskControlError) as broken:
        selection.start_group_paper(root, out=out, paper_dir=paper)
    assert broken.value.reason_code == "paper_group_mixed_authority"
    assert [item["authority"] for item in broken.value.repair["items"]] == ["ManagedPlot", "LegacyPlot"]
    assert broken.value.repair["items"][0]["plot"] == handle["plot"]
    assert not saved and not paper.exists() and not out.exists()


def test_managed_path_alias_cannot_duplicate_saved_figure(group, tmp_path, monkeypatch):
    from sciplot_core.plot_engine.errors import EngineError

    root, _, children, saved = group
    first, second = children.values()
    handle = _saved_handle(first)
    _saved_handle(second)["plot"] = str(Path(handle["plot"]).parent / "alias" / ".." / Path(handle["plot"]).name)
    monkeypatch.setattr(selection, "observe_plot_head", lambda _: {"document": {**handle, "revision": 2}})
    paper, out = tmp_path / "paper", tmp_path / "out"
    with pytest.raises(EngineError) as broken:
        selection.start_group_paper(root, out=out, paper_dir=paper)
    assert broken.value.reason_code == "managed_delivery_duplicate_plot"
    assert not saved and not paper.exists() and not out.exists()
