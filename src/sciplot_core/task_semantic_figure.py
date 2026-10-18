"""Compile a confirmed semantic task into the existing Binding/FigureSpec contracts."""
from copy import deepcopy
from collections.abc import Callable
import math
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_transforms import builtin_executor, execute_node
from sciplot_core.task_errors import TaskControlError


def _error(code: str, message: str, **facts: Any) -> NoReturn:
    error = TaskControlError(code, message)
    error.issues = [{"path": "/intent", "constraint": code, **facts}]
    raise error


def _select_column(candidate: dict[str, Any], block: dict[str, Any], quantity: str, *, header: str | None = None, column_id: str | None = None) -> dict[str, Any]:
    columns = [column for column in candidate["columns"] if column["column_index"] in block["column_indices"]]
    exact = [column for column in columns if column["quantity"] == quantity and (header is None or column["header"] == header)]
    if not exact and quantity not in {"time", "temperature"}:
        # The explicit semantic intent declares the response meaning; observed
        # unit/header/row facts still come exclusively from the original source.
        exact = [column for column in columns if column["column_id"] in block["response_columns"]
                 and column["quantity"] is None and (header is None or column["header"] == header)]
    if column_id is not None:
        exact = [column for column in exact if column["column_id"] == column_id]
    if len(exact) != 1:
        _error("semantic_column_ambiguous", "The requested coordinate does not identify exactly one original column in every selected stage. Revise the semantic intent; no column is selected by position.",
               quantity=quantity, block_id=block["block_id"], candidates=[column["header"] for column in exact])
    return dict(exact[0])


def _rule_id(intent: dict[str, Any]) -> str:
    if "rule_id" in intent:
        return str(intent["rule_id"])
    default = {"mass": "tga_curve", "absorbance": "uvvis_spectrum", "transmittance": "ftir_spectrum"}.get(intent["y"]["quantity"])
    if default is None:
        _error("semantic_rule_required", "Declare the experiment identity with --rule while retaining the requested coordinates; an unfamiliar quantity must not select an unrelated experiment.")
    return str(default)


def _canonical_unit(unit: str) -> str:
    from sciplot_core.plot_transforms.units import canonical_unit_token

    return canonical_unit_token(unit)


def _source_candidate(source: dict[str, Any], choices: dict[str, Any]) -> dict[str, Any]:
    candidates = source["candidates"]
    identifier = choices.get("tables", {}).get(source["source_id"], candidates[0]["candidate_id"] if len(candidates) == 1 else None)
    candidate = next((item for item in candidates if item["candidate_id"] == identifier), None)
    if candidate is None:
        _error("semantic_table_ambiguous", "Choose an advertised table candidate for each attachment.", source=source["source_id"])
    return dict(candidate)


def _ordered_stages(candidate: dict[str, Any], intent: dict[str, Any], choices: dict[str, Any], header: str | None) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = candidate["stages"]
    if len(stages) <= 1:
        return stages
    mode = intent.get("stages", {}).get("mode", choices.get("stage_mode"))
    if mode != "concatenate":
        _error("semantic_stage_choice_required", "Multiple original stages require explicit cumulative assembly; no stage is silently discarded.")
    strategy = intent.get("stages", {}).get("order", choices.get("stage_order"))
    if strategy == "temperature_continuity":
        suggestions = candidate["temperature_continuity"]
        suggestion = suggestions.get(header) if header is not None else next(iter(suggestions.values())) if len(suggestions) == 1 else None
        if suggestion is None:
            _error("semantic_stage_order_ambiguous", "No unique temperature-continuity proposal exists for this exact selected temperature role. Choose explicit source order or provide a source-supported mapping.")
        order = suggestion["order"]
        return [next(stage for stage in stages if stage["stage_id"] == identifier) for identifier in order]
    if strategy == "source_order":
        return stages
    _error("semantic_stage_choice_required", "Confirm one advertised stage order.")


def _domain(values: list[float], coordinate: dict[str, Any]) -> list[float]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        _error("semantic_empty_coordinate", "The selected coordinate has no finite observations.")
    low, high = min(finite), max(finite)
    span = high - low or max(abs(high) * .05, 1)
    default_low = low if coordinate["quantity"] == "time" else low - span * .05
    default_high = high + span * .05
    lower, upper = coordinate.get("minimum", default_low), coordinate.get("maximum", default_high)
    if lower >= upper:
        _error("semantic_invalid_domain", "The confirmed axis bounds must be strictly increasing.", minimum=lower, maximum=upper)
    return [float(lower), float(upper)]


def _ticks(domain: list[float]) -> list[float]:
    low, high = domain
    magnitude = 10 ** math.floor(math.log10((high - low) / 5))
    step = next((item * magnitude for item in (1, 2, 2.5, 5, 10) if item * magnitude >= (high - low) / 5))
    first = math.ceil(low / step) * step
    return [round(first + index * step, 12) for index in range(12) if first + index * step <= high + step * 1e-9]


def _original_samples(source: dict[str, Any], rule_id: str, selection: dict[str, Any],
                      columns: list[str] | None = None) -> set[str]:
    from sciplot_core.data_mapping.table_choice import source_table_snapshot, select_table

    snapshot = source_table_snapshot(Path(source["path"]), rule_id=rule_id)
    if snapshot is None:
        return set()
    metadata = select_table(snapshot, selection)
    return {column["sample"] for column in metadata["columns"] if column["sample"]
            and (columns is None or f"column:{column['index']}" in columns)}


def build_request(state: dict[str, Any]) -> dict[str, Any]:
    intent, plan, choices = state["request"]["intent"], state["semantic_plan"], state.get("semantic_choices", {})
    temperature_header = intent.get("temperature_header", choices.get("temperature_header"))
    temperature_source = (f'source:{intent["temperature_source"]}' if "temperature_source" in intent
                          else choices.get("temperature_source", plan["sources"][0]["source_id"]))
    if temperature_source not in {source["source_id"] for source in plan["sources"]}:
        _error("semantic_temperature_source_invalid", "The requested right-axis source is outside the confirmed attachment list.")
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
    for source in plan["sources"]:
        candidate = _source_candidate(source, choices)
        source_id = source["source_id"]
        # Load through the existing Managed source adapter, including its exact
        # metadata and scientific lineage checks. This is preparation only.
        from sciplot_core.plot_engine.managed_sources import load_sources

        explicit_selection = "selection" in intent
        if not explicit_selection:
            # Retain the original source identities and graph for saved and
            # omitted-selection requests. Explicit selection binds below first.
            data_sources.append({"source_id": source_id, "path": source["path"], "sha256": source["sha256"],
                                 "table_selection": candidate["table_selection"]})
            raw_document = {"scientific": {"data_sources": [data_sources[-1]], "mappings": {}, "transforms": []}}
            datasets.update(load_sources(raw_document, _rule_id(intent)))
        stages = _ordered_stages(candidate, intent, choices, temperature_header)
        pieces = []
        units: dict[str, str] = {}
        raw_samples: set[str] = set()
        for stage in stages:
            block = next(item for item in candidate["blocks"] if item["block_id"] == stage["block_id"])
            x = _select_column(candidate, block, intent["x"]["quantity"],
                               header=intent["x"].get("header", choices.get("x_header")), column_id=intent["x"].get("column_id"))
            y = _select_column(candidate, block, intent["y"]["quantity"],
                               header=intent["y"].get("header", choices.get("y_header")), column_id=intent["y"].get("column_id"))
            if x["column_id"] == y["column_id"]:
                _error("semantic_coordinate_conflict", "X and Y must bind distinct original columns; no source is duplicated as another scientific quantity.")
            selected = {"x": x, "y": y}
            if intent.get("secondary_y") or intent.get("stages", {}).get("order", choices.get("stage_order")) == "temperature_continuity":
                selected["temperature"] = _select_column(candidate, block, "temperature", header=temperature_header)
            columns = list(dict.fromkeys(column["column_id"] for column in selected.values()))
            if explicit_selection:
                stage_source = source_id + ":" + stage["stage_id"]
                region = {**deepcopy(candidate["table_selection"]),
                          "data_start_row": stage["data_start_row"], "data_end_row": stage["data_end_row"]}
                binding = {"source_id": stage_source, "path": source["path"], "sha256": source["sha256"],
                           "table_selection": region}
                # The same validated select persisted in the Managed graph
                # restricts numeric loading before any coordinate transform.
                first_select = {"id": f"transform:{len(transforms)}", "kind": "select", "inputs": [stage_source],
                                "output": f"derived:{len(transforms)}", "parameters": {"columns": columns},
                                "executor": executor, "determinism": "deterministic"}
                raw_document = {"scientific": {"data_sources": [binding], "mappings": {}, "transforms": [first_select]}}
                raw_samples.update(_original_samples(source, _rule_id(intent), region, columns))
                datasets.update(load_sources(raw_document, _rule_id(intent)))
                data_sources.append(binding)
                current = transform("select", [stage_source], {"columns": columns})
            else:
                current = transform("select", [source_id], {"columns": columns})
                origin = candidate["table_selection"]["data_start_row"]
                current = transform("row_slice", [current], {"start": stage["data_start_row"] - origin,
                                                             "end": stage["data_end_row"] - origin})
            current = transform("rename", [current], {"columns": {column["column_id"]: {
                "id": role, "label": intent["x" if role == "x" else "y"]["quantity"].title() if role != "temperature" else "Temperature"}
                for role, column in selected.items()}})
            for role, column in selected.items():
                target = (intent["x"].get("unit") if role == "x" else intent["y"].get("unit") if role == "y" else
                          intent.get("secondary_y", {}).get("unit")) or _canonical_unit(column["unit"])
                if role in units and units[role] != target:
                    _error("semantic_unit_ambiguous", "Selected stages use different units; declare the requested coordinate unit explicitly.", role=role)
                units[role] = target
                if column["unit"] != target:
                    current = transform("convert_unit", [current], {"columns": [role], "from_unit": column["unit"], "to_unit": target})
            pieces.append(current)
        if not pieces:
            _error("semantic_stage_missing", "The selected table has no source-supported stage.")
        if len(pieces) > 1:
            if intent["x"]["quantity"] != "time":
                _error("semantic_stage_unsupported", "Cumulative stage assembly requires an explicitly declared time coordinate.")
            boundary = intent.get("stages", {}).get("boundary", choices.get("time_boundary"))
            if boundary not in {"preserve_endpoint", "next_sample"}:
                _error("semantic_boundary_required", "Confirm the time boundary policy; no elapsed interval is inferred.")
            current = transform("concat_time", pieces, {"time_column": "x", "boundary": boundary, "first_origin": "preserve"})
        else:
            current = pieces[0]
        # Original sample metadata, when present, remains the scientific sample.
        if not explicit_selection:
            raw_samples = _original_samples(source, _rule_id(intent), candidate["table_selection"])
        if len(raw_samples) > 1:
            _error("semantic_sample_ambiguous", "One attachment contains multiple original samples; choose their distinct supported mapping rather than merging them.")
        records.append({"source_id": source_id, "dataset_id": current, "units": units,
                        "sample": next(iter(raw_samples), Path(source["path"]).stem), "stages": stages})
    return _compose(state, records, data_sources, transforms, datasets, temperature_source)


def _compose(state: dict[str, Any], records: list[dict[str, Any]], sources: list[dict[str, Any]],
             transforms: list[dict[str, Any]], datasets: dict[str, Any], temperature_source: str,
             *, axis_policy: Callable[[str, dict[str, Any], str, list[float]], tuple[list[float], list[float], str, str]] | None = None) -> dict[str, Any]:
    intent = state["request"]["intent"]
    scales, axes, layers, slots = [], [], [], {}
    coordinates = [("x", intent["x"], "bottom"), ("y", intent["y"], "left")]
    if "secondary_y" in intent:
        coordinates.append(("temperature", intent["secondary_y"], "right"))
    for role, coordinate, side in coordinates:
        selected = records if role != "temperature" else [record for record in records if record["source_id"] == temperature_source]
        units = {record["units"][role] for record in selected}
        if len(units) != 1:
            _error("semantic_unit_ambiguous", "All series on an axis require one declared unit.", role=role, units=sorted(units))
        unit = next(iter(units))
        values = [value for record in selected for value in datasets[record["dataset_id"]]["columns"][role]["values"] if value is not None]
        if axis_policy is not None:
            domain, ticks, label, scale_transform = axis_policy(role, coordinate, unit, values)
        else:
            domain = _domain(values, coordinate)
            ticks, scale_transform = _ticks(domain), "linear"
            label_unit = "°C" if unit == "C" else unit
            label = coordinate["quantity"].title() + (f" ({label_unit})" if unit else "")
        scales.append({"id": "scale:" + role, "dimension": "x" if role == "x" else "y", "transform": scale_transform,
                       "domain": domain, "unit": unit, "quantity": coordinate["quantity"], "direction": "ascending"})
        axes.append({"id": "axis:" + role, "scale_id": "scale:" + role, "side": side,
                     "label": label, "visible": True, "label_visible": True, "ticks": ticks, "style": {}})
    def layer(record: dict[str, Any], index: int, *, temperature: bool = False) -> None:
        role = "temperature" if temperature else "y"
        identifier = "layer:temperature" if temperature else f"layer:response:{index}"
        label = "Temperature" if temperature else (intent.get("labels", [])[index] if index < len(intent.get("labels", [])) else record.get("label", record["sample"]))
        line = {"id": identifier + ":line", "type": "line", "style": {"line_color": "#888888", "line_style": "dash"} if temperature else {}}
        display = intent.get("display", {})
        if not temperature and display.get("interpolation"):
            line["interpolation"] = deepcopy(display["interpolation"])
        marks = [line]
        if not temperature:
            marks.append({"id": identifier + ":points", "type": "point", "style": {"marker_thin_factor": display.get("marker_every", 1)}})
        layers.append({"id": identifier, "dataset_id": record["dataset_id"], "mappings": {"x": "x", "y": role},
                       "mapping_semantics": {"x": intent["x"]["quantity"], "y": "temperature" if temperature else intent["y"]["quantity"]},
                       "x_scale": "scale:x", "y_scale": "scale:" + role, "marks": marks,
                       "role": "measurement", "label": label, "legend": {"visible": True, "label": label}, "z_order": index, "style": {}})
        slots[identifier] = {"series_id": identifier, "sample": record["sample"],
            "x": {"source_id": record["dataset_id"], "column": "x"},
            "y": {"source_id": record["dataset_id"], "column": role}, "x_unit": record["units"]["x"], "y_unit": record["units"][role]}
    for index, record in enumerate(records):
        layer(record, index)
    if "secondary_y" in intent:
        layer(next(record for record in records if record["source_id"] == temperature_source), len(records), temperature=True)
    figure: dict[str, Any] = {"axis_layout_policy": "decorated_secondary_sides_v1", "kind": "sciplot_figure_spec", "schema_version": 2, "id": "figure:main", "scales": scales,
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
                   "layout_selection": {"policy": "first_fitting_house_width", "attempts": layout_attempts},
                   "stages": {record["source_id"]: record["stages"] for record in records}}}}
    if "selection" in state["semantic_plan"]:
        from sciplot_core.task_semantic_selection import selection_for_choices

        binding["provenance"]["semantic_task"]["selection"] = selection_for_choices(
            state["semantic_plan"]["selection"], state.get("semantic_choices", {}))
    request = {"idempotency_key": key, "template_definition": {"kind": "sciplot_figure_template", "schema_version": 2,
                   "template_id": template, "figure_spec": figure}, "data_binding": binding,
               "rule_id": _rule_id(intent)}
    from sciplot_core.output_contract import resolve_user_output_layout
    from sciplot_core.task_output_choice import creation_output

    output = resolve_user_output_layout(Path(sources[0]["path"]), requested_delivery_root=creation_output(state))
    request["out"] = str(output.workspace_root / "managed-artifacts" / canonical_json_sha256([state["task_dir"], state["intent_revision"]]))
    return request
