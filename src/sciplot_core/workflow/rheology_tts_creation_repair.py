"""Project prepared-creation failures without replacing their original exception."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

class PreparedCreationBlocked(FileExistsError):
    def __init__(self, message: str, reason: str, request: Path, workspace: Path, action: str) -> None:
        super().__init__(message)
        self.reason_code = reason
        self.repair = {"action": action, "request": str(request), "workspace": str(workspace),
                       "checkpoint": str(workspace / "creation_checkpoint.json")}


def _blocked(message: str, reason: str, request: Path, workspace: Path,
             action: str = "inspect_creation_evidence") -> PreparedCreationBlocked:
    return PreparedCreationBlocked(message, reason, request, workspace, action)


def attach_creation_repair(exc: Exception, request: Path, workspace: Path, *,
                           check: Callable[[], object] | None = None) -> None:
    """Only inspect shared continuation guards while the caller owns its lease."""
    if (workspace / ".sciplot_store/head.json").is_file():
        # New generations own recovery. Historical checkpoint files are never
        # written or used to restart an unknown shared native command.
        import json
        from sciplot_core.project_store import FileProjectStore
        repair = {"action": "inspect_project_command", "request": str(request), "workspace": str(workspace),
                  "repository": str(workspace / ".sciplot_store"),
                  "next_step": "Preserve the command's exact native outcome and sealed candidates; unknown native work must not run again."}
        try:
            payload = json.loads(request.read_bytes())
            store = FileProjectStore(workspace, locations={"delivery": Path(payload["out"]).expanduser().resolve()})
            parents = [item for item in store.commands() if item.get("metadata", {}).get("request", {}).get("adapter") == "prepared_native_suite"
                       and item["metadata"]["request"].get("request") == payload]
            if len(parents) == 1:
                parent = parents[0]
                repair.update(command_id=parent["command_id"], phase=parent["phase"])
                if parent["phase"] in {"complete", "accepted"}:
                    repair.update(action="resume_prepared_creation",
                                  next_step="Resume the same request to publish its already sealed native candidate without native reexecution.",
                                  command=["rheology", "plot", "--request", str(request), "--resume", "--json"])
        except (KeyError, ValueError, OSError):
            pass
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
