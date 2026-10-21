"""Source-bound explicit missing-value decisions shared by replicate tasks."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.task_errors import TaskControlError


def missing_values_response_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {"expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                           "missing_values": {"const": "exclude"}},
            "required": ["expected_question_id", "missing_values"]}


def require_missing_policy(state: dict[str, Any], evidence: dict[str, Any]) -> str | None:
    """Return observed/explicit policy, or journal a real scientific question."""
    digest = canonical_json_sha256(evidence, allow_nan=False)
    if not any(group["missing_count"] for group in evidence["groups"]):
        return "none_present"
    confirmation = state.get("missing_value_confirmation", {})
    if state["request"].get("missing_values") == "exclude" or (
        confirmation.get("missing_values") == "exclude"
        and confirmation.get("source_sha256") == state["source_sha256"]
        and confirmation.get("evidence_sha256") == digest
    ):
        return "exclude"
    question = {"field": "missing_values", "reason_code": "missing_values_policy_required",
                "source_sha256": state["source_sha256"], "evidence_sha256": digest,
                "evidence": evidence, "choices": ["exclude"],
                "message": "Some replicate cells are missing. Confirm exclusion before mean/sample SD; delivered valid_n will count only finite numeric observations and disclose excluded cells. No values are filled."}
    question["question_id"] = canonical_json_sha256(question, allow_nan=False)
    question["response_template"] = {"expected_question_id": question["question_id"], "missing_values": "exclude"}
    state.update(status="needs_input", phase="scientific_choice", question=question)
    state.pop("blocker", None)
    return None


def accept_missing_values_response(state: dict[str, Any], response: dict[str, Any]) -> None:
    """Accept only this exact current question, never a rule/metadata answer."""
    question = state.get("question", {})
    if (state.get("status") != "needs_input" or question.get("field") != "missing_values"
            or set(response) != {"expected_question_id", "missing_values"}
            or response.get("expected_question_id") != question.get("question_id")
            or response.get("missing_values") != "exclude"
            or question.get("source_sha256") != state.get("source_sha256")):
        raise TaskControlError("invalid_task_response", "Reply to the current source-bound missing_values question with its expected_question_id and explicit exclude policy.")
    state["missing_value_confirmation"] = {"missing_values": "exclude", "source_sha256": state["source_sha256"],
        "question_id": question["question_id"], "evidence_sha256": question["evidence_sha256"]}
