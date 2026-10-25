"""Preview and adopt source-preserving edits from one bound visible VSZ."""

from __future__ import annotations

from sciplot_core.studio_core.project_command_scope import project_command_runtime

from pathlib import Path
from typing import Any

from sciplot_core.studio_core.native_scientific_audit import audit_native_candidate as _audit_candidate
from sciplot_core.studio_core.delivery_recovery_state import (
    RecoveryBlocked,
    canonical_path,
    capture_recovery_state,
)




@project_command_runtime
def preview_delivery_recovery(
    project_dir: Path, candidate: Path | None = None, *, _stage: bool = True
) -> dict[str, Any]:
    """Read three-way hashes and audit the exact candidate; never change a project."""
    payload: dict[str, Any] = {
        "kind": "sciplot_delivery_recovery_preview",
        "version": 1,
        "status": "blocked",
        "ready_to_apply": False,
        "project": str(project_dir.expanduser().resolve()),
    }
    try:
        state = capture_recovery_state(project_dir, candidate)
        payload.update(state)
        hashes = state["hashes"]
        if hashes["document"] == hashes["candidate"] != hashes["baseline"]:
            raise RecoveryBlocked(
                "already_reconciled",
                "The managed and visible documents already match. Export the current project to refresh its delivery.",
            )
        if hashes["document"] != hashes["baseline"]:
            raise RecoveryBlocked(
                "canonical_diverged",
                "The managed document changed since delivery. Keep both documents; automatic adoption is blocked.",
            )
        if hashes["candidate"] == hashes["baseline"]:
            raise RecoveryBlocked(
                "no_visible_changes", "The visible document has no edits to recover."
            )
        payload["scientific_audit"] = _audit_candidate(
            Path(state["candidate"]), Path(state["document"]).with_name("spec.json")
        )
        if capture_recovery_state(project_dir, candidate) != state:
            raise RecoveryBlocked(
                "changed_during_preview",
                "Recovery inputs changed during the scientific audit; preview again.",
            )
        payload.update(status="ready", ready_to_apply=True)
        if _stage:
            from sciplot_core.studio_core.delivery_recovery_commands import stage_delivery_recovery

            return stage_delivery_recovery(Path(state["project"]), payload)
    except Exception as exc:
        payload.update(
            status="blocked",
            ready_to_apply=False,
            reason_code=exc.code
            if isinstance(exc, RecoveryBlocked)
            else "recovery_validation_failed",
            message=str(exc),
        )
    return payload



def apply_delivery_recovery(project_dir: Path, preview: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.studio_core.delivery_recovery_commands import decide_delivery_recovery, stage_delivery_recovery

    project = canonical_path(project_dir)
    if preview.get("version") == 2:
        return decide_delivery_recovery(project, preview)
    if not isinstance(preview.get("candidate"), str):
        raise ValueError("A complete recovery preview is required")
    current = preview_delivery_recovery(project, Path(preview["candidate"]), _stage=False)
    if current != preview or current.get("ready_to_apply") is not True:
        raise ValueError("The recovery preview is stale or modified; preview the current project again")
    return decide_delivery_recovery(project, stage_delivery_recovery(project, current))


__all__ = ["preview_delivery_recovery", "apply_delivery_recovery"]
