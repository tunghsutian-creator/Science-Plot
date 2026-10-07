"""Typed task entries compose the existing current-state and lifecycle owners."""

from pathlib import Path
from typing import Any

from sciplot_core.doctor import doctor_payload
from sciplot_core.studio_core.annotation_schema import validate_operation_batch
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError, validate_task_request
from sciplot_core.task_control import inspect_task, start_task
from sciplot_core.task_edit_context import edit_context
from sciplot_core.task_storage import load_task


def _style_replay(task_dir: Path | None, intent: dict[str, Any]) -> dict[str, Any] | None:
    """An explicit task key replays its original intent, never today's new SHA."""
    if task_dir is None:
        return None
    root = canonical_path(task_dir)
    if not root.exists():
        return None
    state = load_task(root)
    if state.get("entry_intent") != intent:
        stored = state.get("entry_intent")
        differences = ([key for key in sorted(set(stored) | set(intent)) if stored.get(key) != intent.get(key)]
                       if isinstance(stored, dict) else ["entry_intent"])
        existing = dict(stored) if isinstance(stored, dict) else None
        if existing is not None and isinstance(existing.get("samples"), list):
            sample_count = len(existing["samples"])
            existing["samples"] = existing["samples"][:16]
            existing["omitted_sample_count"] = max(0, sample_count - 16)
        error = TaskControlError(
            "task_intent_conflict",
            "This task key has a different or unavailable original style intent. The current request was not executed.",
        )
        error.repair = {"action": "resolve_task_intent_conflict", "task": str(root),
                        "existing_intent": existing, "different_fields": differences,
                        "request_executed": False,
                        "message": "Do not accept the old preview as this rejected edit. Continue the saved original intent, revise its pending preview explicitly, or use a new task key for a new intent."}
        raise error
    return inspect_task(root)


def _target_error(code: str, message: str, context: dict[str, Any], sample: str | None = None) -> TaskControlError:
    """Return current exact choices already read, without a discovery round trip."""
    targets = context["selected_figure"]["sample_styles"]
    exact = [item for item in targets if item["sample"] == sample]
    ordered = exact + [item for item in targets if item["sample"] != sample]
    choices = []
    for item in ordered[:16]:
        choice = {key: item[key] for key in ("sample", "unique") if key in item}
        if "object_paths" in item:
            choice["object_paths"] = item["object_paths"][:16]
            if len(item["object_paths"]) > 16:
                choice["omitted_object_count"] = len(item["object_paths"]) - 16
        choices.append(choice)
    error = TaskControlError(code, message)
    error.repair = {"action": "correct_style_target",
                    "issues": [{"path": "/samples", "constraint": "exact_current_sample_label"}],
                    "figure_id": context["request_template"]["figure_id"],
                    "targets": choices, "target_count": len(targets),
                    "omitted_target_count": max(0, len(targets) - len(choices)),
                    "message": "Choose only explicit exact labels; duplicate labels require the listed native object paths. No label is selected automatically."}
    return error


def create_task(
    source: Path, *, rule_id: str | None = None, template: str | None = None,
    profile: Path | None = None, out: Path | None = None, task_dir: Path | None = None,
) -> dict[str, Any]:
    """Start from original input; scientific choices stay with ordinary creation."""
    request: dict[str, Any] = {"version": 1, "action": "create", "source": str(source)}
    for key, value in (("rule_id", rule_id), ("template", template), ("profile", profile), ("out", out)):
        if value is not None:
            request[key] = str(value)
    request = validate_task_request(request)
    runtime = doctor_payload()
    doctor = {"kind": runtime["kind"], "status": runtime["status"],
              "failed_checks": [item for item in runtime["checks"] if item.get("status") != "passed"]}
    if runtime["status"] != "ready":
        return {"kind": "sciplot_task_shortcut", "version": 1, "status": "blocked",
                "reason_code": "runtime_not_ready", "doctor": doctor,
                "next_step": {"action": "repair_runtime", "next_actions": runtime.get("next_actions", [])}}
    return {**start_task(request, task_dir=task_dir), "doctor": doctor}


def style_task(
    target: Path, *, samples: list[str] | None = None, all_samples: bool = False,
    width: str | None = None, color: str | None = None,
    figure_id: str | None = None, task_dir: Path | None = None,
) -> dict[str, Any]:
    """Bind an explicit sample-style intent now, then return its normal preview."""
    if all_samples == (samples is not None):
        raise TaskControlError("invalid_sample_selection", "Choose --all-samples or one or more exact --sample labels.")
    style = {key: value for key, value in (("width", width), ("color", color)) if value is not None}
    if not style or any(not value.strip() for value in style.values()):
        raise TaskControlError("invalid_sample_style", "Provide a non-empty --width and/or --color.")
    validate_operation_batch([{"op": "set_sample_style", "samples": samples if samples is not None else ["_all_samples"], "style": style}])
    if "width" in style:
        from sciplot_core.style_values import normalize_physical_size

        style["width"] = normalize_physical_size(style["width"])
    intent = {"kind": "sciplot_style_intent", "version": 1,
              "target": str(canonical_path(target)), "figure_id": figure_id,
              "all_samples": all_samples, "samples": list(samples) if samples is not None else None,
              "style": style}
    replay = _style_replay(task_dir, intent)
    if replay is not None:
        return replay
    context = edit_context(target, operations=["set_sample_style"], figure_id=figure_id)
    if context["status"] != "ok":
        return context
    targets = context["selected_figure"]["sample_styles"]
    selected = [item["sample"] for item in targets] if all_samples else list(samples or [])
    if not selected:
        raise _target_error("unknown_sample_style_target", "The selected figure has no ordinary sample-style targets.", context)
    inventory = {item["sample"]: item for item in targets}
    for sample in selected:
        if sample not in inventory:
            raise _target_error("unknown_sample_style_target", f"No ordinary curve has exact sample label {sample!r}.", context, sample)
        if inventory[sample]["unique"] is not True:
            raise _target_error("ambiguous_sample_style_target", f"Sample label {sample!r} names multiple curves; use explicit native targets.", context, sample)
    operations = [{"op": "set_sample_style", "samples": selected, "style": style}]
    validate_operation_batch(operations)
    request = validate_task_request({**context["request_template"], "operations": operations})
    result = (start_task(request, task_dir=task_dir, entry_intent=intent)
              if task_dir is not None else start_task(request, task_dir=None))
    return {**result, "doctor": context["doctor"]}
