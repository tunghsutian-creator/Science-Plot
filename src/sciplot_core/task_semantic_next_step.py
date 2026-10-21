"""Pure projection of existing semantic owner continuation contracts."""
from typing import Any


def blocked_next_step(state: dict[str, Any]) -> dict[str, Any]:
    """Retain the Managed owner's corrective action; never turn an unknown failure into retry."""
    blocker = state.get("blocker") or {}
    owner = blocker.get("owner_next_step") or {}
    repair = blocker.get("repair") or {}
    action = owner.get("action") or repair.get("action") or blocker.get("recovery_action") or "inspect_diagnostic"
    if not state.get("project") and not state.get("managed_request") and (repair.get("draft_correction") or {}).get("action") == "revise_intent":
        action = "revise_intent"
    step: dict[str, Any] = {"action": action, "task": state["task_dir"], "reason_code": blocker.get("reason_code"),
                            "owner_next_step": owner, "diagnostic": blocker.get("diagnostic", repair),
                            "message": "Follow the actual owner diagnosis. Unknown or scientific/layout failures are not retryable merely because export failed; preserve this task and all prior evidence."}
    if action in {"retry_same_request", "retry_export", "plot.export", "retry_same_task", "release_project_then_retry"}:
        step.update(action="retry_same_task", response_template={"retry": True},
                    cli_argv=["sciplot", "task", "resume", state["task_dir"], "--retry", "--json"])
    elif state.get("project"):
        step["inspect_cli_argv"] = ["sciplot", "plot", "describe", state["project"], "--scope", "summary", "--json"]
        if action == "correct_layout":
            step["layout_contract_cli_argv"] = ["sciplot", "plot", "describe", state["project"], "--scope", "edit",
                                                "--target-id", "figure:main", "--property", "layout", "--json"]
    if not state.get("project") and not state.get("managed_request") and not state.get("creation_attempts") and state.get("phase") not in {"creating", "exporting", "finished"}:
        step["draft_revision_template"] = {"expected_intent_revision": state["intent_revision"],
                                            "revise_intent": state["request"]["intent"]}
    return step
