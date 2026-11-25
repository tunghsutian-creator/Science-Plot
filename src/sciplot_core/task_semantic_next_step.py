"""Pure projection of existing semantic owner continuation contracts."""
from typing import Any


def selected_repair(state: dict[str, Any], code: str) -> dict[str, Any]:
    plot = state["project"]
    step = {"action": "resolve_current_evidence", "task": state["task_dir"], "reason_code": code,
            "inspect_cli_argv": ["sciplot", "plot", "describe", plot, "--scope", "summary", "--json"]}
    if code in {"figure_handoff_destination_exists", "figure_handoff_install_changed"}:
        result = state["result"]
        argv = ["sciplot", "plot", "export", plot, "--output-dir", "NEW_OUTPUT_DIR",
                "--plot-id", result["plot_id"], "--revision", str(result["revision"])]
        if "tiff_300" in state["request"]["formats"]:
            argv.append("--tiff")
        step.update(action="export_selected_files", cli_argv=[*argv, "--json"],
                    message="The project is saved. Choose a new output directory for this revision; the old destination is not replaced.")
    elif code == "task_execution_failed" and state["status"] != "complete":
        step.update(action="retry_same_task", response_template={"retry": True},
                    cli_argv=["sciplot", "task", "resume", state["task_dir"], "--retry", "--json"],
                    message="After resolving the cause, resume the same saved figure handoff. It will not recreate the plot or replace an existing directory.")
    else:
        step["message"] = ("The project and any old delivery are preserved. Inspect the saved plot; once the intended revision has a current audited "
                           "publication, use plot export with its current ID, revision and a new output directory.")
    return step


def blocked_next_step(state: dict[str, Any]) -> dict[str, Any]:
    """Retain the Managed owner's corrective action; never turn an unknown failure into retry."""
    blocker = state.get("blocker") or {}
    if "formats" in state["request"] and state["phase"] == "delivering" and state.get("project"):
        return selected_repair(state, str(blocker.get("reason_code")))
    owner = blocker.get("owner_next_step") or {}
    repair = blocker.get("repair") or {}
    action = owner.get("action") or repair.get("action") or blocker.get("recovery_action") or "inspect_diagnostic"
    if not state["request"].get("choose_columns") and not state.get("project") and not state.get("managed_request") and (repair.get("draft_correction") or {}).get("action") == "revise_intent":
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
    if (not state["request"].get("choose_columns") and not state.get("project") and not state.get("managed_request")
            and not state.get("creation_attempts") and state.get("phase") not in {"creating", "exporting", "finished"}):
        step["draft_revision_template"] = {"expected_intent_revision": state["intent_revision"],
                                            "revise_intent": state["request"]["intent"]}
    return step
