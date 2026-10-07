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
    # The operation's declared discriminator is authoritative for feedback too.
    # A nearly valid unrelated branch must not report missing fields for another op.
    if isinstance(error.instance, dict) and isinstance(error.schema, dict):
        for discriminator in ("op", "mode", "action", "kind"):
            if discriminator not in error.instance:
                continue
            for index, variant in enumerate(error.schema.get(error.validator, [])):
                field = variant.get("properties", {}).get(discriminator, {})
                if "const" in field and error.instance[discriminator] == field["const"]:
                    return branches.get(index, [])
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


def _issues(value: Any, exc: Exception, *, section: str, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    supplied = getattr(exc, "issues", None)
    if isinstance(supplied, list) and supplied:
        return supplied[:8]
    issues = wire_issues(value, section=section)
    if issues:
        return issues
    code = getattr(exc, "reason_code", None)
    if code == "profile_selection_conflict" and isinstance(value, dict):
        fields = [key for key in ("rule_id", "template", "choose_columns") if value.get(key)]
        return [{"path": "/profile", "constraint": "mutually_exclusive", "conflicts_with": fields}]
    if code == "task_location_conflict":
        return [{"path": "/task_dir", "constraint": "same_transport_location"}]
    if code == "invalid_mapping_candidate" and isinstance(value, dict) and state is not None:
        candidates = (state.get("question") or {}).get("mapping_candidates", [])
        chosen = next((item for item in candidates if item["candidate_id"] == value.get("mapping_candidate_id")), None)
        if chosen is None:
            return [{"path": "/mapping_candidate_id", "constraint": "advertised_candidate",
                     "expected": [item["candidate_id"] for item in candidates[:8]],
                     **({"remaining_candidate_count": len(candidates) - 8} if len(candidates) > 8 else {})}]
        count = len(chosen["mapping"]["column_mapping"]["pairs"])
        return [{"path": f"/pair_indices/{index}", "constraint": "maximum", "expected": count - 1}
                for index, pair in enumerate(value.get("pair_indices", [])) if pair >= count][:8]
    if state is not None and code in {"stale_task_preview", "stale_source_review", "stale_task_question"}:
        field, expected = (("expected_question_id", (state.get("question") or {}).get("question_id"))
                           if code == "stale_task_question" else
                           ("expected_revision_id", state.get("revision_id")) if code == "stale_source_review" else
                           ("expected_operation_id", state.get("operation_id")) if state["status"] == "needs_review" else
                           ("expected_preview_revision", len(state.get("edit_revisions") or []) + 1))
        return [{"path": "/" + field, "constraint": "current_review_binding", "expected": expected}]
    rejected_field = getattr(exc, "field", None)
    return [{"path": "/" + str(rejected_field).lstrip("/"), "constraint": "rejected_value"}] if rejected_field else []


def request_repair(request: Any, exc: Exception) -> dict[str, Any]:
    return {"action": "correct_request", "issues": _issues(request, exc, section="request"),
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
    review: dict[str, Any] = ({key: summary[key] for key in ("preview", "previews", "operation_id", "revision_id") if key in summary}
                             if state["status"] == "needs_review" else {})
    return {"action": "correct_response", "task": state["task_dir"],
            "reason_code": getattr(exc, "reason_code", "invalid_arguments"),
            "issues": _issues(response, exc, section="response", state=state),
            "question": question, "question_unchanged": unchanged, "next_step": next_step,
            **review,
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
