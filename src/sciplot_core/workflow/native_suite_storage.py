"""Native display operations live in the existing suite preview lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.studio_core.source_update_commit import reject_symlink_path


def operation_path(context: dict[str, Any], key: str) -> Path:
    identity = canonical_json_sha256({"plot": context["plot"], "key": key})
    prefix = canonical_json_sha256(context["plot"])[:16]
    path = Path(context["workspace"]) / "style_previews" / ("display_" + prefix + "_" + identity) / "operation.json"
    reject_symlink_path(path)
    return path


def operation_paths(context: dict[str, Any]) -> list[Path]:
    directory = Path(context["workspace"]) / "style_previews"
    reject_symlink_path(directory)
    prefix = canonical_json_sha256(context["plot"])[:16]
    return list(directory.glob("display_" + prefix + "_*/operation.json"))


def read_operation(path: Path) -> dict[str, Any] | None:
    reject_symlink_path(path)
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("kind") != "sciplot_native_display_operation"
            or record.get("version") != 1):
        raise ValueError("Invalid saved native display operation; preserve its evidence.")
    return record


def save_operation(path: Path, record: dict[str, Any]) -> None:
    reject_symlink_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, record)


def pending_operation(context: dict[str, Any]) -> dict[str, Any] | None:
    matches = []
    for path in operation_paths(context):
        record = read_operation(path)
        if (record is not None and record["plot"] == context["plot"]
                and record["phase"] not in {"complete", "rejected"}):
            matches.append(record)
    if len(matches) > 1:
        raise ValueError("Multiple pending native display operations; preserve and inspect.")
    return matches[0] if matches else None


def require_idle(context: dict[str, Any]) -> None:
    record = pending_operation(context)
    if record:
        raise EngineError("document_pending_edit", "Resume or reject the existing native display operation first.",
            action="plot.resume", request={key: record["request"][key]
                for key in ("plot_id", "base_revision", "idempotency_key")})


def result_for(record: dict[str, Any], path: Path, *, replayed: bool = False) -> dict[str, Any]:
    result = {"kind": "sciplot_plot_result", "version": 1,
        "status": "needs_review" if record["phase"] == "needs_review" else record["phase"],
        "plot": record["plot"], "plot_id": record["request"]["plot_id"],
        "plot_type": "LegacyPlot", "revision": record.get("revision", record["request"]["base_revision"]),
        "revision_semantics": "content_bound", "scientific_hash": record["scientific_hash"],
        "presentation_hash": record.get("presentation_hash", record["before_native_sha256"]),
        "scientific_hash_changed": False, "effective_risk": "presentation", "replayed": replayed,
        "changed": bool(record["diff"]), "diff_count": len(record["diff"]), "diff": record["diff"],
        "commit_status": "committed" if record["phase"] == "complete" else "pending",
        "export_status": "complete" if record["phase"] == "complete" else "pending",
        "ready_to_use": record.get("ready_to_use", record["phase"] == "complete"), "evidence": str(path),
        "transform_execution": {"executed": [], "reused": []}, "scope": "single_figure"}
    if record["phase"] == "needs_review":
        result.update(decision_id=record["decision_id"], preview=record["preview_png"],
            scientific_audit={"status": "passed", "evidence": record["preview"]},
            next_step={"action": "plot.decide", "plot": record["plot"], "request": {
                "decision_id": record["decision_id"], "base_revision": record["request"]["base_revision"], "accept": True}})
    elif record["phase"] == "complete":
        result.update(exports=record.get("exports", []), next_step={"action": "deliver"})
    elif record["phase"] == "rejected":
        result["ready_to_use"] = False
        result["next_step"] = {"action": "none"}
    else:
        result.update(status="blocked", next_step={"action": "plot.resume", "plot": record["plot"],
            "request": {key: record["request"][key] for key in ("plot_id", "base_revision", "idempotency_key")}},
            discard_request={"decision_id": record["decision_id"],
                "base_revision": record["request"]["base_revision"], "accept": False})
        if record.get("error"):
            result["error"] = record["error"]
    return result
