"""Compile a confirmed semantic task into the existing Binding/FigureSpec contracts."""
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_transforms import builtin_executor, execute_node
from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_coordinates import resolved_binding
from sciplot_core.task_semantic_stages import stage_execution_error, validate_stage_domains
from sciplot_core.plot_document.errors import DocumentError


def _error(code: str, message: str, **facts: Any) -> NoReturn:
    error = TaskControlError(code, message)
    error.issues = [{"path": "/intent", "constraint": code, **facts}]
    error.repair = {"action": "revise_intent", "message": "Preserve this task and the original source. Correct the complete uncommitted intent using its current intent_revision; no source or coordinate is replaced automatically."}
    raise error


def _select_column(candidate: dict[str, Any], block: dict[str, Any], coordinate: dict[str, Any], role: str) -> dict[str, Any]:
    """Validate a resolved literal column; lowering cannot reinterpret quantity."""
    columns = block.get("columns") or [column for column in candidate["columns"] if column["column_index"] in block["column_indices"]]
    exact = [column for column in columns if all(column[field] == coordinate[field] for field in ("column_id", "column_index", "header"))
             and column["quantity"] == coordinate["observed_quantity"] and column["unit"] == coordinate["observed_unit"]]
    if len(exact) != 1:
        _error("semantic_resolved_binding_changed", "An original coordinate differs from its resolved source binding; no replacement column was chosen.",
               role=role, block_id=block["block_id"])
    from sciplot_core.plot_document.errors import DocumentError
    from sciplot_core.plot_transforms.unit_relations import requires_unit_context, resolve_unit_relation

    relation = coordinate["unit_relation"]
    if relation["from_unit"] != coordinate["source_unit"] or relation["to_unit"] != coordinate["unit"]:
        _error("semantic_resolved_binding_changed", "The resolved unit relation differs from its exact coordinate binding.", role=role)
    if coordinate["source_unit"] == coordinate["unit"] and (relation["kind"] != "identity" or relation["factor"] != 1 or relation["offset"] != 0 or relation["canonical_from_unit"] != relation["canonical_to_unit"]):
        _error("semantic_resolved_binding_changed", "An unchanged original unit does not match its resolved identity relation.", role=role)
    if requires_unit_context(coordinate["source_unit"], coordinate["unit"]):
        context = coordinate.get("unit_context")
        if context is None and coordinate["quantity"] == "temperature" and coordinate["observed_quantity"] != "temperature":
            _error("semantic_unit_context_confirmation_required", "This uncommitted legacy C binding has no recorded source temperature or exact selected user quantity fact. Reconfirm it through revise_intent; its old draft was not reinterpreted.", role=role)
        if context is not None and (context.get("version") != 1 or any(
                context.get(field) != coordinate[key] for field, key in (
                    ("quantity", "quantity"), ("observed_quantity", "observed_quantity"), ("source_header", "header")))
                or type(context.get("explicit_quantity_binding")) is not bool):
            _error("semantic_resolved_binding_changed", "The frozen unit context differs from its exact source coordinate.", role=role)
        try:
            admitted = resolve_unit_relation(coordinate["source_unit"], coordinate["unit"],
                quantity=coordinate["quantity"], observed_quantity=coordinate["observed_quantity"],
                explicit_quantity_binding=context["explicit_quantity_binding"] if context else False)
        except DocumentError:
            _error("semantic_unit_context_confirmation_required", "This uncommitted coordinate lacks a supported unit context. Explicitly reconfirm its quantity and exact original selector with revise_intent in this same draft; no saved request or source value was changed.", role=role)
        if admitted != relation:
            _error("semantic_resolved_binding_changed", "The frozen relation differs from its source-supported unit context; revise this same uncommitted draft.", role=role)
    return {**exact[0], "unit": coordinate["source_unit"]}


def _source_metadata(source: dict[str, Any], candidate: dict[str, Any], bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Archive missing-unit declarations through the existing metadata contract."""
    confirmations = []
    for binding in bindings:
        block = next(block for block in candidate["blocks"] if block["block_id"] == binding["block_id"])
        for role, coordinate in binding["coordinates"].items():
            if "derivation" in coordinate or coordinate["observed_unit"]:
                continue
            column = _select_column(candidate, block, coordinate, role)
            confirmation = {"source_sha256": source["sha256"], "sheet": candidate["sheet"],
                            "column_index": column["column_index"], "field": "unit", "value": column["unit"],
                            "evidence": {"kind": "user_statement", "asserted_by": "semantic_task_intent",
                                         "statement": f"intent.{role}.source_unit explicitly declares the original unit of {column['header']!r} as {column['unit']!r}; the original cell is absent."}}
            if confirmation not in confirmations:
                confirmations.append(confirmation)
    return confirmations


def _source_candidate(source: dict[str, Any], choices: dict[str, Any]) -> dict[str, Any]:
    candidates = source["candidates"]
    identifier = choices.get("tables", {}).get(source["source_id"], candidates[0]["candidate_id"] if len(candidates) == 1 else None)
    candidate = next((item for item in candidates if item["candidate_id"] == identifier), None)
    if candidate is None:
        _error("semantic_table_ambiguous", "Choose an advertised table candidate for each attachment.", source=source["source_id"])
    return dict(candidate)


def _original_samples(source: dict[str, Any], rule_id: str, selection: dict[str, Any],
                      columns: list[str] | None = None) -> set[str]:
    from sciplot_core.data_mapping.original_tables import source_table_snapshot
    from sciplot_core.data_mapping.table_choice import select_table

    snapshot = source_table_snapshot(Path(source["path"]), rule_id=rule_id, sheets=[selection["sheet"]])
    if snapshot is None:
        return set()
    metadata = select_table(snapshot, selection)
    return {column["sample"] for column in metadata["columns"] if column["sample"]
            and (columns is None or f"column:{column['index']}" in columns)}


def _source_views(sources: list[dict[str, Any]], choices: dict[str, Any], intent: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Project confirmed physical blocks without deriving a new source region."""
    if "curve_bindings" in intent:
        from sciplot_core.task_semantic_curve_bindings import bound_views

        return bound_views(sources, intent)
    views = []
    for source in sources:
        candidate = _source_candidate(source, choices)
        instrument = candidate.get("format") in {"instrument_intervals", "rheology_frequency_intervals"}
        concatenate = (intent["x"]["quantity"] == "time"
                       and intent.get("stages", {}).get("mode", choices.get("stage_mode")) == "concatenate")
        if instrument and concatenate:
            views.append((source, {**candidate, "sample_view": True}))
            continue
        if not instrument and (candidate.get("format") != "sample_column_blocks"
                               or len({block["sample"] for block in candidate["blocks"]}) <= 1):
            views.append((source, candidate))
            continue
        if intent.get("secondary_y") and len(candidate["blocks"]) > 1:
            _error("semantic_sample_secondary_unsupported", "A multi-sample table needs an explicit single original block for a secondary coordinate; sample schedules are not assumed interchangeable.")
        if intent.get("stages") and intent["x"]["quantity"] != "time":
            _error("semantic_sample_stage_intent_unsupported", "Sample column blocks are independent curves, not cumulative acquisition stages. A stage transform requires an explicit time coordinate within each sample.")
        if len(candidate["blocks"]) > 1 and intent.get("stages", {}).get("order", choices.get("stage_order")) == "temperature_continuity":
            _error("semantic_sample_stage_order_unsupported", "Sample blocks are independent curves. Temperature-continuity stage proposals currently require one selected original block; no samples are concatenated.")
        for block in candidate["blocks"]:
            view = {**candidate, "blocks": [block], "table_selection": block["table_selection"], "sample_view": True,
                    "stages": [stage for stage in candidate["stages"] if stage["block_id"] == block["block_id"]]}
            views.append(({**source, "source_id": source["source_id"] + ":" + block["block_id"]}, view))
    return views


def _resolved_views(plan: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]]:
    """Project the frozen views without invoking any scientific selector."""
    views = []
    for frozen in plan["resolved_views"]:
        sources = [source for source in plan["sources"] if (source["path"], source["sha256"]) == (frozen["source_path"], frozen["source_sha256"])]
        candidates = [candidate for source in sources for candidate in source["candidates"] if candidate["candidate_id"] == frozen["table_id"]]
        if len(sources) != 1 or len(candidates) != 1:
            _error("semantic_resolved_binding_changed", "The frozen original table is absent from this source plan.")
        original = candidates[0]
        by_block = {block["block_id"]: block for block in original["blocks"]}
        if any(identifier not in by_block for identifier in frozen["block_ids"]):
            _error("semantic_resolved_binding_changed", "The frozen original block is absent from this source plan.")
        blocks = [by_block[identifier] for identifier in frozen["block_ids"]]
        expected = blocks[0]["table_selection"] if frozen["sample_view"] and len(blocks) == 1 else original["table_selection"]
        if frozen["table_selection"] != expected:
            _error("semantic_resolved_binding_changed", "The original table region differs from its resolved plan.")
        by_id = {stage["stage_id"]: stage for stage in original["stages"]}
        if any(stage != by_id.get(stage["stage_id"]) for stage in frozen["stages"]):
            _error("semantic_resolved_binding_changed", "An original stage differs from its resolved plan.")
        candidate = {**original, "blocks": blocks, "table_selection": frozen["table_selection"],
                     "sample_view": frozen["sample_view"], "curve_coordinates": frozen["curve_coordinates"]}
        validate_stage_domains(plan, sources[0], candidate, frozen["stages"])
        views.append(({**sources[0], "source_id": frozen["source_id"]}, candidate, frozen["stages"]))
    return views


def build_request(state: dict[str, Any]) -> dict[str, Any]:
    intent, plan = state["request"]["intent"], state["semantic_plan"]

    temperature_source = plan["temperature_source"]
    executor = builtin_executor()
    transforms: list[dict[str, Any]] = []
    data_sources, records = [], []
    datasets: dict[str, Any] = {}
    def transform(kind: str, inputs: list[str], parameters: dict[str, Any]) -> str:
        index = len(transforms)
        output = f'derived:{index}'
        node = {"id": f'transform:{index}', "kind": kind, "inputs": inputs, "output": output,
                "parameters": parameters, "executor": executor, "determinism": "deterministic"}
        # The same registered builtins determine preview domains and later
        # resolve the authoritative Managed model; there is no AI numeric data.
        dataset, _key = execute_node(node, datasets)
        datasets[output] = dataset
        transforms.append(node)
        return output
    for source, candidate, stages in _resolved_views(plan):
        source_id = source["source_id"]
        curve_intent = {**intent, **candidate.get("curve_coordinates", {})}
        bound = [resolved_binding(plan["resolved_bindings"], source, candidate, block) for block in candidate["blocks"]]
        metadata = _source_metadata(source, candidate, bound)
        # Load through the existing Managed source adapter, including its exact
        # metadata and scientific lineage checks. This is preparation only.
        from sciplot_core.plot_engine.managed_sources import load_sources

        explicit_selection = "selection" in intent or candidate.get("sample_view") is True
        if not explicit_selection:
            # Retain the original source identities and graph for saved and
            # omitted-selection requests. Explicit selection binds below first.
            data_sources.append({"source_id": source_id, "path": source["path"], "sha256": source["sha256"],
                                 "table_selection": candidate["table_selection"],
                                 **({"metadata_confirmations": metadata} if metadata else {})})
            raw_document = {"scientific": {"data_sources": [data_sources[-1]], "mappings": {}, "transforms": []}}
            datasets.update(load_sources(raw_document, plan["resolved_rule_id"]))
        pieces = []
        stage_sources = {}
        units: dict[str, str] = {}
        raw_samples: set[str] = set()
        for stage in stages:
            block = next(item for item in candidate["blocks"] if item["block_id"] == stage["block_id"])
            coordinates = resolved_binding(plan["resolved_bindings"], source, candidate, block)["coordinates"]
            selected = {role: _select_column(candidate, block, coordinate, role) for role, coordinate in coordinates.items() if "derivation" not in coordinate}
            derived = coordinates["y"].get("derivation")
            derivation_inputs = {role: _select_column(candidate, block, coordinate, role) for role, coordinate in derived["inputs"].items()} if derived else {}
            if not derived and selected["x"]["column_id"] == selected["y"]["column_id"]:
                _error("semantic_coordinate_conflict", "X and Y must bind distinct original columns; no source is duplicated as another scientific quantity.")
            columns = list(dict.fromkeys(column["column_id"] for column in [*selected.values(), *derivation_inputs.values()]))
            if explicit_selection:
                stage_source = source_id if candidate.get("sample_view") and len(stages) == 1 else source_id + ":" + stage["stage_id"]
                region = {**deepcopy(block["table_selection"]),
                          "data_start_row": stage["data_start_row"], "data_end_row": stage["data_end_row"]}
                binding = {"source_id": stage_source, "path": source["path"], "sha256": source["sha256"],
                           "table_selection": region, **({"metadata_confirmations": metadata} if metadata else {})}
                # The same validated select persisted in the Managed graph
                # restricts numeric loading before any coordinate transform.
                first_select = {"id": f"transform:{len(transforms)}", "kind": "select", "inputs": [stage_source],
                                "output": f"derived:{len(transforms)}", "parameters": {"columns": columns},
                                "executor": executor, "determinism": "deterministic"}
                raw_document = {"scientific": {"data_sources": [binding], "mappings": {}, "transforms": [first_select]}}
                raw_samples.update(_original_samples(source, plan["resolved_rule_id"], region, columns))
                datasets.update(load_sources(raw_document, plan["resolved_rule_id"]))
                data_sources.append(binding)
                stage_sources[stage["stage_id"]] = stage_source
                current = transform("select", [stage_source], {"columns": columns})
            else:
                stage_sources[stage["stage_id"]] = source_id
                current = transform("select", [source_id], {"columns": columns})
                origin = candidate["table_selection"]["data_start_row"]
                current = transform("row_slice", [current], {"start": stage["data_start_row"] - origin,
                                                             "end": stage["data_end_row"] - origin})
            if derived:
                current = transform("rheology_complex_viscosity", [current], {
                    "frequency_column": derivation_inputs["angular_frequency"]["column_id"],
                    "storage_column": derivation_inputs["storage_modulus"]["column_id"],
                    "loss_column": derivation_inputs["loss_modulus"]["column_id"],
                    "output_column": "y", "output_unit": coordinates["y"]["unit"]})
            current = transform("rename", [current], {"columns": {column["column_id"]: {
                "id": role, "label": curve_intent["x" if role == "x" else "y"]["quantity"].title() if role != "temperature" else "Temperature"}
                for role, column in selected.items()}})
            for role, coordinate in coordinates.items():
                target = coordinate["unit"]
                if role in units and units[role] != target:
                    _error("semantic_unit_ambiguous", "Selected stages use different units; declare the requested coordinate unit explicitly.", role=role)
                units[role] = target
                if role in selected and selected[role]["unit"] != target:
                    current = transform("convert_unit", [current], {"columns": [role], "from_unit": selected[role]["unit"], "to_unit": target})
                    details = datasets[current]["provenance"]["transforms"][-1]["details"]
                    if any(details[field] != value for field, value in coordinate["unit_relation"].items() if field != "kind"):
                        _error("semantic_resolved_binding_changed", "The registered unit execution differs from its resolved scientific relation.", role=role)
            if derived:
                current = transform("select", [current], {"columns": list(coordinates)})
            pieces.append(current)
        if not pieces:
            _error("semantic_stage_missing", "The selected table has no source-supported stage.")
        if len(pieces) > 1:
            if intent["x"]["quantity"] != "time":
                _error("semantic_stage_unsupported", "Cumulative stage assembly requires an explicitly declared time coordinate.")
            boundary = plan["stage_boundary"]
            if boundary not in {"preserve_endpoint", "next_sample"}:
                _error("semantic_boundary_required", "Confirm the time boundary policy; no elapsed interval is inferred.")
            try:
                current = transform("concat_time", pieces, {"time_column": "x", "boundary": boundary, "first_origin": "preserve"})
            except DocumentError as exc:
                if exc.reason_code not in {"transform_stage_time_invalid", "transform_boundary_interval_missing"}:
                    raise
                raise stage_execution_error(exc, source, stages) from exc
        else:
            current = pieces[0]
        # Original sample metadata, when present, remains the scientific sample.
        if not explicit_selection:
            raw_samples = _original_samples(source, plan["resolved_rule_id"], candidate["table_selection"])
        if len(raw_samples) > 1:
            _error("semantic_sample_ambiguous", "One attachment contains multiple original samples; choose their distinct supported mapping rather than merging them.")
        literal = candidate["blocks"][0] if candidate.get("sample_view") else {}
        condition = bound[0]["condition"] if candidate.get("sample_view") and len(bound) == 1 else {}
        recorded_stages = []
        for stage in stages:
            block_binding = next(item for item in bound if item["block_id"] == stage["block_id"])
            physical = next(block for block in candidate["blocks"] if block["block_id"] == stage["block_id"])
            recorded_stages.append({**deepcopy(stage), "source_id": stage_sources[stage["stage_id"]], "table_selection": deepcopy(block_binding["table_selection"]),
                **({"source_interval": deepcopy(block_binding["condition"].get("source_interval", physical.get("source_interval")))}
                   if "source_interval" in physical or "source_interval" in block_binding["condition"] else {})})
        records.append({"source_id": source_id, "dataset_id": current, "units": units,
                        "sample": literal.get("sample") or next(iter(raw_samples), Path(source["path"]).stem),
                        **({"label": condition.get("label", literal.get("label"))} if condition.get("label") or literal.get("label") else {}), "stages": recorded_stages,
                        "quantities": {role: curve_intent[role]["quantity"] for role in ("x", "y")}})
    return _compose(state, records, data_sources, transforms, datasets, temperature_source)


def _compose(state: dict[str, Any], records: list[dict[str, Any]], sources: list[dict[str, Any]],
             transforms: list[dict[str, Any]], datasets: dict[str, Any], temperature_source: str) -> dict[str, Any]:
    intent = state["request"]["intent"]
    if "labels" in intent and len(intent["labels"]) != len(records):
        _error("semantic_label_count_mismatch", "Display labels must match the complete retained source-bound curve count and order. Correct this same draft; no label is silently omitted or attached to another sample.",
               expected=len(records), actual=len(intent["labels"]), samples=[record["sample"] for record in records])
    scales, axes, layers, slots = [], [], [], {}
    resolved_axes = state["semantic_plan"]["resolved_axes"]
    coordinates = [("x", resolved_axes["x"], "bottom"), ("y", resolved_axes["y"], "left")]
    if "secondary_y" in intent:
        coordinates.append(("temperature", resolved_axes["temperature"], "right"))
    for role, coordinate, side in coordinates:
        selected = records if role != "temperature" else [record for record in records if record["source_id"] == temperature_source]
        units = {record["units"][role] for record in selected}
        if len(units) != 1:
            _error("semantic_unit_ambiguous", "All series on an axis require one declared unit.", role=role, units=sorted(units))
        unit = next(iter(units))
        if coordinate["unit"] != unit:
            _error("semantic_resolved_binding_changed", "The compiled coordinate unit differs from its resolved axis.", role=role)
        values = [value for record in selected for value in datasets[record["dataset_id"]]["columns"][role]["values"] if value is not None]
        from sciplot_core.task_semantic_axes import ordinary_axis

        domain, ticks, label, scale_transform = ordinary_axis(role, coordinate, unit, values)
        scales.append({"id": "scale:" + role, "dimension": "x" if role == "x" else "y", "transform": scale_transform,
                       "domain": domain, "unit": unit, "quantity": coordinate["quantity"], "direction": coordinate.get("direction", "ascending"),
                       "domain_rule": {name: {"mode": "fixed", "value": coordinate[name]} if name in coordinate else {"mode": "auto"}
                                       for name in ("minimum", "maximum")},
                       **({"quantity_members": deepcopy(coordinate["quantity_members"])} if "quantity_members" in coordinate else {})})
        axes.append({"id": "axis:" + role, "scale_id": "scale:" + role, "side": side,
                     "label": label, "visible": True, "label_visible": True, "ticks": ticks, "ticks_mode": "automatic", "style": {}})
    def layer(record: dict[str, Any], index: int, *, temperature: bool = False) -> None:
        role = "temperature" if temperature else "y"
        identifier = "layer:temperature" if temperature else f"layer:response:{index}"
        label = "Temperature" if temperature else (intent.get("labels", [])[index] if index < len(intent.get("labels", [])) else record.get("label", record["sample"]))
        line = {"id": identifier + ":line", "type": "line", "style": {"line_color": "#888888", "line_style": "dash"} if temperature else {}}
        display = intent.get("display", {})
        if not temperature and display.get("interpolation"):
            line["interpolation"] = deepcopy(display["interpolation"])
        marks = [line]
        marks.append({"id": identifier + ":points", "type": "point", "style": {
            "marker_thin_factor": display.get("marker_every", 1), **({"marker_color": "#888888"} if temperature else {})}})
        layers.append({"id": identifier, "dataset_id": record["dataset_id"], "mappings": {"x": "x", "y": role},
                       "mapping_semantics": {"x": intent["x"]["quantity"], "y": "temperature" if temperature else record.get("quantities", {}).get("y", intent["y"]["quantity"])},
                       "x_scale": "scale:x", "y_scale": "scale:" + role, "marks": marks,
                       "role": "measurement", "label": label, "legend": {"visible": True, "label": label}, "z_order": index, "style": {}})
        slots[identifier] = {"series_id": identifier, "sample": record["sample"],
            "x": {"source_id": record["dataset_id"], "column": "x"},
            "y": {"source_id": record["dataset_id"], "column": role}, "x_unit": record["units"]["x"], "y_unit": record["units"][role]}
    for index, record in enumerate(records):
        layer(record, index)
    if "secondary_y" in intent:
        layer(next(record for record in records if record["source_id"] == temperature_source), len(records), temperature=True)
    figure: dict[str, Any] = {"domain_semantics": "current_view_v1", "axis_layout_policy": "decorated_secondary_sides_v1", "kind": "sciplot_figure_spec", "schema_version": 2, "id": "figure:main", "scales": scales,
              "views": [{"id": "view:main", "panel_label": None, "style": {}, "axes": axes, "layers": layers}],
              "composition": {"kind": "single", "rows": 1, "columns": 1,
                  "cells": [{"view_id": "view:main", "row": 0, "column": 0, "row_span": 1, "column_span": 1}],
                  "column_weights": [1], "row_weights": [1], "resolve": []},
              "layout": {}, "theme": {"project": {}, "figure": {}},
              "guides": [{"id": "guide:legend", "type": "legend", "scope": "view", "view_id": "view:main",
                  "layer_ids": [], "order": [], "labels": {}, "visible": True, "location": "bottom-right" if "secondary_y" in intent else "inside-best", "columns": 1, "style": {}}],
              "annotations": []}
    template = "semantic-task-v1"
    key = "task:" + canonical_json_sha256([state["task_dir"], state["intent_revision"]])
    from sciplot_core.plot_grammar import compile_figure
    from sciplot_core.rendering_contract import contract_binding, contract_value

    figure["rendering_contract"] = contract_binding()
    from sciplot_core.plot_grammar.current_view import resolve_current_view

    figure = resolve_current_view(figure, datasets)
    presets = contract_value("canvas.size_presets")
    width_candidates = sorted({float(item["width_mm"]) for item in presets.values()
                               if float(item["height_mm"]) == float(contract_value("canvas.height_mm"))})
    layout_attempts = []
    for width in width_candidates:
        figure["layout"]["width_mm"] = width
        try:
            compile_figure(figure, datasets, scientific_hash="0" * 64, presentation_hash="0" * 64)
            layout_attempts.append({"width_mm": width, "status": "fit"})
            break
        except ValueError as exc:
            if getattr(exc, "reason_code", "") not in {"figure_layout_legend_no_space", "layout_insufficient_plot_space", "layout_invalid_plot_extent"}:
                raise
            layout_attempts.append({"width_mm": width, "status": "no_space", "reason_code": getattr(exc, "reason_code", "")})
    else:
        _error("semantic_layout_no_space", "No declared house size preset fits the confirmed axes and legend. Preserve scientific content and choose an explicit supported composition.", attempts=layout_attempts)
    binding: dict[str, Any] = {"kind": "sciplot_binding", "schema_version": 1, "template_id": template,
               "data_sources": sources, "slots": slots, "transforms": transforms, "guards": {},
               "provenance": {"semantic_task": {"task": state["task_dir"], "intent_revision": state["intent_revision"],
                   "intent": deepcopy(intent), "choices": deepcopy(state.get("semantic_choices", {})),
                   "resolution": {"rule_id": state["semantic_plan"]["resolved_rule_id"], "axes": deepcopy(resolved_axes),
                                  "bindings": deepcopy(state["semantic_plan"]["resolved_bindings"])},
                   "layout_selection": {"policy": "first_fitting_house_width", "attempts": layout_attempts},
                   "stages": {record["source_id"]: record["stages"] for record in records}}}}
    if "selection" in state["semantic_plan"]:
        from sciplot_core.task_semantic_selection import selection_for_choices

        binding["provenance"]["semantic_task"]["selection"] = selection_for_choices(
            state["semantic_plan"]["selection"], state.get("semantic_choices", {}))
    request = {"idempotency_key": key, "template_definition": {"kind": "sciplot_figure_template", "schema_version": 2,
                   "template_id": template, "figure_spec": figure}, "data_binding": binding,
               "rule_id": state["semantic_plan"]["resolved_rule_id"]}
    from sciplot_core.output_contract import resolve_user_output_layout
    from sciplot_core.task_output_choice import creation_output

    output = resolve_user_output_layout(Path(sources[0]["path"]), requested_delivery_root=creation_output(state))
    request["out"] = str(output.workspace_root / "managed-artifacts" / canonical_json_sha256([state["task_dir"], state["intent_revision"]]))
    return request
