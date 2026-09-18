"""Bounded correction feedback over the existing task contracts; no AI or retries."""

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema
from sciplot_core.task_storage import load_task, task_path, task_summary


def normalize_task_location(request: dict[str, Any], supplied: Path | None) -> tuple[dict[str, Any], Path | None, list[dict[str, str]]]:
    """Relocate one unambiguous transport field, never guess scientific values."""
    if not isinstance(request, dict) or "task_dir" not in request:
        return request, supplied, []
    value = request["task_dir"]
    if not isinstance(value, str) or not value.strip():
        raise TaskControlError("invalid_task_field", "task_dir 必须是非空路径。")
    embedded = canonical_path(Path(value))
    if supplied is not None and canonical_path(supplied) != embedded:
        raise TaskControlError("task_location_conflict", "两处 task_dir 不一致；请选择一个任务位置，其他请求字段保持不变。")
    return ({key: item for key, item in request.items() if key != "task_dir"}, embedded,
            [{"field": "/task_dir", "action": "moved_to_transport_option", "value": str(embedded)}])


def _leaves(error: ValidationError) -> list[ValidationError]:
    if error.validator not in {"oneOf", "anyOf"} or not error.context:
        return [error]
    branches: dict[Any, list[ValidationError]] = {}
    for child in error.context:
        branches.setdefault(child.schema_path[0], []).extend(_leaves(child))
    return min(branches.values(), key=len)


def wire_issues(value: Any, *, section: str) -> list[dict[str, Any]]:
    """Report paths and constraints without echoing raw instances or every oneOf branch."""
    schemas = task_request_schema() if section == "request" else task_response_schema()
    variants = schemas["oneOf"]
    if isinstance(value, dict):
        if section == "request":
            selected = [s for s in variants if s["properties"]["action"]["const"] == value.get("action")]
        else:
            selected = [s for s in variants if any(k in value for k in s["required"] if not k.startswith("expected_"))]
        if selected:
            variants = selected
    # Use the nearest advertised shape only for feedback, never to accept input.
    errors = min(([leaf for e in Draft202012Validator(s).iter_errors(value) for leaf in _leaves(e)]
                  for s in variants), key=len)
    issues = []
    for error in errors[:8]:
        path = "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in error.absolute_path)
        item: dict[str, Any] = {"path": path, "constraint": error.validator}
        if error.validator == "required" and isinstance(error.validator_value, list) and isinstance(error.instance, dict):
            item["missing"] = [key for key in error.validator_value if key not in error.instance]
        elif error.validator == "additionalProperties" and isinstance(error.instance, dict) and isinstance(error.schema, dict):
            item["unsupported"] = sorted(set(error.instance) - set(error.schema.get("properties", {})))[:16]
        elif error.validator in {"type", "minimum", "maximum", "minItems", "maxItems", "minLength", "pattern", "const", "enum", "uniqueItems"}:
            item["expected"] = error.validator_value
        else:
            item["message"] = "Use the advertised schema for this field."
        issues.append(item)
    if len(errors) > 8:
        issues.append({"remaining_issue_count": len(errors) - 8})
    return issues


def request_repair(request: Any, exc: Exception) -> dict[str, Any]:
    return {"action": "correct_request", "issues": wire_issues(request, section="request"),
            "reason_code": getattr(exc, "reason_code", "invalid_arguments"),
            "message": "Correct only rejected fields; retain valid source/out/mapping. Resubmit task start. No task was created."}


def response_repair(state: dict[str, Any], response: Any, exc: Exception) -> dict[str, Any]:
    summary = task_summary(state)
    question = summary.get("question")
    unchanged = (isinstance(question, dict) and isinstance(response, dict)
                 and question.get("question_id") is not None
                 and response.get("expected_question_id") == question["question_id"])
    next_step = dict(summary["next_step"])
    if unchanged and isinstance(question, dict):
        question = {key: question[key] for key in ("field", "question_id")}
        # Bindings refer to evidence already returned for exactly this question.
        # Keep the generic shape: never silently remove invalid sample selections.
        next_step["message"] = "Correct only issues below using the already returned evidence for this question; no inspect/help call is needed."
    return {"action": "correct_response", "task": state["task_dir"],
            "reason_code": getattr(exc, "reason_code", "invalid_arguments"),
            "issues": wire_issues(response, section="response"),
            "question": question, "question_unchanged": unchanged, "next_step": next_step,
            "message": "Use this saved current question and next_step in the same task. Source bytes are rechecked on resume. Do not repeat an unchanged rejected answer or rewrite raw values."}


def adapter_repair(name: str, arguments: dict[str, Any], exc: Exception) -> dict[str, Any] | None:
    """Give MCP schema failures the same correction context without executing work."""
    if name == "sciplot_task_start":
        return request_repair(arguments.get("request"), exc)
    if name == "sciplot_task_resume" and isinstance(arguments.get("task"), str):
        try:
            state = load_task(task_path(Path(arguments["task"])))
        except (ValueError, OSError):
            return None
        return response_repair(state, arguments.get("response"), exc)
    return None
