"""Final task delivery reuses the sealed native-snapshot owner without recreating science."""
from pathlib import Path

import pytest

from sciplot_core.task_control import start_task, resume_task, inspect_task
from sciplot_core import task_semantic_creation as semantic, task_semantic_delivery as delivery
from sciplot_core.task_storage import load_task, task_summary


def _timed_semantic_backend(tmp_path, monkeypatch, *, decisions, fail_delivery=False):
    """Account for known owner work without native runtime or wall-clock sleeps."""
    from sciplot_core import task_timing
    from sciplot_core.plot_protocol import socket_client

    now, calls = [0.0], {"create": 0, "delivery": 0, "describe": 0}
    monkeypatch.setattr(task_timing, "perf_counter", lambda: now[0])
    def work(seconds):
        now[0] += seconds
    def plan(paths, intent):
        work(2)
        return {"sources": [], "decisions": decisions}
    def build(state):
        work(3)
        return {"idempotency_key": "timed-attempt", "out": str(tmp_path / ".sciplot" / "artifacts")}
    identity = {"revision": 0, "scientific_hash": "science", "presentation_hash": "presentation"}
    def create(state, wire):
        calls["create"] += 1
        work(5)
        return {"status": "complete", "ready_to_use": True, "plot": str(tmp_path / "managed"),
                "plot_id": "plot:timed", "exports": [{"path": "/sealed/figure.pdf"}], **identity}
    def package(wire):
        calls["delivery"] += 1
        work(7)
        if fail_delivery and calls["delivery"] == 1:
            return {"status": "partial", "ready_to_use": False,
                    "next_step": {"action": "retry_same_request"}}
        return {"status": "complete", "ready_to_use": True,
                "delivery": {"native_launcher": "/delivery/Open_in_Veusz.command"}}
    def describe(method, params):
        assert method == "plot.describe"
        calls["describe"] += 1
        work(11)
        return {"status": "current", "pending": None, **identity,
                "export_current": {"current": True, "byte_inventory_verified": True}}
    monkeypatch.setattr(semantic, "prepare_plan", plan)
    monkeypatch.setattr(semantic, "build_managed_request", build)
    monkeypatch.setattr(semantic, "execute_managed", create)
    monkeypatch.setattr(delivery, "execute_delivery", package)
    monkeypatch.setattr(delivery, "delivery_current", lambda state: True)
    monkeypatch.setattr(delivery, "handoff_paths", lambda state: {"images": ["/delivery/figure.tiff"]})
    monkeypatch.setattr(socket_client, "call", describe)
    source = tmp_path / "original.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n1,99\n")
    request = {"version": 1, "action": "create", "sources": [str(source)],
               "intent": {"x": {"quantity": "time"}, "y": {"quantity": "mass"}}}
    return request, work, calls


def _assert_timing_receipt(task, result, *, calls, total, last):
    saved = load_task(task)
    assert result["local_timing"] == saved["local_timing"]
    assert result["updated_at"] == saved["updated_at"]
    timing = result["local_timing"]
    assert timing["calls"] == calls
    assert timing["total_seconds"] == total
    assert timing["last_call_seconds"] == last
    assert sum(timing["last_call_phases_seconds"].values()) == last
    assert timing["external_model_seconds"] is None
    assert result["external_model_tokens"] is None


@pytest.mark.parametrize("needs_choice", [False, True], ids=["explicit-create", "question-resume"])
def test_semantic_call_timing_matches_saved_receipt_after_current_evidence(tmp_path, monkeypatch, needs_choice):
    decisions = [{"field": "time_boundary", "options": ["preserve_endpoint", "next_sample"]}] if needs_choice else []
    request, work, calls = _timed_semantic_backend(tmp_path, monkeypatch, decisions=decisions)
    task = tmp_path / "task"
    result = start_task(request, task_dir=task)
    if needs_choice:
        assert result["status"] == "needs_input"
        _assert_timing_receipt(task, result, calls=1, total=2, last=2)
        work(1000)  # Time between calls belongs to the user, not local execution.
        result = resume_task(task, {"expected_question_id": result["question"]["question_id"],
                                   "confirm_plan": True, "choices": {"time_boundary": "next_sample"}})
    assert result["status"] == "complete" and result["ready_to_use"] is True
    assert result["next_step"]["images"] == ["/delivery/figure.tiff"]
    _assert_timing_receipt(task, result, calls=2 if needs_choice else 1, total=28, last=26 if needs_choice else 28)
    assert result["local_timing"]["last_call_phases_seconds"]["checking_current_project"] == 11
    assert calls == {"create": 1, "delivery": 1, "describe": 1}


def test_semantic_delivery_retry_timing_excludes_wait_and_inspect_is_read_only(tmp_path, monkeypatch):
    request, work, calls = _timed_semantic_backend(tmp_path, monkeypatch, decisions=[], fail_delivery=True)
    task = tmp_path / "task"
    failed = start_task(request, task_dir=task)
    assert failed["status"] == "blocked" and failed["phase"] == "delivering"
    _assert_timing_receipt(task, failed, calls=1, total=17, last=17)
    work(1000)
    done = resume_task(task, {"retry": True})
    assert done["status"] == "complete" and done["ready_to_use"] is True
    _assert_timing_receipt(task, done, calls=2, total=35, last=18)
    assert calls == {"create": 1, "delivery": 2, "describe": 1}
    before = (task / "task.json").read_bytes()
    work(1000)
    inspected = inspect_task(task)
    assert inspected["local_timing"] == done["local_timing"]
    assert (task / "task.json").read_bytes() == before
    # A completed idempotent replay queries current evidence without executing
    # another attempt or changing the historical active-attempt receipt.
    replay = resume_task(task, {"retry": True})
    assert replay["ready_to_use"] is True and replay["local_timing"] == done["local_timing"]
    assert (task / "task.json").read_bytes() == before
    assert calls == {"create": 1, "delivery": 2, "describe": 3}


def test_delivery_failure_resumes_same_frozen_request_without_create_or_retransform(tmp_path, monkeypatch):
    source = tmp_path / "original.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n1,99\n")
    request = {"version": 1, "action": "create", "sources": [str(source)],
               "intent": {"x": {"quantity": "time"}, "y": {"quantity": "mass"}}}
    creates, packages = [], []
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"sources": [], "decisions": []})
    monkeypatch.setattr(semantic, "build_managed_request", lambda state: {"idempotency_key": "frozen-science", "out": str(tmp_path / ".sciplot" / "artifacts")})
    monkeypatch.setattr(semantic, "current_result", lambda state: task_summary(state))
    def create(state, wire):
        creates.append(wire)
        return {"status": "complete", "ready_to_use": True, "plot": str(tmp_path / "managed"),
                "plot_id": "plot:test", "revision": 0, "exports": [{"path": "/sealed/figure.pdf"}]}
    monkeypatch.setattr(semantic, "execute_managed", create)
    def package(wire):
        packages.append(wire)
        # The actual delivery owner supplies and guards CSV/native/launchers;
        # this isolated workflow test controls only a transient publication loss.
        if len(packages) == 1:
            return {"status": "partial", "ready_to_use": False, "checkpoint": "/checkpoint",
                    "items": [{"error": {"reason_code": "interrupted_publication", "message": "saved for retry"}}],
                    "next_step": {"action": "retry_same_request", "method": "plot.deliver"}}
        return {"status": "complete", "ready_to_use": True, "delivery": {"native_launcher": "/delivery/Open_in_Veusz.command"}}
    monkeypatch.setattr(delivery, "execute_delivery", package)
    task = tmp_path / "task"
    first = start_task(request, task_dir=task)
    assert first["status"] == "blocked" and first["phase"] == "delivering"
    assert first["next_step"]["action"] == "retry_same_task"
    assert len(creates) == len(packages) == 1
    result = resume_task(task, {"retry": True})
    assert result["status"] == "complete" and len(creates) == 1 and len(packages) == 2
    assert packages[0] == packages[1] and packages[0]["mode"] == "native_snapshot"
    assert not Path(packages[0]["out"]).is_relative_to(tmp_path / ".sciplot" / "artifacts")


def test_final_delivery_inventory_is_required_for_ready(tmp_path):
    from sciplot_core.plot_engine.storage import digest, write
    from sciplot_core.plot_engine.managed_delivery_continuation import delivery_inventory
    out, checkpoint = tmp_path / "delivery", tmp_path / "checkpoint"
    out.mkdir()
    checkpoint.mkdir()
    (out / "plotting.csv").write_text("x,y\n0,100\n")
    request = {"out": str(out), "idempotency_key": "frozen"}
    record = {"request": request, "status": "complete", "delivery_files": delivery_inventory(out)}
    write(checkpoint / "delivery.json", {**record, "state_sha256": digest(record)})
    state = {"delivery_request": request, "delivery_result": {"status": "complete", "ready_to_use": True, "checkpoint": str(checkpoint)}}
    assert delivery.delivery_current(state)
    (out / "plotting.csv").write_text("x,y\n0,101\n")
    assert not delivery.delivery_current(state)
