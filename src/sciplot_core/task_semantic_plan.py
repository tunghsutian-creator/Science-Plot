"""Prepare one original-evidence question; candidates never silently become science."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_coordinates import coordinate_columns, resolved_binding, source_unit
from sciplot_core.task_semantic_stages import ordered_stages, stage_evidence


def scientific_adapter(intent: dict[str, Any]) -> str | None:
    """Only an explicitly selected registered rule supplies scientific policy."""
    from sciplot_core.materials_rules.catalog import iter_rules

    context = intent.get("rule_id", "ordinary_xy")
    registered = next((rule for rule in iter_rules() if rule.rule_id == context), None)
    if registered is None and context != "ordinary_xy":
        error = TaskControlError("semantic_rule_unknown", "Select an advertised experiment rule or retain original-value ordinary_xy; source layout and coordinate names cannot select an experiment.")
        error.repair = {"action": "revise_intent", "field": "intent.rule_id"}
        raise error
    return registered.scientific_source_adapter if registered else None


def _coordinate_binding(column: dict[str, Any], coordinate: dict[str, Any], role: str) -> dict[str, Any]:
    from sciplot_core.plot_document.errors import DocumentError
    from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation

    if role == "temperature" and not column["unit"]:
        error = TaskControlError("semantic_source_unit_required", "The secondary temperature needs an observed original unit. This coordinate contract cannot declare an absent source unit; retain the original and select an unambiguous supported temperature field.")
        error.issues = [{"path": "/intent/secondary_y", "column_id": column["column_id"], "constraint": "observed_original_unit"}]
        error.repair = {"action": "revise_intent", "supported_selectors": ["intent.secondary_y.header", "intent.secondary_y.column_id"],
                        "message": "Select a supported original temperature field with recorded units, or remove this optional secondary axis explicitly. Do not change raw units or send an unsupported secondary source_unit field."}
        raise error
    observed = source_unit(column, coordinate, role)
    try:
        target = coordinate.get("unit", observed)
        relation = resolve_unit_relation(observed, target, quantity=coordinate["quantity"],
            observed_quantity=column["quantity"], explicit_quantity_binding=any(
                field in coordinate for field in ("header", "headers", "column_id")))
    except DocumentError as exc:
        error = TaskControlError(exc.reason_code, str(exc))
        error.issues = [{"path": "/intent/" + ("secondary_y" if role == "temperature" else role) + "/unit", "column_id": column["column_id"], "source_unit": observed,
                         "unit": coordinate.get("unit"), "constraint": "registered_unit_relation"}]
        error.repair = {"action": "revise_intent", "message": (
            "This compound C unit is currently unsupported. Preserve the original column, unit and values; formatting cannot establish a different physical quantity."
            if exc.reason_code == "transform_unit_context_unsupported" else
            "Keep the exact original column and unit. Select a registered target unit; no numeric value was changed.")}
        raise error from exc
    return {"column_id": column["column_id"], "column_index": column["column_index"], "header": column["header"],
            "quantity": coordinate["quantity"], "observed_quantity": column["quantity"], "observed_unit": column["unit"],
            "source_unit": observed, "unit": target, "unit_relation": relation,
            "unit_context": {"version": 1, "quantity": coordinate["quantity"], "observed_quantity": column["quantity"],
                             "source_header": column["header"], "explicit_quantity_binding": any(
                                 field in coordinate for field in ("header", "headers", "column_id"))}}


def _coordinate_decisions(sources: list[dict[str, Any]], intent: dict[str, Any],
                          choices: dict[str, Any], adapter: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    from sciplot_core.task_semantic_figure import _source_views
    from sciplot_core.task_semantic_frequency import frequency_derivation, frequency_condition

    if adapter == "rheology_frequency":
        from sciplot_core.task_semantic_frequency import validate_frequency_intent

        validate_frequency_intent(intent)
    views = _source_views(sources, choices, intent)
    bindings = []
    for source, candidate in views:
        for block in candidate["blocks"]:
            bindings.append({"source_path": source["path"], "source_sha256": source["sha256"],
                             "table_id": candidate["candidate_id"], "block_id": block["block_id"],
                             "table_selection": deepcopy(block["table_selection"]),
                             "quantities": {role: candidate.get("curve_coordinates", {}).get(role, intent[role])["quantity"] for role in ("x", "y")},
                             "condition": frequency_condition(block) if adapter == "rheology_frequency" else {},
                             "coordinates": {}})
    decisions: list[dict[str, Any]] = []
    for role in ("x", "y"):
        groups = []
        index = 0
        for _source, candidate in views:
            coordinate = {**candidate.get("curve_coordinates", {}).get(role, intent[role]),
                          **({"header": choices[role + "_header"]} if role + "_header" in choices else {})}
            for block in candidate["blocks"]:
                    columns = block.get("columns") or [column for column in candidate["columns"] if column["column_index"] in block["column_indices"]]
                    eligible = coordinate_columns(columns, block, coordinate, role)
                    derived = frequency_derivation(columns, coordinate) if adapter == "rheology_frequency" and role == "y" else None
                    has_selector = any(field in coordinate for field in ("header", "headers", "column_id"))
                    if derived and not has_selector:
                        eligible = [column for column in eligible if column["quantity"] == coordinate["quantity"]]
                    if not eligible and derived and not has_selector:
                        eligible = [derived]
                    if len(eligible) == 1 and "method" not in eligible[0]:
                        bindings[index]["coordinates"][role] = _coordinate_binding(eligible[0], coordinate, role)
                    elif len(eligible) == 1 and derived is not None:
                        from sciplot_core.semantic_sources.rheology_frequency_metrics import validate_complex_viscosity_units
                        from sciplot_core.plot_transforms.units import canonical_unit_token

                        target = coordinate.get("unit") or derived["unit"]
                        inputs = derived["inputs"]
                        try:
                            validate_complex_viscosity_units(frequency_unit=canonical_unit_token(inputs["angular_frequency"]["unit"]),
                                storage_unit=canonical_unit_token(inputs["storage_modulus"]["unit"]),
                                loss_unit=canonical_unit_token(inputs["loss_modulus"]["unit"]), output_unit=target)
                        except ValueError as exc:
                            error = TaskControlError("semantic_derivation_unit_incompatible", str(exc))
                            error.repair = {"action": "revise_intent", "message": "The selected derivation needs explicit registered frequency/modulus/output units; no input unit or magnitude was inferred."}
                            raise error from exc
                        resolved_derived = {**deepcopy(derived), "inputs": {quantity: _coordinate_binding(column,
                            {"quantity": quantity, "unit": column["unit"]}, quantity) for quantity, column in inputs.items()}}
                        bindings[index]["coordinates"][role] = {"quantity": coordinate["quantity"], "unit": target,
                            "derivation": resolved_derived}
                    groups.append({"source_id": _source["source_id"], "table_id": candidate["candidate_id"],
                                   "block_id": block["block_id"], "columns": eligible,
                                   "available_columns": [{key: column[key] for key in ("column_id", "header", "quantity", "unit")} for column in columns],
                                   **({"available_derivation": derived} if derived else {})})
                    index += 1
        if all(len(group["columns"]) == 1 for group in groups):
            continue
        common = set.intersection(*(set(column["header"] for column in group["columns"] if "header" in column) for group in groups)) if groups else set()
        headers = [header for header in sorted(common) if all(sum(column.get("header") == header for column in group["columns"]) == 1 for group in groups)]
        if headers and not any(field in intent[role] for field in ("header", "headers", "column_id")):
            decisions.append({"field": role + "_header", "options": headers,
                              "message": "Select the exact observed original column header for this coordinate; units alone do not choose a response."})
            continue
        error = TaskControlError("semantic_coordinate_mapping_required", "This source needs a more specific original coordinate binding. Revise this same draft with exact original headers/column_id; no column was silently selected.")
        error.issues = [{"path": "/intent/" + role, "constraint": "unique_original_coordinate", "source_blocks": groups}]
        error.repair = {"action": "choose_original_coordinate", "supported_selectors": ["intent." + role + ".header", "intent." + role + ".headers", "intent." + role + ".column_id"],
                        "draft_correction": {"action": "revise_intent", "message": "Use exact observed headers (headers lists may bind differently named sample blocks), preserving the declared quantity. A known component cannot be relabelled as magnitude. Missing original units require a separately confirmed source_unit."}}
        derivations = [group for group in groups if "available_derivation" in group]
        if derivations:
            error.repair["available_derivations"] = derivations
            error.repair["draft_correction"] = {
                "action": "revise_intent", "omit_fields": ["intent." + role + ".header", "intent." + role + ".headers", "intent." + role + ".column_id"],
                "message": "To request the advertised source-derived quantity, retain its quantity/unit and omit a selector naming a different measured component. Revise this same task with its current expected_intent_revision; never relabel a real or imaginary component as magnitude."}
        raise error
    return decisions, bindings, views


def prepare_plan(paths: list[Path], intent: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables
    from sciplot_core.task_semantic_selection import select_source_blocks, source_observation_scope

    adapter = scientific_adapter(intent)
    scope = source_observation_scope(paths, intent.get("selection"))
    sources = []
    for index, path in enumerate(paths):
        observed_sheets = scope[f"source:{index}"]["observed_sheets"] if scope is not None else None
        if observed_sheets == []:
            continue
        evidence = inspect_semantic_tables(path, rule_id=intent.get("rule_id"), sheets=observed_sheets)
        if scope is not None and evidence["sha256"] != scope[f"source:{index}"]["sha256"]:
            raise ValueError("Source bytes changed after resolving table observation scope.")
        if not evidence["candidates"]:
            raise TaskControlError("semantic_table_not_found", "No byte-bound named numeric table was found. Preserve the original and inspect its supported original-table layout; a scientific adapter cannot be replaced with an ordinary XY importer.")
        source = {"source_id": f"source:{index}", "path": str(path), "name": path.name,
                  "sha256": evidence["sha256"], "candidates": evidence["candidates"],
                  "scientific_identity": evidence["scientific_identity"]}
        sources.append(source)
    sources, selection = select_source_blocks(sources, intent.get("selection"))
    if scope is not None:
        selection["observation_scope"] = list(scope.values())
    for source in sources:
        for candidate in source["candidates"]:
            stage_evidence(source, candidate)
    plan = {"sources": sources, "selection": selection, "intent": intent,
            "authority": "Preparation evidence only. Confirmed source facts compile into the existing Managed document; original bytes stay immutable.",
            "raw_data": "original bytes retained; selected original blocks and explicit exclusions are recorded; source row bounds are zero-based and data_end_row is exclusive. point_count and selected_point_count count physical row positions in the confirmed original region, including missing coordinates; they are not finite measurement counts",
            "interpolation": "Display interpolation retains raw marker points; gaps and non-increasing time boundaries remain separate runs."}
    return _resolve_plan(plan, intent, {}, adapter)


def _plan_decisions(sources: list[dict[str, Any]], intent: dict[str, Any], choices: dict[str, Any], adapter: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    from sciplot_core.task_semantic_temperature import temperature_decisions, temperature_selector

    temperature_selector(intent, choices)
    multiple = {source["source_id"]: [candidate["candidate_id"] for candidate in source["candidates"]]
                for source in sources if len(source["candidates"]) > 1}
    if multiple:
        return [{"field": "tables", "options": multiple,
                 "message": "Choose one exact original table candidate for every listed source before coordinate validation. No alternative was silently excluded."}], [], []
    decisions, bindings, views = _coordinate_decisions(sources, intent, choices, adapter)
    if (adapter or intent.get("stages")) and intent["x"]["quantity"] == "time":
        from sciplot_core.task_semantic_figure import _source_views

        for source in sources:
            for candidate in source["candidates"]:
                stage_evidence(source, candidate, bindings)
        views = _source_views(sources, choices, intent)
    segmented = bool(adapter or intent.get("stages")) and any((any(sum(stage["block_id"] == block["block_id"] for stage in candidate["stages"]) > 1 for block in candidate["blocks"])
                     if candidate.get("format") == "sample_column_blocks" and len({block["sample"] for block in candidate["blocks"]}) > 1
                     else len(candidate["stages"]) > 1)
                    for source in sources for candidate in source["candidates"])
    decisions.extend(temperature_decisions(sources, intent, segmented, choices))
    if intent.get("secondary_y") and len(sources) > 1 and "temperature_source" not in intent:
        decisions.append({"field": "temperature_source", "options": [source["source_id"] for source in sources],
                          "message": "Choose the exact recorded attachment for the right-axis temperature; other schedules are not assumed equal."})
    if segmented and intent["x"]["quantity"] == "time":
        if (intent.get("stages") or {}).get("mode") != "concatenate":
            decisions.append({"field": "stage_mode", "options": ["concatenate"],
                              "message": "The originals contain multiple acquisition stages/time resets. Confirm cumulative stage assembly; no stage may be silently dropped."})
        if "order" not in intent.get("stages", {}):
            order_options = ["source_order"]
            if all(candidate["temperature_continuity"] for source in sources for candidate in source["candidates"]):
                order_options.append("temperature_continuity")
            decisions.append({"field": "stage_order", "options": order_options,
                              "message": "Confirm stage order from source evidence. Temperature continuity is an explicit proposal, never an automatic experiment interpretation."})
        if "boundary" not in intent.get("stages", {}):
            decisions.append({"field": "time_boundary", "options": ["preserve_endpoint", "next_sample"],
                "message": "preserve_endpoint retains both boundary points at equal cumulative time; next_sample also retains both and advances by the entering stage's first measured positive sample interval. Neither policy invents measurements."})
    return decisions, bindings, views


def selected_table_plan(plan: dict[str, Any], intent: dict[str, Any], choices: dict[str, Any]) -> dict[str, Any]:
    """Resolve the current advertised choices through the same scientific owner."""
    return _resolve_plan(plan, intent, choices, scientific_adapter(intent))


def _resolve_plan(plan: dict[str, Any], intent: dict[str, Any], choices: dict[str, Any], adapter: str | None) -> dict[str, Any]:
    """Resolve one confirmed plan; lowering never interprets source layout again."""
    from sciplot_core.task_semantic_figure import _source_candidate
    from sciplot_core.task_semantic_temperature import temperature_column, temperature_selector
    from sciplot_core.task_semantic_frequency import frequency_coordinate

    selected = deepcopy(plan)
    selected["resolution_version"] = 1
    for name in ("resolved_bindings", "resolved_axes", "resolved_views", "resolved_rule_id", "resolved_choices"):
        selected.pop(name, None)
    if not any(len(source["candidates"]) > 1 and source["source_id"] not in choices.get("tables", {}) for source in selected["sources"]):
        selected["sources"] = [{**source, "candidates": [_source_candidate(source, choices)]} for source in selected["sources"]]
    decisions, bindings, source_views = _plan_decisions(selected["sources"], intent, choices, adapter)
    selected["decisions"] = [decision for decision in decisions if decision["field"] not in choices]
    if selected["decisions"]:
        return selected
    selector = temperature_selector(intent, choices)
    views = []
    for source, candidate in source_views:
        header = selector.get("header")
        if header is None and "column_id" in selector:
            observed = {temperature_column(candidate, block, selector)["header"] for block in candidate["blocks"]}
            header = next(iter(observed)) if len(observed) == 1 else None
        stages = ordered_stages(candidate, intent, choices, header)
        views.append({"source_id": source["source_id"], "source_path": source["path"], "source_sha256": source["sha256"],
                      "table_id": candidate["candidate_id"], "block_ids": [block["block_id"] for block in candidate["blocks"]],
                      "table_selection": deepcopy(candidate["table_selection"]), "sample_view": candidate.get("sample_view", False),
                      "curve_coordinates": deepcopy(candidate.get("curve_coordinates", {})), "stages": deepcopy(stages)})
        if intent.get("secondary_y") or intent.get("stages", {}).get("order", choices.get("stage_order")) == "temperature_continuity":
            for block in candidate["blocks"]:
                item = resolved_binding(bindings, source, candidate, block)
                coordinate = {"quantity": "temperature", **intent.get("secondary_y", {})}
                item["coordinates"]["temperature"] = _coordinate_binding(temperature_column(candidate, block, selector), coordinate, "temperature")
    axes = {}
    for role, coordinate in (("x", intent["x"]), ("y", intent["y"]), *(([("temperature", intent["secondary_y"])] if intent.get("secondary_y") else []))):
        units = {item["coordinates"][role]["unit"] for item in bindings}
        if len(units) != 1:
            raise TaskControlError("semantic_unit_ambiguous", "All selected curves on an axis need one declared output unit; revise this same draft.")
        unit = next(iter(units))
        resolved = {**deepcopy(coordinate), "unit": unit, "scale": coordinate.get("scale", "linear"), "direction": coordinate.get("direction", "ascending")}
        if adapter == "rheology_frequency":
            resolved = frequency_coordinate(role, {**coordinate, "unit": unit}, unit)
        axes[role] = resolved
    temperature_source = f'source:{intent["temperature_source"]}' if "temperature_source" in intent else choices.get("temperature_source", selected["sources"][0]["source_id"])
    if temperature_source not in {source["source_id"] for source in selected["sources"]}:
        raise TaskControlError("semantic_temperature_source_invalid", "The requested right-axis source is outside the confirmed attachment list.")
    if intent.get("secondary_y"):
        original = next(source for source in selected["sources"] if source["source_id"] == temperature_source)
        attached = [view["source_id"] for view in views if view["source_path"] == original["path"] and view["source_sha256"] == original["sha256"]]
        if len(attached) != 1:
            raise TaskControlError("semantic_temperature_source_invalid", "Select one original curve for the right-axis temperature; independent schedules cannot be silently substituted.")
        temperature_source = attached[0]
    selected.update(resolved_bindings=bindings, resolved_axes=axes, resolved_views=views,
                    resolved_rule_id=intent.get("rule_id", "ordinary_xy"), resolved_choices=deepcopy(choices),
                    temperature_source=temperature_source, stage_boundary=intent.get("stages", {}).get("boundary", choices.get("time_boundary")))
    return selected
