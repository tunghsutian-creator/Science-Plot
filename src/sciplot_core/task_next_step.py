"""State-specific guidance projects existing recovery and review contracts."""

from typing import Any

from sciplot_core.task_recovery_policy import recovery_action, refresh_context_argv


def task_next_step(state: dict[str, Any]) -> dict[str, Any]:
    status, phase = state["status"], state["phase"]
    task = state.get("task_dir")
    if status in {"complete", "cancelled"}:
        return {"action": "inspect_current_project", "task": task,
                "message": "Inspect current source, QA and delivery before handoff or another edit."}
    if status == "needs_input":
        question = state["question"]
        if question["field"] == "out":
            return {"action": "choose_new_output", "task": task,
                    "schema_query": {"section": "response", "name": "out"},
                    "response_template": {"expected_question_id": question["question_id"], "out": "NEW_OUTPUT_PATH"},
                    "message": "Resume this task with a new output path, or inspect the existing project. Do not move existing deliveries or send retry=true."}
        if question.get("mapping_candidates"):
            return {"action": "answer_scientific_question", "task": task,
                    "schema_query": {"section": "response", "name": "mapping_candidate_id"},
                    "response_bindings": {"expected_question_id": question["question_id"]},
                    "response_template": {"expected_question_id": question["question_id"],
                                          "mapping_candidate_id": "ID of the candidate you reviewed"},
                    "message": "Review mapping_candidates (rows, columns, samples, units and original note). Reply with mapping_candidate_id; optional pair_indices selects/orders samples. Use the full mapping response only to change the proposed regions or scientific declarations."}
        if (question["field"] in {"table_selection", "column_mapping", "rule_id"}
                and question.get("question_id") and state["request"]["action"] in {"create", "update_source"}):
            return {"action": "answer_scientific_question", "task": task,
                    "schema_query": {"section": "response", "name": "mapping"},
                    "response_bindings": {"expected_question_id": question["question_id"]},
                    "cli": "task resume TASK_DIR --response ANSWER_JSON_FILE --json",
                    "message": "Reply once with mapping: source_sha256, table_selection, metadata_confirmations if needed, column_mapping pairs and optional labels. Include rule_id/template when choosing the experiment. Resume this task; do not split raw files, try other plotting commands, or create another project. Legacy stepwise answers remain supported."}
        field = "annotation_choices" if question["field"] == "annotation_rebinding" else question["field"]
        bindings = ({"expected_revision_id": state["revision_id"]} if field == "annotation_choices" else
                    {"expected_question_id": question["question_id"]} if "question_id" in question and field != "rule_id" else {})
        return {"action": "answer_scientific_question", "task": task,
                "schema_query": {"section": "response", "name": field}, "response_bindings": bindings,
                "message": "Read original evidence and rejection reasons, then answer the current question. Confirmations do not convert units."}
    if status == "needs_review":
        source_update = state["request"]["action"] == "update_source"
        name = "accept_source_update" if source_update else "accept_preview"
        bindings = ({"expected_revision_id": state["revision_id"]} if source_update else
                    {"expected_operation_id": state["operation_id"]})
        return {"action": "view_preview_then_decide", "task": task,
                "schema_query": {"section": "response", "name": name}, "response_bindings": bindings,
                "response_template": {name: True, **bindings},
                **({"cli_argv": ["sciplot", "task", "resume", task, "--accept-preview",
                                 "--expected-operation-id", state["operation_id"], "--json"]}
                   if not source_update else {}),
                "message": "Inspect every returned before/candidate image and scientific audit before accepting this revision."}
    code = (state.get("blocker") or {}).get("reason_code")
    recovery = (state.get("blocker") or {}).get("recovery_action") or recovery_action(state, str(code))
    if recovery == "resolve_source_change":
        return {"action": recovery, "task": task, "reason_code": code,
                "message": "The bound scientific source changed. Resolve the source revision with an explicit source update or the intended original source; do not retry styling, revise valid operations or rewrite raw values to hide the mismatch."}
    if recovery in {"retry_same_task", "release_project_then_retry"}:
        return {"action": recovery, "task": task, "reason_code": code,
                "response": {"retry": True},
                "cli_argv": ["sciplot", "task", "resume", task, "--retry", "--json"],
                "message": (
                    "Close the writable project session or finish its other transaction, then retry this saved task. Do not change its operations."
                    if recovery == "release_project_then_retry" else
                    "Retry this saved task only after resolving the worker timeout. Its phase and transaction evidence prevent recreating or reapplying completed work; do not change the requested operations.")}
    if recovery == "refresh_edit_context":
        return {"action": recovery, "task": task, "reason_code": code,
                "cli_argv": refresh_context_argv(state),
                "message": "The saved edit baseline is stale. Read the current figure once and preview the original intent against that revision; never accept or retry the stale preview."}
    if phase == "exporting":
        return {"action": "repair_export_then_retry", "task": task, "response": {"retry": True},
                "cli_argv": ["sciplot", "task", "resume", task, "--retry", "--json"],
                "message": "Read the blocker and repair the export cause. Retrying this task only exports; it does not reapply the saved revision."}
    if (recovery == "revise_operations" and phase == "previewing"
            and state["request"]["action"] == "edit" and not state.get("preview_accepted")):
        return {"action": "correct_preview_operations", "task": task,
                "schema_query": {"section": "response", "name": "revise_operations"},
                "response_bindings": {"expected_preview_revision": len(state.get("edit_revisions") or []) + 1},
                "message": "Read the blocker. Submit a complete corrected batch against the saved baseline, then inspect the new preview."}
    return {"action": "inspect_blocker_and_saved_state", "task": task, "reason_code": code,
            "diagnostics": {"path": str(task) + "/task.json", "json_pointer": "/blocker"},
            "message": "Read the reported diagnostics before retrying. Do not revise valid operations to fix an unknown runtime failure. Preserve archives and uncertain creation or partially installed source updates."}
