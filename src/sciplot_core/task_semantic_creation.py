"""Adapt semantic creation to the existing task journal and Managed plot lifecycle."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_raw_analysis import raw_curve_analysis
from sciplot_core.task_storage import save_task, task_summary


def is_semantic(state: dict[str, Any]) -> bool:
    return state["request"].get("action") == "create" and "intent" in state["request"]


def admit_raw_curve(state: dict[str, Any], plan: dict[str, Any]) -> bool:
    """Freeze the same source, columns, sample and units under Managed authority."""
    request = state["request"]
    source = Path(request["source"])
    rule_id = plan["rule_id"]
    if (set(request) - {"version", "action", "source", "out", "rule_id", "template"}
            or source.suffix.casefold() not in {".csv", ".tsv"} or not source.is_file()
            or rule_id not in {"uvvis_spectrum", "dsc_curve", "tga_curve", "dtg_curve", "saxs_profile", "xrd_pattern"}
            or plan["template"] != "curve" or "data_mapping" in plan or "source_options" in plan):
        return False
    transform = plan.get("scientific_transform") or {}
    output = transform.get("output") or {}
    columns, series = transform.get("source_columns", []), output.get("series", [])
    if not (len(columns) == len(series) == 1
            and output.get("series_order") == [series[0]["sample"]]
            and columns[0]["sample"] == series[0]["sample"]
            and columns[0]["sources"] == [str(source)]
            and series[0]["excluded_point_count"] == 0
            and transform["normalizer"]["operation"] == "none"
            and transform["anchor"]["scope"] == "none"
            and transform["x_coordinate_policy"]["operation"] == "preserve_source_coordinate_and_order"
            and len(plan["resolved_figure_plan"]["selected_figure_ids"]) == 1):
        return False
    from sciplot_core.materials_rules.catalog import get_rule
    from sciplot_core.policy.contract_queries import size_preset_contract

    rule = get_rule(rule_id)
    selected_id, = plan["resolved_figure_plan"]["selected_figure_ids"]
    figure_task = next(item for item in plan["resolved_figure_plan"]["tasks"] if item["figure_id"] == selected_id)
    if figure_task["metric_binding"] != {"kind": "cartesian_xy", "x_metric": output["x_metric"], "y_metric": output["y_metric"]}:
        return False
    conversions = {(item["sample"], item["role"]): item for item in transform["unit_conversions"]}
    coordinates = (("x", "x", rule.x_axis), ("y", "response", rule.y_axis))
    intent: dict[str, Any] = {"rule_id": rule_id}
    for role, original_role, axis in coordinates:
        unit = axis.canonical_unit
        compatibility = transform["axis_compatibility"][role]
        if (compatibility["registered_scale"] != axis.scale or not compatibility["finite_compatible"]
                or (axis.scale == "log" and not compatibility["log_compatible"])):
            return False
        original = columns[0][original_role]
        conversion = conversions.get((series[0]["sample"], original_role), {})
        if (original["unit"] != unit or output.get(role + "_unit") != unit
                or any(conversion.get(step) != {"factor": 1.0, "offset": 0.0}
                       for step in ("source_to_canonical", "canonical_to_display"))
                or original["unit_detection"]["method"] != "detected_from_adjacent_unit_row"):
            return False
        intent[role] = {"quantity": output[role + "_metric"], "column_id": f"column:{original['column_index_zero_based']}",
                        "scale": axis.scale, "direction": "descending" if axis.reverse else "ascending"}

    if rule_id == "dtg_curve":
        from sciplot_core.source_inspection.semantic_evidence import _quantity

        if _quantity(columns[0]["response"]["header"]) != "derivative_mass":
            return False  # A generic "Derivative" header does not prove the DTG unit context.
    semantic = prepare_plan([source], intent)
    frozen = semantic["sources"][0]
    if canonical_json_sha256({"kind": "file", "content_sha256": frozen["sha256"]}) != state["source_sha256"]:
        raise TaskControlError("source_changed", "The original file changed after the raw scientific plan.")
    candidates = frozen["candidates"]
    bindings = semantic.get("resolved_bindings", [])
    if semantic["decisions"] or len(candidates) != 1 or len(candidates[0]["blocks"]) != 1 or len(bindings) != 1:
        return False
    block = candidates[0]["blocks"][0]
    if (block["sample"] != series[0]["sample"] or block["point_count"] != series[0]["point_count"]):
        return False
    for role, original_role, axis in coordinates:
        actual, original = bindings[0]["coordinates"][role], columns[0][original_role]
        # Scattering quantities may be known to the registered plan without
        # aliases in the generic table. DTG needs the observed derivative.
        expected = output[role + "_metric"]
        allowed = (expected, None) if rule_id in {"saxs_profile", "xrd_pattern"} else (expected,)
        if ((actual["column_index"], actual["header"], actual["observed_unit"], actual["unit"])
                != (original["column_index_zero_based"], original["header"], axis.canonical_unit, axis.canonical_unit)
                or actual["observed_quantity"] not in allowed
                or actual["unit_relation"]["kind"] != "identity"):
            return False

    size = size_preset_contract(rule.render_options["size"])
    presentation: dict[str, Any] = {}
    if rule_id == "xrd_pattern":
        from sciplot_core.studio_render.spectral_axis_display import freeze_new_spectral_axis_display

        display = freeze_new_spectral_axis_display({}, rule_id=rule_id, template="curve", transform_contract=transform)
        presentation["show_y_ticks"] = display["render_options"]["show_y_ticks"]
    analysis = raw_curve_analysis(source, rule_id, plan, frozen["sha256"])
    state.update(initial_request=deepcopy(request), analysis_metrics=analysis,
                 request={"version": 1, "action": "create", "sources": [str(source)], "intent": intent,
                          **({"out": request["out"]} if "out" in request else {})},
                 source_hashes={str(source): frozen["sha256"]}, semantic_plan=semantic, semantic_choices={},
                 semantic_plan_confirmed=True, intent_revision=1,
                 plan_confirmation={"mode": "verified_raw_curve", "rule_id": rule_id,
                                    "figure_plan": plan["resolved_figure_plan"]["plan_sha256"],
                                    "size_mm": [size.width_mm, size.height_mm], **presentation,
                                    "axis_labels": {role: axis.display_label.replace("$^{-1}$", "⁻¹")
                                                    for role, _, axis in coordinates}})
    return True


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
    from sciplot_core.task_semantic_plan import selected_table_plan

    intent = state["request"]["intent"]
    choices = state.get("semantic_choices", {})
    plan = state["semantic_plan"]
    if plan.get("intent") != intent:
        error = TaskControlError("semantic_plan_intent_changed", "The complete intent differs from its source-bound plan. Use revise_intent in this same task to resolve a new scientific draft.")
        error.repair = {"action": "revise_intent"}
        raise error
    if "resolved_bindings" not in plan or plan.get("resolved_choices") != choices:
        plan = selected_table_plan(plan, intent, choices)
        state["semantic_plan"] = plan
    if plan["decisions"]:
        raise TaskControlError("semantic_plan_choice_required", "Confirm this same task's current original-source plan before compilation; no scientific choice was inferred.")
    return build_request(state)


def execute_managed(state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.plot_protocol.socket_client import call

    # The established local RPC port owns serialization and lost-reply safety.
    # It does not import the server/PlotService back into the task coordinator.
    return call("plot.create", {"request": request})


def _ask_plan(root: Path, state: dict[str, Any]) -> None:
    question = {"field": "semantic_plan", "intent_revision": state["intent_revision"],
                "plan": state["semantic_plan"], "message": "Resolve the listed scientific choices in this same task; no native work has started."}
    question["question_id"] = canonical_json_sha256(question)
    state.update(status="needs_input", phase="scientific_choice", question=question, semantic_plan_confirmed=False)
    save_task(root, state)


def run_creation(root: Path, state: dict[str, Any]) -> None:
    assert_sources_current(state)
    from sciplot_core.task_scientific_presentation import presentation_blocker, scientific_presentation

    effective = scientific_presentation(state["request"])
    state["scientific_presentation"] = {**effective, "source_hashes": dict(state["source_hashes"])}
    blocker = presentation_blocker(state["request"], effective)
    if blocker is not None:
        state.setdefault("intent_revision", 1)
        state.update(status="blocked", phase="planning", blocker=blocker)
        save_task(root, state)
        return
    if "delivery_request" in state:
        from sciplot_core.task_semantic_delivery import finish_delivery

        finish_delivery(root, state)
        return
    state.setdefault("intent_revision", 1)
    if "semantic_plan" in state and "resolution_version" not in state["semantic_plan"] and "managed_request" not in state:
        if state.get("creation_attempts") or state.get("project") or state.get("phase") in {"creating", "exporting", "finished"}:
            raise TaskControlError("creation_outcome_uncertain", "The prior creation attempt lacks a frozen request. Preserve its evidence and inspect that outcome; its science cannot be resolved into a replacement request.")
        state.setdefault("semantic_plan_history", []).append({"intent_revision": state["intent_revision"],
            "plan": deepcopy(state["semantic_plan"]), "choices": deepcopy(state.get("semantic_choices", {})),
            "question": deepcopy(state.get("question")), "confirmation": deepcopy(state.get("plan_confirmation"))})
        for key in ("semantic_plan", "semantic_plan_confirmed", "semantic_choices", "question", "plan_confirmation"):
            state.pop(key, None)
    if "semantic_plan" not in state:
        state.update(status="running", phase="planning")
        save_task(root, state)
        from sciplot_core.task_output_choice import require_available_output

        if not require_available_output(state):
            save_task(root, state)
            return
        plan = prepare_plan([Path(value) for value in state["request"]["sources"]], state["request"]["intent"])
        state["semantic_plan"] = plan
        state.pop("blocker", None)
        if plan.get("decisions"):
            _ask_plan(root, state)
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
    if complete:
        from sciplot_core.task_semantic_delivery import finish_delivery

        finish_delivery(root, state)


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
    if "out" in response:
        from sciplot_core.task_output_choice import accept_output_response

        accept_output_response(state, response)
        run_creation(root, state)
        return
    if "revise_intent" in response:
        if not Draft202012Validator(semantic_response_schemas()[1]).is_valid(response):
            raise TaskControlError("invalid_task_response", "Revise the complete semantic intent with its current intent_revision.")
        if response["expected_intent_revision"] != state.get("intent_revision", 1):
            raise TaskControlError("stale_task_question", "Use the current intent_revision to replace this draft.")
        if state.get("project") or state.get("result", {}).get("commit_status") == "committed":
            raise TaskControlError("task_not_revisable", "This task already committed a plot. Continue its saved plot through an explicit scientific edit; a draft correction cannot replace committed science.")
        if "managed_request" not in state and (state.get("creation_attempts") or state.get("phase") in {"creating", "exporting", "finished"}):
            raise TaskControlError("task_not_revisable", "The prior native outcome lacks its frozen request. Recover that original outcome before replacing scientific intent.")
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
        for key in ("semantic_plan", "semantic_plan_confirmed", "semantic_choices", "managed_request", "question", "blocker", "result", "plan_confirmation", "analysis_metrics"):
            state.pop(key, None)
        run_creation(root, state)
        return
    if response == {"retry": True}:
        if state.get("delivery_request") or (state.get("project") and (state.get("result") or {}).get("status") == "complete"):
            from sciplot_core.task_semantic_delivery import finish_delivery

            finish_delivery(root, state)
            return
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
    accumulated = {**state.get("semantic_choices", {}), **deepcopy(choices)}
    if choices:
        from sciplot_core.task_semantic_plan import selected_table_plan

        plan = selected_table_plan(state["semantic_plan"], state["request"]["intent"], accumulated)
        state.update(semantic_plan=plan, semantic_choices=accumulated)
        if plan["decisions"]:
            _ask_plan(root, state)
            return
    state.update(semantic_choices=accumulated, semantic_plan_confirmed=True)
    state.pop("question", None)
    save_task(root, state)
    run_creation(root, state)


def current_result(state: dict[str, Any]) -> dict[str, Any]:
    summary = task_summary(state)
    if state.get("project") and state["status"] == "complete":
        from sciplot_core.plot_protocol.socket_client import call

        try:
            current = call("plot.describe", {"plot": state["project"], "description": {"scope": "summary"}})
        except (ValueError, OSError, RuntimeError) as exc:
            summary.update(status="blocked", ready_to_use=False, current_project={"status": "unknown", "message": str(exc)})
            return summary
        summary["current_project"] = current
        exports = (state.get("result") or {}).get("exports", [])
        from sciplot_core.task_semantic_delivery import delivery_current

        native_delivery_current = delivery_current(state)
        exported = state.get("result") or {}
        identities_match = all(current.get(key) == exported.get(key) for key in ("revision", "scientific_hash", "presentation_hash"))
        export_current = current.get("export_current") or {}
        # Only the execution owner can compare its actual render recipe. The
        # client process has a different startup/environment identity.
        ready = (native_delivery_current and current["status"] == "current" and current.get("pending") is None
                 and identities_match and bool(exports) and export_current.get("current") is True
                 and export_current.get("byte_inventory_verified") is True)
        summary.update(ready_to_use=ready, readiness_evaluated=True)
        if ready:
            from sciplot_core.task_semantic_delivery import handoff_paths

            summary["next_step"] = {"action": "review_exports_and_deliver", "task": state["task_dir"],
                **handoff_paths(state),
                "delivery": state["delivery_result"]["delivery"],
                "message": "Review the actual exported images. The Managed document is the scientific authority; retain original attachments and its .sciplot_documents directory."}
        elif not native_delivery_current:
            summary.update(status="blocked", next_step={"action": "finish_native_delivery", "task": state["task_dir"],
                "cli_argv": ["sciplot", "task", "resume", state["task_dir"], "--retry", "--json"],
                "response_template": {"retry": True},
                "message": "The original export is preserved, but the final native snapshot/data/launcher delivery is missing or changed. Resume this same task; packaging never recreates or edits the plot."})
        else:
            summary.update(status="blocked", next_step={"action": "resolve_current_evidence", "task": state["task_dir"],
                "message": "Historical task completion does not certify current source, native or delivery files. Inspect the returned current state and preserve this task."})
    return summary
