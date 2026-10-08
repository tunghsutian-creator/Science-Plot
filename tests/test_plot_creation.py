"""Completed creation history cannot certify stale or unknown current delivery."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.plot_engine import creation_results as creation


@pytest.mark.parametrize("with_options", [False, True])
def test_source_only_public_create_keeps_original_production_task(tmp_path, monkeypatch, with_options):
    from sciplot_core.plot_engine import creation as entry, managed_creation
    from sciplot_core.plot_engine.service import PlotService

    source = tmp_path / "FS"
    source.mkdir()
    request = {"source": str(source), "idempotency_key": "ordinary-source"}
    if with_options:
        request.update(rule_id="rheology_frequency_sweep", template="point_line",
                       profile=str(tmp_path / "explicit-profile.json"), out=str(tmp_path / "delivery"))
    calls = []
    monkeypatch.setattr(managed_creation, "create_managed", lambda *a, **k: pytest.fail("Raw data reached Managed compiler"))
    monkeypatch.setattr(entry, "start_task", lambda task_request, **k: calls.append(task_request) or {"status": "from-production"})
    monkeypatch.setattr(entry, "_result", lambda service, root, state, task: task)
    result = PlotService(backend=object()).create(request)
    assert result == {"status": "from-production"}
    assert calls == [{"version": 1, "action": "create",
                      **{key: value for key, value in request.items() if key != "idempotency_key"}}]
    assert "render_options" not in calls[0]
    assert "template_definition" not in calls[0]


class Opener:
    def __init__(self, status: str = "current") -> None:
        self.status = status
        self.calls = 0

    def open(self, target: Path, figure_id: str | None = None) -> dict[str, Any]:
        self.calls += 1
        return {"status": self.status, "plot": str(target / "document"), "plot_id": "plot",
                "revision": 0, "coverage": {"mode": "legacy_shadow"}, "objects": {}}


def task() -> dict[str, Any]:
    return {"status": "complete", "project": "/tmp/project", "result": {"studio_run": {"ready_to_use": True}},
            "current_project": {key: {"current": True} for key in ("source", "qa", "delivery")},
            "next_step": {"action": "review_exports_and_deliver"}}


@pytest.mark.parametrize("gap,value", [("source", False), ("qa", False), ("delivery", False), ("source", None)])
def test_old_complete_creation_is_blocked_before_native_import(tmp_path: Path, gap: str, value: Any) -> None:
    prior = task()
    prior["current_project"][gap]["current"] = value
    opener = Opener()
    result = creation._result(opener, tmp_path / "creation", {}, prior)
    assert result["status"] == "blocked" and result["ready_to_use"] is False
    assert result["next_step"] == {"action": "resolve_current_evidence", "evidence_gaps": [gap]}
    assert opener.calls == 0


def test_creation_reuses_current_evidence_but_checks_semantic_native_binding(tmp_path: Path) -> None:
    result = creation._result(Opener("stale"), tmp_path / "creation", {}, task())
    assert result["status"] == "blocked" and result["ready_to_use"] is False
    assert result["blocker"]["evidence_gaps"] == ["semantic_document"]
    ready = creation._result(Opener(), tmp_path / "ready", {}, task())
    assert ready["status"] == "complete" and ready["ready_to_use"] is True


def test_creation_without_current_snapshot_queries_once_before_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = deepcopy(task())
    del old["current_project"]
    reads: list[Path] = []

    def inspect(path: Path) -> dict[str, Any]:
        reads.append(path)
        current = task()
        current["current_project"]["delivery"]["current"] = False
        return current

    monkeypatch.setattr(creation, "inspect_task", inspect)
    result = creation._result(Opener(), tmp_path / "creation", {}, old)
    assert result["status"] == "blocked"
    assert reads == [tmp_path / "creation/task"]


def test_blocked_creation_reports_current_failure_without_repeating_inactive_question(tmp_path: Path) -> None:
    import json

    root = tmp_path / "creation"
    failed = {"kind": "sciplot_task", "status": "blocked", "task_dir": str(root / "task"),
              "question": {"evidence": "inactive evidence" * 5000},
              "blocker": {"reason_code": "source_changed", "message": "failure details" * 5000},
              "next_step": {"action": "resolve_source_change", "task": str(root / "task")}}
    result = creation._result(Opener(), root, {}, failed)
    assert "question" not in result
    assert result["next_step"] == {"action": "resolve_source_change"}
    assert len(json.dumps(result)) < 1500
    saved = json.loads((root / "creation.json").read_text())
    assert saved["task_result"] == failed
