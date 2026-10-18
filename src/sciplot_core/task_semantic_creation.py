"""Adapt semantic creation to the existing task journal and Managed plot lifecycle."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task, task_summary


def is_semantic(state: dict[str, Any]) -> bool:
    return state["request"].get("action") == "create" and "intent" in state["request"]


def normalize_sources(request: dict[str, Any]) -> dict[str, str]:
    paths = [canonical_path(Path(value)) for value in request["sources"]]
    if len(paths) != len(set(paths)):
        raise TaskControlError("duplicate_semantic_source", "List each exact original attachment once; aliases cannot duplicate a source.")
    digests = {}
    for path in paths:
        if not path.is_file():
            error = TaskControlError("source_is_directory" if path.is_dir() else "source_not_found", "Select exact original data files; directories are not a semantic table attachment.")
            error.repair = {"action": "select_source_files", "source": str(path),
                            "files": [str(item) for item in sorted(path.iterdir()) if item.is_file() and item.suffix.lower() in {".csv", ".tsv", ".xlsx", ".xls"}][:32] if path.is_dir() else []}
            raise error
        digests[str(path)] = file_sha256(path)
    if "out" in request:
        output = canonical_path(Path(request["out"]))
        if any(output == path or output in path.parents or path in output.parents for path in paths):
            raise TaskControlError("output_path_overlap", "The delivery directory cannot contain, replace or be contained by any original attachment.")
    request["sources"] = [str(path) for path in paths]
    return digests


def assert_sources_current(state: dict[str, Any]) -> None:
    for name, digest in state["source_hashes"].items():
        path = canonical_path(Path(name))
        if not path.is_file() or file_sha256(path) != digest:
            raise TaskControlError("source_changed", "An original attachment changed. Preserve the task and restore its exact source or start an explicit source revision; no rendering was run.")


def prepare_plan(paths: list[Path], intent: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.task_semantic_plan import prepare_plan as prepare

    return prepare(paths, intent)


def build_managed_request(state: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.task_semantic_figure import build_request

    return build_request(state)


def execute_managed(state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.plot_engine.service import PlotService

    service = PlotService()
    try:
        # create_managed already freezes request identity before scientific
        # resolution and resumes a committed export instead of creating twice.
        return service.create(request)
    finally:
        service.close()


def run_creation(root: Path, state: dict[str, Any]) -> None:
    assert_sources_current(state)
    state.setdefault("intent_revision", 1)
    if "semantic_plan" not in state:
        state.update(status="running", phase="planning")
        save_task(root, state)
        plan = prepare_plan([Path(value) for value in state["request"]["sources"]], state["request"]["intent"])
        state["semantic_plan"] = plan
        state.pop("blocker", None)
        if plan.get("decisions"):
            question = {"field": "semantic_plan", "intent_revision": state["intent_revision"],
                        "plan": plan, "message": "Resolve the listed scientific choices together in this same task; no native work has started."}
            question["question_id"] = canonical_json_sha256(question)
            state.update(status="needs_input", phase="scientific_choice", question=question)
            save_task(root, state)
            return
        state.update(semantic_plan_confirmed=True, semantic_choices={},
                     plan_confirmation={"mode": "explicit_intent_and_unambiguous_source_evidence"})
        state.pop("question", None)
        save_task(root, state)
    if not state.get("semantic_plan_confirmed"):
        return
    if "managed_request" not in state:
        state["managed_request"] = build_managed_request(state)
        state.setdefault("creation_attempts", []).append({"intent_revision": state["intent_revision"],
            "idempotency_key": state["managed_request"]["idempotency_key"], "request": deepcopy(state["managed_request"])})
    state.update(status="running", phase="creating")
    state.pop("blocker", None)
    save_task(root, state)
    result = execute_managed(state, state["managed_request"])
    state["result"] = result
    if isinstance(result.get("plot"), str):
        state["project"] = result["plot"]
    complete = (result.get("status") == "complete" and result.get("ready_to_use") is True
                and isinstance(result.get("plot"), str) and bool(result.get("exports")))
    state.update(status="complete" if complete else "blocked", phase="finished" if complete else "exporting")
    if not complete:
        state["blocker"] = {"reason_code": (result.get("error") or {}).get("reason_code", "managed_export_not_ready"),
                            "message": (result.get("error") or {}).get("message", "The saved Managed revision is not a verified delivery."),
                            "recovery_action": (result.get("next_step") or {}).get("action", "inspect_diagnostic"),
                            "owner_next_step": deepcopy(result.get("next_step", {})),
                            **({"diagnostic": result["error"]} if result.get("error") else {})}
    save_task(root, state)


def _validate_choices(plan: dict[str, Any], choices: dict[str, Any]) -> None:
    fields = {decision["field"] for decision in plan.get("decisions", [])}
    if set(choices) - fields:
        error = TaskControlError("invalid_task_response", "Only answer the decisions advertised by this exact plan; existing explicit intent cannot be silently overridden.")
        error.issues = [{"path": "/choices", "constraint": "advertised_fields_only", "unsupported": sorted(set(choices) - fields)}]
        raise error
    for decision in plan.get("decisions", []):
        field = decision["field"]
        actual = choices.get(field)
        allowed = decision["options"]
        valid = (isinstance(actual, dict) and set(actual) == set(allowed)
                 and all(actual[name] in options for name, options in allowed.items())) if isinstance(allowed, dict) else actual in allowed
        if not valid:
            error = TaskControlError("invalid_task_response", "Answer every listed scientific decision with one advertised option; no choice is inferred.")
            error.issues = [{"path": "/choices/" + field, "constraint": "advertised_option", "expected": allowed, "actual": actual}]
            raise error


def resume(root: Path, state: dict[str, Any], response: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator
    from sciplot_core.task_semantic_contract import semantic_response_schemas, validate_intent

    assert_sources_current(state)
    if "revise_intent" in response:
        if not Draft202012Validator(semantic_response_schemas()[1]).is_valid(response):
            raise TaskControlError("invalid_task_response", "Revise the complete semantic intent with its current intent_revision.")
        if response["expected_intent_revision"] != state.get("intent_revision", 1):
            raise TaskControlError("stale_task_question", "Use the current intent_revision to replace this draft.")
        if state.get("project") or state.get("result", {}).get("commit_status") == "committed":
            raise TaskControlError("task_not_revisable", "This task already committed a plot. Continue its saved plot through an explicit scientific edit; a draft correction cannot replace committed science.")
        # A lost reply may have committed before the task adopted its receipt.
        # Inspect the already frozen attempt's known Managed owner journal.
        wire = state.get("managed_request")
        if wire:
            from sciplot_core.plot_engine.storage import digest

            first = Path(wire["data_binding"]["data_sources"][0]["path"])
            owner = first.parent / ".sciplot_documents" / "managed" / digest(wire["idempotency_key"])
            if (owner / "head.json").exists():
                raise TaskControlError("task_not_revisable", "The prior attempt committed before its reply. Retry this same task to recover its saved plot; do not replace the request.")
        intent = validate_intent(response["revise_intent"])
        state.setdefault("intent_history", []).append({"intent_revision": state.get("intent_revision", 1),
            "intent": deepcopy(state["request"]["intent"]), "question": deepcopy(state.get("question")),
            "blocker": deepcopy(state.get("blocker"))})
        state["request"]["intent"] = intent
        state["intent_revision"] = int(state.get("intent_revision", 1)) + 1
        for key in ("semantic_plan", "semantic_plan_confirmed", "semantic_choices", "managed_request", "question", "blocker", "result"):
            state.pop(key, None)
        run_creation(root, state)
        return
    if response == {"retry": True}:
        if state.get("semantic_plan_confirmed"):
            run_creation(root, state)
            return
        if "semantic_plan" not in state:
            run_creation(root, state)
            return
        raise TaskControlError("invalid_task_response", "The current source plan requires confirmation and scientific choices; retry does not confirm it.")
    if not Draft202012Validator(semantic_response_schemas()[0]).is_valid(response):
        raise TaskControlError("invalid_task_response", "Confirm the current semantic plan, or revise the complete intent in this task.")
    if response["expected_question_id"] != (state.get("question") or {}).get("question_id"):
        raise TaskControlError("stale_task_question", "This response belongs to a different source-bound plan.")
    choices = response.get("choices", {})
    _validate_choices(state["semantic_plan"], choices)
    state.update(semantic_choices=deepcopy(choices), semantic_plan_confirmed=True)
    state.pop("question", None)
    save_task(root, state)
    run_creation(root, state)


def current_result(state: dict[str, Any]) -> dict[str, Any]:
    summary = task_summary(state)
    if state.get("project") and state["status"] == "complete":
        from sciplot_core.plot_engine.service import PlotService

        service = PlotService()
        try:
            current = service.describe(Path(state["project"]), description={"scope": "summary"})
        except (ValueError, OSError, RuntimeError) as exc:
            summary.update(status="blocked", ready_to_use=False, current_project={"status": "unknown", "message": str(exc)})
            return summary
        finally:
            service.close()
        summary["current_project"] = current
        exports = (state.get("result") or {}).get("exports", [])
        from sciplot_core.plot_engine.current import evidence_current
        from sciplot_core.plot_engine.cache_identity import build_key
        from sciplot_core.plot_engine.storage import load_head, read

        cache_path = Path(state["project"]) / "export-cache.json"
        cache = read(cache_path) if cache_path.is_file() else {}
        head = load_head(Path(state["project"]))
        exported = (state.get("result") or {})
        identities_match = all(current.get(key) == exported.get(key) for key in ("revision", "scientific_hash", "presentation_hash"))
        ready = (current["status"] == "current" and current.get("pending") is None and identities_match
                 and bool(exports) and cache.get("build_key") == build_key(head["document"], head["binding"])
                 and evidence_current(cache.get("artifact_files", {}), cache.get("evidence_inventories", {})))
        summary.update(ready_to_use=ready, readiness_evaluated=True)
        if ready:
            summary["next_step"] = {"action": "review_exports_and_deliver", "task": state["task_dir"],
                "images": [item["path"] for item in exports if "tiff" in item.get("format", "")],
                "editable_native": {"document": current.get("artifact"),
                                    "command": ["sciplot", "studio", current.get("artifact")],
                                    "authority": "Managed scientific document remains authoritative; native changes require explicit reconciliation."},
                "message": "Review the actual exported images. The Managed document is the scientific authority; retain original attachments and its .sciplot_documents directory."}
        else:
            summary.update(status="blocked", next_step={"action": "resolve_current_evidence", "task": state["task_dir"],
                "message": "Historical task completion does not certify current source, native or delivery files. Inspect the returned current state and preserve this task."})
    return summary


def blocked_next_step(state: dict[str, Any]) -> dict[str, Any]:
    """Retain the Managed owner's corrective action; never turn an unknown failure into retry."""
    blocker = state.get("blocker") or {}
    owner = blocker.get("owner_next_step") or {}
    repair = blocker.get("repair") or {}
    action = owner.get("action") or repair.get("action") or blocker.get("recovery_action") or "inspect_diagnostic"
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
    if not state.get("project"):
        step["draft_revision_template"] = {"expected_intent_revision": state["intent_revision"],
                                            "revise_intent": state["request"]["intent"]}
    return step
