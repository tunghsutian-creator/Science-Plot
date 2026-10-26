"""Native display operations live in the existing suite preview lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
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


def pending_operation(context: dict[str, Any]) -> dict[str, Any] | None:
    matches = []
    migrated = set()
    workspace = Path(context["workspace"])
    if (workspace / ".sciplot_store/head.json").exists():
        from sciplot_core.project_store import FileProjectStore
        for record in FileProjectStore(workspace, locations={"delivery": Path(context["delivery"])}).commands():
            migrated.add(record.get("review", {}).get("legacy_operation"))
            metadata = record.get("metadata", {}).get("request", {})
            if (metadata.get("adapter") == "native_display" and metadata.get("figure_id") == context["figure_id"]
                    and record["phase"] not in {"complete", "rejected"}):
                matches.append({"request": metadata["request"], "phase": record["phase"]})
    for path in operation_paths(context):
        if str(path) in migrated:
            continue
        legacy = read_operation(path)
        if (legacy is not None and legacy["plot"] == context["plot"]
                and legacy["phase"] not in {"complete", "rejected"}):
            matches.append(legacy)
    if len(matches) > 1:
        raise ValueError("Multiple pending native display operations; preserve and inspect.")
    return matches[0] if matches else None


def require_idle(context: dict[str, Any]) -> None:
    record = pending_operation(context)
    if record:
        raise EngineError("document_pending_edit", "Resume or reject the existing native display operation first.",
            action="plot.resume", request={key: record["request"][key]
                for key in ("plot_id", "base_revision", "idempotency_key")})


def recorded_decision(context: dict[str, Any], record: dict[str, Any], path: Path) -> bool | None:
    """Use Managed's accepted flag; retain truthful older native outcomes."""
    if "accepted" in record:
        if type(record["accepted"]) is not bool:
            raise ValueError("Invalid saved native decision; preserve and inspect.")
        accepted: bool = record["accepted"]
        if ((accepted and record["phase"] not in {"prepared", "needs_review", "complete"})
                or (not accepted and record["phase"] != "rejected")):
            raise ValueError("Saved native decision and phase disagree; preserve and inspect.")
        return accepted
    if record["phase"] in {"complete", "rejected"}:
        return bool(record["phase"] == "complete")
    directory = path.parent
    applied_path = directory / "applied.json"
    intent_directory = directory / "publication_intents"
    reject_symlink_path(applied_path)
    reject_symlink_path(intent_directory)
    intents = list(intent_directory.glob("*.json"))
    if not applied_path.exists() and not intents:
        return None
    # Older native records saved no explicit decision, but entering this
    # publication owner already required accept=True. Bind its evidence before
    # preventing a contradictory rejection or resuming the accepted work.
    preview_path = directory / "preview.json"
    reject_symlink_path(preview_path)
    seal_path = directory / "preview.sha256"
    reject_symlink_path(seal_path)
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    if (record.get("preview") != str(preview_path) or canonical_json_sha256(preview) != seal_path.read_text(encoding="ascii")
            or preview.get("workspace") != context["workspace"] or preview.get("delivery") != context["delivery"]
            or len(preview.get("candidates", [])) != 1 or preview["candidates"][0]["id"] != context["figure_id"]):
        raise ValueError("Legacy native publication decision evidence changed; preserve and inspect.")
    expected_sha = preview["candidates"][0]["export"]["document_sha256"]
    if applied_path.exists():
        evidence = json.loads(applied_path.read_text(encoding="utf-8"))
        if _bound_publication(evidence, context, expected_sha):
            return True
    for intent_path in intents:
        reject_symlink_path(intent_path)
        seal = intent_path.with_suffix(".sha256")
        reject_symlink_path(seal)
        if not seal.is_file():
            continue
        evidence = json.loads(intent_path.read_text(encoding="utf-8"))
        if (evidence.get("kind") == "sciplot_rheology_publication_intent" and evidence.get("version") == 1
                and evidence.get("preview_sha256") == canonical_json_sha256(preview)
                and canonical_json_sha256(evidence) == seal.read_text(encoding="ascii")
                and _bound_publication(evidence, context, expected_sha)):
            return True
    raise ValueError("Legacy native publication has uncertain decision evidence; preserve and inspect.")


def _bound_publication(evidence: dict[str, Any], context: dict[str, Any], expected_sha: str) -> bool:
    if (not isinstance(evidence, dict) or not isinstance(evidence.get("published_files"), dict)
            or not isinstance(evidence.get("result"), dict)):
        return False
    result = evidence.get("result", {})
    return bool(evidence.get("published_files", {}).get(context["plot"]) == expected_sha
            and result.get("workspace") == context["workspace"] and result.get("delivery") == context["delivery"]
            and result.get("status") == "ready")


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
            "request": {key: record["request"][key] for key in ("plot_id", "base_revision", "idempotency_key")}})
        if record.get("accepted") is not True:
            result["discard_request"] = {"decision_id": record["decision_id"],
                "base_revision": record["request"]["base_revision"], "accept": False}
        if record.get("error"):
            result["error"] = record["error"]
    if "accepted" in record:
        result["accepted"] = record["accepted"]
    return result
