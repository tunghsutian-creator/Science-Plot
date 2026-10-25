"""Project prepared-creation failures without replacing their original exception."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

class PreparedCreationBlocked(FileExistsError):
    def __init__(self, message: str, reason: str, request: Path, workspace: Path, action: str) -> None:
        super().__init__(message)
        self.reason_code = reason
        self.repair = {"action": action, "request": str(request), "workspace": str(workspace)}
        if (workspace / ".sciplot_store/head.json").is_file():
            self.repair["repository"] = str(workspace / ".sciplot_store")
        else:
            self.repair["checkpoint"] = str(workspace / "creation_checkpoint.json")


def _blocked(message: str, reason: str, request: Path, workspace: Path,
             action: str = "inspect_creation_evidence") -> PreparedCreationBlocked:
    return PreparedCreationBlocked(message, reason, request, workspace, action)


def attach_creation_repair(exc: Exception, request: Path, workspace: Path, *,
                           check: Callable[[], object] | None = None) -> None:
    """Only inspect shared continuation guards while the caller owns its lease."""
    existing = getattr(exc, "repair", None)
    if existing is not None and getattr(exc, "reason_code", None) != "prepared_creation_resume_required":
        return
    if (workspace / ".sciplot_store/head.json").is_file():
        repair = {"action": "inspect_creation_evidence", "request": str(request), "workspace": str(workspace),
                  "repository": str(workspace / ".sciplot_store"),
                  "next_step": "Preserve the original native outcome and sealed candidates; uncertain native work must not run again."}
        busy = "project_busy" in (getattr(exc, "reason_code", None), getattr(exc, "native_reason_code", None))
        if not busy:
            try:
                from sciplot_core.workflow.native_suite_creation_inspection import inspect_creation_continuation
                state = inspect_creation_continuation(request, workspace)
            except Exception as blocked:
                repair["blocked_by"] = str(blocked) or type(blocked).__name__
            else:
                repair.update(command_id=state["command_id"], phase=state["phase"], action="resume_prepared_creation",
                    next_step="Continue the exact saved request; completed native effects are verified read-only and never saved again.",
                    command=["rheology", "plot", "--request", str(request), "--resume", "--json"])
                if state["complete"] and getattr(exc, "reason_code", None) == "prepared_creation_resume_required":
                    repair.update(action="export_saved_suite", next_step="Export the saved suite's exact current native documents.")
                    repair.pop("command", None)
        try:
            exc.repair = repair
        except Exception:
            pass
        return
    existing = getattr(exc, "repair", None)
    if existing is not None and (getattr(exc, "reason_code", None) != "prepared_creation_resume_required"
                                 or "next_step" in existing):
        return
    repair = {"action": "inspect_creation_evidence", "request": str(request), "workspace": str(workspace),
              "checkpoint": str(workspace / "creation_checkpoint.json"),
              "next_step": "Preserve the workspace and inspect its checkpoint and original failure before retrying."}
    busy = "project_busy" in (getattr(exc, "reason_code", None), getattr(exc, "native_reason_code", None))
    if check is not None and not busy:
        try:
            check()
        except Exception as blocked:
            repair["blocked_by"] = str(blocked) or type(blocked).__name__
        else:
            repair.update(action="resume_prepared_creation",
                          next_step="Continue the same request with rheology plot --request SAME.json --resume --json.",
                          command=["rheology", "plot", "--request", str(request), "--resume", "--json"])
    try:
        exc.repair = repair
    except Exception:
        pass  # An exception with immutable attributes must retain its original identity.
