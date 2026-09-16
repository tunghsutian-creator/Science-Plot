"""State-specific guidance projects existing recovery and review contracts."""

from typing import Any


def task_next_step(state: dict[str, Any]) -> dict[str, Any]:
    status, phase = state["status"], state["phase"]
    task = state.get("task_dir")
    if status in {"complete", "cancelled"}:
        return {"action": "inspect_current_project", "task": task,
                "message": "Inspect current source, QA and delivery before handoff or another edit."}
    if status == "needs_input":
        question = state["question"]
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
                "message": "Inspect every returned before/candidate image and scientific audit before accepting this revision."}
    code = (state.get("blocker") or {}).get("reason_code")
    if phase == "exporting":
        return {"action": "repair_export_then_retry", "task": task, "response": {"retry": True},
                "message": "Read the blocker and repair the export cause. Retrying this task only exports; it does not reapply the saved revision."}
    if phase == "previewing" and state["request"]["action"] == "edit" and not state.get("preview_accepted"):
        return {"action": "correct_preview_operations", "task": task,
                "schema_query": {"section": "response", "name": "revise_operations"},
                "response_bindings": {"expected_preview_revision": len(state.get("edit_revisions") or []) + 1},
                "message": "Read the blocker. Submit a complete corrected batch against the saved baseline, then inspect the new preview."}
    return {"action": "inspect_blocker_and_saved_state", "task": task, "reason_code": code,
            "message": "Inspect the blocker and durable task/project records before retrying. Preserve archives and uncertain creation or partially installed source updates."}
