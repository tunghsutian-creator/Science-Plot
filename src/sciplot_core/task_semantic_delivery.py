"""Finish semantic tasks through the existing sealed native-snapshot delivery owner."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.task_output_choice import creation_output
from sciplot_core.task_storage import save_task


def delivery_request(state: dict[str, Any]) -> dict[str, Any]:
    source = Path(state["request"]["sources"][0])
    layout = resolve_user_output_layout(source, requested_delivery_root=creation_output(state))
    out = layout.delivery_root
    result = state["result"]
    wire = state["managed_request"]
    # Older completed task attempts already placed their original artifacts in
    # the requested visible directory. Preserve those frozen paths and select a
    # distinct sibling for native packaging, whose owner rejects any overlap.
    artifacts = Path(wire.get("out", source.parent / (source.stem + "_SciPlot") / result["plot_id"].replace(":", "_")))
    if out == artifacts or out in artifacts.parents or artifacts in out.parents:
        out = out.with_name(out.name + "_delivery")
        state.setdefault("automatic_corrections", []).append({"field": "/delivery/out",
            "action": "separate_legacy_task_artifacts", "value": str(out),
            "message": "The frozen prior task already owns artifacts at the original out; the final native snapshot uses this distinct new sibling without moving or replacing them."})
    return {"idempotency_key": "task-delivery:" + canonical_json_sha256([state["task_dir"], state["intent_revision"]]),
            "out": str(out), "title": "Scientific figure", "mode": "native_snapshot",
            "items": [{"plot": result["plot"], "plot_id": result["plot_id"], "revision": result["revision"], "label": "Figure 1"}]}


def execute_delivery(request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.plot_protocol.socket_client import call

    return call("plot.deliver", {"request": request})


def finish_delivery(root: Path, state: dict[str, Any]) -> None:
    if "delivery_request" not in state:
        state["delivery_request"] = delivery_request(state)
    state.update(status="running", phase="delivering")
    state.pop("blocker", None)
    # Publication request identity and the phase are durable before dispatch.
    # The existing delivery checkpoint owns partial work and never redraws.
    save_task(root, state)
    delivery = execute_delivery(state["delivery_request"])
    state["delivery_result"] = delivery
    complete = delivery.get("status") == "complete" and delivery.get("ready_to_use") is True
    state.update(status="complete" if complete else "blocked", phase="finished" if complete else "delivering")
    if not complete:
        blocker: dict[str, Any] = delivery.get("blocker") or next((item["error"] for item in delivery.get("items", []) if item.get("error")), {})
        state["blocker"] = {"reason_code": blocker.get("reason_code", "managed_delivery_pending"),
                            "message": blocker.get("message", "The native snapshot/data delivery is not complete."),
                            "owner_next_step": deepcopy(delivery.get("next_step", {})),
                            "recovery_action": (delivery.get("next_step") or {}).get("action", "inspect_diagnostic"),
                            "diagnostic": {"checkpoint": delivery.get("checkpoint"), "items": delivery.get("items", [])}}
    save_task(root, state)


def delivery_current(state: dict[str, Any]) -> bool:
    from sciplot_core.plot_engine.managed_delivery_continuation import delivery_inventory
    from sciplot_core.plot_engine.storage import digest, read

    result = state.get("delivery_result") or {}
    request = state.get("delivery_request")
    if result.get("status") != "complete" or result.get("ready_to_use") is not True or not request:
        return False
    try:
        record = read(Path(result["checkpoint"]) / "delivery.json")
        sealed = record.get("state_sha256") == digest({key: value for key, value in record.items() if key != "state_sha256"})
        return bool(sealed and record.get("request") == request and record.get("status") == "complete"
                    and record.get("delivery_files") and delivery_inventory(Path(request["out"])) == record["delivery_files"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def handoff_paths(state: dict[str, Any]) -> dict[str, Any]:
    """Project only paths from the current sealed owner index; never walk arbitrary files."""
    from sciplot_core.plot_engine.storage import read

    out = Path(state["delivery_request"]["out"])
    manifest = read(out / "index.json")
    return {"images": [str(out / item["files"]["tiff_300"]) for item in manifest["items"]],
            "files": [{key: str(out / value) for key, value in item["files"].items()} for item in manifest["items"]],
            "plotting_data": [str(out / dataset["path"]) for item in manifest["items"] for dataset in item["plotted_data"]["datasets"]]}
