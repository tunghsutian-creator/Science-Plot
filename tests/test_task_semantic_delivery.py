"""Final task delivery reuses the sealed native-snapshot owner without recreating science."""
from pathlib import Path

from sciplot_core.task_control import start_task, resume_task
from sciplot_core import task_semantic_creation as semantic, task_semantic_delivery as delivery
from sciplot_core.task_storage import task_summary


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
