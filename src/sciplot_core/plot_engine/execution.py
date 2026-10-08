"""Persist stages before side effects; resume native commit and export independently."""

from pathlib import Path
from subprocess import TimeoutExpired
from collections.abc import Callable
from copy import deepcopy
import json
from typing import Any
from uuid import uuid4

from .backend import PlotBackend
from .cache_identity import build_key
from .content_store import verify_document_content
from .current import artifact_files, evidence_current, require_current
from .errors import EngineError
from .receipts import receipt
from .storage import commit, load_head, persist, write


def _retryable(exc: Exception) -> bool:
    return isinstance(exc, TimeoutExpired) or getattr(exc, "reason_code", None) in {
        "worker_timeout", "render_timeout", "export_timeout", "renderer_unavailable",
    }


def _failure(root: Path, tx: dict[str, Any], exc: Exception, stage: str) -> None:
    import traceback

    path = root / "transactions" / tx["id"] / "diagnostic.json"
    issues = getattr(exc, "issues", [])
    repair = getattr(exc, "repair", None)
    write(path, {"stage": stage, "type": type(exc).__name__, "message": str(exc),
                 "traceback": traceback.format_exc(), "issues": issues, "repair": repair})
    tx["error"] = {"reason_code": getattr(exc, "reason_code", "backend_failure"), "stage": stage,
                   "message": str(exc)[:240], "diagnostic": str(path)}
    tx["error"]["action"] = (repair.get("action", "inspect_diagnostic") if isinstance(repair, dict)
                              else "retry_same_request" if _retryable(exc) else "inspect_diagnostic")
    for key, detail in (("issues", issues), ("repair", repair)):
        if detail:
            if len(json.dumps(detail, ensure_ascii=False).encode()) <= 1024:
                tx["error"][key] = detail
            else:
                tx["error"][key + "_evidence"] = {"path": str(path), "json_pointer": "/" + key}
    field = getattr(exc, "field", None)
    if field:
        tx["error"]["field"] = str(field)[:256]
    persist(root, tx)


def _attempt(root: Path, tx: dict[str, Any], stage: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """One durable extra attempt only for explicitly known transient failures."""
    try:
        result: dict[str, Any] = operation()
        return result
    except Exception as exc:
        budget = tx.setdefault("retry_counts", {})
        if not _retryable(exc) or budget.get(stage, 0) >= 1:
            raise
        budget[stage] = budget.get(stage, 0) + 1
        persist(root, tx)
        retried: dict[str, Any] = operation()
        return retried


def _require_audit(review: dict[str, Any]) -> None:
    audit = review.get("scientific_audit")
    if not isinstance(audit, dict) or audit.get("status") != "passed":
        raise EngineError("document_scientific_audit_failed", "The native candidate lacks a passed scientific audit.",
                          action="inspect_scientific_audit")


def _require_managed_base(head: dict[str, Any], tx: dict[str, Any], backend: PlotBackend) -> None:
    """Detect edits to the active artifact until the canonical revision commits."""
    if tx["document"].get("plot_type") != "ManagedPlot" or head["transaction"] == tx["id"]:
        return
    if head["document"]["revision"] != tx["request"]["base_revision"]:
        raise EngineError("document_revision_conflict", "Another revision was committed during recovery.")
    baseline = tx.get("managed_base_binding")
    if not isinstance(baseline, dict):
        raise EngineError("managed_recovery_baseline_missing", "This interrupted managed transaction lacks its original native baseline; inspect it before resuming.",
                          action="inspect_managed_transaction")
    require_current(backend, baseline)


def advance(root: Path, tx: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    stage = tx["phase"]
    try:
        if stage == "resolving":
            from .managed_resolution import resolve_transaction

            require_current(backend, tx["binding"])
            resolve_transaction(root, tx)
            stage = tx["phase"]
        if stage == "planned":
            stage = "preview"
            require_current(backend, tx["binding"])
            if tx["diff"]:
                def preview() -> dict[str, Any]:
                    require_current(backend, tx["binding"])
                    return backend.preview(tx["before"], tx["binding"], tx["document"], tx["diff"],
                                           root / "transactions" / tx["id"] / ("preview-" + uuid4().hex))
                stage = "preview"
                tx["review"] = _attempt(root, tx, "preview", preview)
                _require_audit(tx["review"])
                tx["phase"] = "needs_review" if tx["risk"] == "review" else "prepared"
            else:
                tx["phase"] = "committed"
            tx.pop("error", None)
            persist(root, tx)
        if tx["phase"] in {"needs_review", "rejected"}:
            return receipt(root, tx)
        if tx["phase"] in {"prepared", "applying"}:
            # Legacy writes happen in place and own their recovery checks. Managed
            # candidates have a separate path, so applying cannot alter the base.
            stage = "apply"
            _require_audit(tx["review"])
            verify_document_content(root, tx["document"])
            if tx["phase"] == "prepared":
                require_current(backend, tx["binding"])
                if tx["document"].get("plot_type") == "ManagedPlot":
                    tx["managed_base_binding"] = deepcopy(tx["binding"])
            elif tx["document"].get("plot_type") == "ManagedPlot":
                _require_managed_base(load_head(root), tx, backend)
            tx["phase"] = "applying"
            persist(root, tx)
            if tx.get("mode") == "reimport":
                require_current(backend, tx["binding"])
                applied = {"status": "adopted", **tx["native_adoption"]}
            else:
                applied = backend.apply(tx["binding"], tx["review"])
                tx["binding"] = backend.refresh_binding(tx["binding"], applied)
                if tx["document"].get("plot_type") != "ManagedPlot" and "document" in tx["binding"]:
                    from .external_mutation import capture_baseline

                    tx["binding"] = capture_baseline(root, tx["binding"])
            tx["native_result"] = applied
            tx["phase"] = "native_applied"
            persist(root, tx)
        if tx["phase"] == "native_applied":
            stage = "commit"
            require_current(backend, tx["binding"])
            head = load_head(root)
            _require_managed_base(head, tx, backend)
            if head["document"]["revision"] != tx["request"]["base_revision"] and head["transaction"] != tx["id"]:
                raise EngineError("document_revision_conflict", "Another revision was committed during recovery.")
            commit(root, tx["document"], tx["binding"], tx["id"])
            tx["phase"] = "committed"
            persist(root, tx)
        if tx["phase"] in {"committed", "exporting", "export_pending"}:
            stage = "export"
            require_current(backend, tx["binding"])
            tx["phase"] = "exporting"
            persist(root, tx)
            exported = _attempt(root, tx, "export", lambda: backend.export(tx["binding"]))
            if exported.get("ready_to_use") is not True:
                raise EngineError("export_not_ready", "The export has not passed its delivery checks.", action="retry_export")
            require_current(backend, tx["binding"])
            tx["export"] = exported
            tx["artifact_files"] = {**artifact_files(exported), **exported.get("evidence_files", {})}
            tx["evidence_inventories"] = exported.get("evidence_inventories", {})
            if not evidence_current(tx["artifact_files"], tx["evidence_inventories"]):
                raise EngineError("export_evidence_missing", "The export lacks current, verifiable artifact evidence.",
                                  action="retry_export")
            tx["artifact_build_key"] = build_key(tx["document"], tx["binding"])
            tx["phase"] = "complete"
            tx.pop("error", None)
            persist(root, tx)
            write(root / "export-cache.json", {"build_key": tx["artifact_build_key"],
                  "export": exported, "artifact_files": tx["artifact_files"],
                  "evidence_inventories": tx["evidence_inventories"]})
        return receipt(root, tx)
    except Exception as exc:
        if stage == "export":
            tx["phase"] = "export_pending"
        _failure(root, tx, exc, stage)
        return receipt(root, tx)


def replay(root: Path, tx: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    if tx["phase"] == "complete":
        head = load_head(root)
        if head["document"]["revision"] != tx["document"]["revision"]:
            result = receipt(root, tx, replay=True)
            result.update({"ready_to_use": False, "historical": True, "current_revision": head["document"]["revision"],
                           "exports": [], "next_step": {"action": "plot.describe"}})
            return result
        require_current(backend, tx["binding"])
        if (tx.get("artifact_build_key") == build_key(tx["document"], tx["binding"])
                and evidence_current(tx.get("artifact_files", {}), tx.get("evidence_inventories"))):
            return receipt(root, tx, replay=True)
        # Missing output does not invalidate the committed semantic mutation.
        tx["phase"] = "export_pending"
        persist(root, tx)
    return advance(root, tx, backend)
