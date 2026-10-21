"""Public adapters retain exact selections and use the existing domain owners."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from sciplot_core.cli.dispatch import tasks
from sciplot_core.cli.parsers import build_parser
from sciplot_core.mcp_server import server, services
from sciplot_core.task_capabilities import task_capabilities
from sciplot_core.task_contract import TaskControlError


def test_common_edit_cli_preserves_closed_intent_and_stable_replay_entry(monkeypatch, capsys):
    from sciplot_core.cli.dispatch import common_edits

    calls = []
    monkeypatch.setattr(common_edits, "edit_task", lambda target, **kwargs: calls.append((target, kwargs)) or {"status": "needs_review"})
    intent = "换配色 tol_bright；统一字号 9pt；图例字号 7pt"
    args = build_parser().parse_args(["task", "edit", "/original project", "--intent", intent,
                                    "--figure", "secondary", "--task-dir", "/stable edit", "--json"])
    assert tasks.dispatch_task(args) == 0
    target, options = calls[0]
    assert target == Path("/original project")
    assert options == {"intent": intent, "palette": None, "font_size": None, "font_family": None,
                       "legend_font_size": None, "legend_visible": None, "legend_position": None,
                       "legend_columns": None, "series_labels": None, "series_visibility": None,
                       "figure_id": "secondary", "task_dir": Path("/stable edit")}
    assert json.loads(capsys.readouterr().out)["status"] == "needs_review"


@pytest.mark.parametrize("bounded", [False, True])
def test_find_cli_retains_original_discovery_and_explicit_search_scope(monkeypatch, capsys, bounded):
    from sciplot_core import task_saved_work

    calls = []
    monkeypatch.setattr(tasks, "find_tasks", lambda source, **kw: calls.append(("old", source, kw)) or {"status": "ok"})
    monkeypatch.setattr(task_saved_work, "find_saved_work", lambda source, **kw: calls.append(("bounded", source, kw)) or {"status": "ok"})
    argv = ["task", "find", "/renamed.csv", "--tasks-root", "/tasks", "--limit", "3", "--json"]
    if bounded:
        argv += ["--search-root", "/explicit-one", "--search-root", "/explicit-two"]
    assert tasks.dispatch_task(build_parser().parse_args(argv)) == 0
    expected = {"tasks_root": Path("/tasks"), "limit": 3}
    if bounded:
        expected["search_roots"] = [Path("/explicit-one"), Path("/explicit-two")]
    assert calls == [("bounded" if bounded else "old", Path("/renamed.csv"), expected)]
    assert json.loads(capsys.readouterr().out) == {"status": "ok"}


def test_continue_cli_keeps_explicit_copy_and_figure_selection(monkeypatch):
    from sciplot_core import task_saved_work

    calls = []
    monkeypatch.setattr(task_saved_work, "continue_saved_work", lambda source, **kw: calls.append((source, kw)) or {"status": "blocked"})
    args = build_parser().parse_args(["task", "continue", "/renamed.csv", "--search-root", "/projects",
                                    "--target", "/selected copy", "--figure", "secondary", "--json"])
    assert tasks.dispatch_task(args) == 1
    assert calls == [(Path("/renamed.csv"), {"search_roots": [Path("/projects")], "tasks_root": None,
                                          "target": Path("/selected copy"), "figure_id": "secondary"})]


@pytest.mark.parametrize("action", ["inspect", "resume"])
def test_paper_cli_preserves_exact_execution_path_and_blocked_currentness(monkeypatch, action):
    from sciplot_core import task_papers

    calls = []
    monkeypatch.setattr(task_papers, action + "_paper", lambda target: calls.append(target) or {"status": "blocked"})
    args = build_parser().parse_args(["task", "paper", action, "/frozen paper", "--json"])
    assert tasks.dispatch_task(args) == 1 and calls == [Path("/frozen paper")]


def test_paper_start_resolves_request_relative_paths_in_domain_owner(tmp_path, monkeypatch):
    from sciplot_core import task_papers

    request = {"version": 1, "out": "relative delivery", "items": []}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    calls = []
    monkeypatch.setattr(task_papers, "start_paper", lambda value, **kw: calls.append((value, kw)) or {"status": "complete"})
    args = build_parser().parse_args(["task", "paper", "start", "--request", str(path), "--paper-dir", "/stable paper", "--json"])
    assert tasks.dispatch_task(args) == 0
    assert calls == [(request, {"paper_dir": Path("/stable paper"), "base_dir": tmp_path})]


@pytest.mark.parametrize("section", ["common_edit", "paper_request"])
def test_new_capabilities_are_bound_to_same_contract_and_reject_stale_reads(section):
    index = task_capabilities()
    assert section in index["sections"]
    result = task_capabilities(section=section, expected_contract_sha256=index["contract_sha256"])
    assert result["schema"]["additionalProperties"] is False
    with pytest.raises(TaskControlError, match="能力定义已变化"):
        task_capabilities(section=section, expected_contract_sha256="0" * 64)


@pytest.mark.parametrize("name,args,module,method,expected", [
    ("sciplot_task_edit", {"target": "/original", "font_size": "9pt", "task_dir": "/entry"},
     "task_common_edits", "edit_task", {"target": Path("/original"), "font_size": "9pt", "task_dir": Path("/entry")}),
    ("sciplot_paper_start", {"request": {"version": 1}, "paper_dir": "/entry"},
     "task_papers", "start_paper", {"request": {"version": 1}, "paper_dir": Path("/entry")}),
])
def test_mcp_services_use_same_owner_with_exact_paths(monkeypatch, name, args, module, method, expected):
    import importlib

    calls = []
    def invoke(*pos, **kw):
        if pos:
            kw["request"] = pos[0]
        calls.append(kw)
        return {"status": "complete"}
    monkeypatch.setattr(importlib.import_module("sciplot_core." + module), method, invoke)
    assert services.invoke_owner(name, args) == {"status": "complete"}
    assert calls == [expected]


@pytest.mark.parametrize("name,args", [
    ("sciplot_task_edit", {"target": "/original", "python": "arbitrary"}),
    ("sciplot_task_continue", {"source": "/original.csv", "search_roots": ["/folder"] * 21}),
    ("sciplot_paper_start", {"request": {"version": 1, "out": "/delivery", "items": []}, "paper_dir": "/entry"}),
    ("sciplot_paper_resume", {"paper": "/entry", "replace_existing": True}),
])
def test_mcp_invalid_product_input_never_reaches_owner(monkeypatch, name, args):
    monkeypatch.setattr(server, "invoke_owner", lambda *_: pytest.fail("invalid product input reached owner"))
    async def scenario():
        response = await server.Adapter().call(name, args)
        assert response.is_error
        assert response.structured_content["error"]["code"] == "invalid_arguments"
    anyio.run(scenario)
