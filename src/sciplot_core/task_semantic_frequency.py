"""Bind original frequency intervals into the existing Managed transform graph."""
from copy import deepcopy
import math
from typing import Any

from sciplot_core.plot_transforms import builtin_executor, execute_node
from sciplot_core.task_semantic_figure import _canonical_unit, _compose, _error, _rule_id, _source_candidate


def frequency_axis(role: str, coordinate: dict[str, Any], unit: str, values: list[float]) -> tuple[list[float], list[float], str, str]:
    """Use the shared frequency label/tick policy with strict positive log data."""
    from sciplot_core.materials_rules.unit_formatting import format_unit_label
    from sciplot_core.policy.axis_defaults import RHEOLOGY_FREQUENCY_X_LABEL, anchored_log_decade_ticks
    from sciplot_core.source_tables.text_normalization import normalize_label
    from sciplot_core.task_semantic_figure import _domain, _ticks

    quantity = coordinate["quantity"]
    if role == "x" and quantity == "angular_frequency":
        label = RHEOLOGY_FREQUENCY_X_LABEL if unit == "rad/s" else "f (Hz)" if unit == "Hz" else f"Angular Frequency ({format_unit_label(unit)})"
    else:
        # Managed grammar labels are literal text; legacy Veusz TeX policy
        # strings would be escaped and visibly print their backslashes.
        label = normalize_label(quantity.replace("_", " "))
        if unit and unit != "1":
            label += " (" + format_unit_label(unit) + ")"
    if quantity in {"loss_factor", "temperature"}:
        domain = _domain(values, coordinate)
        return domain, _ticks(domain), label, "linear"
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        _error("semantic_frequency_log_domain", "Frequency logarithmic axes require strictly positive finite observations; no scientific point is clipped or dropped.", quantity=quantity)
    low, high = min(values), max(values)
    domain = [float(coordinate.get("minimum", low / 1.05)), float(coordinate.get("maximum", high * 1.05))]
    if not 0 < domain[0] < domain[1]:
        _error("semantic_frequency_log_domain", "Declared frequency logarithmic axis bounds must be positive and strictly increasing.", quantity=quantity)
    ticks = [value for value in anchored_log_decade_ticks(values) if domain[0] <= value <= domain[1]]
    return domain, ticks, label, "log"


def build_frequency_request(state: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.plot_engine.managed_sources import load_sources

    intent = state["request"]["intent"]
    if intent["x"]["quantity"] != "angular_frequency" or intent.get("secondary_y") or intent.get("stages"):
        _error("semantic_frequency_intent_unsupported", "Original frequency intervals retain distinct conditions. Use angular_frequency and one response, without cumulative time stages or a secondary axis.")
    executor = builtin_executor()
    sources, records, nodes = [], [], []
    datasets: dict[str, Any] = {}

    def transform(kind: str, source_id: str, parameters: dict[str, Any]) -> str:
        output = f"derived:{len(nodes)}"
        node = {"id": f"transform:{len(nodes)}", "kind": kind, "inputs": [source_id],
                "output": output, "parameters": parameters, "executor": executor, "determinism": "deterministic"}
        datasets[output], _key = execute_node(node, datasets)
        nodes.append(node)
        return output

    for source in state["semantic_plan"]["sources"]:
        candidate = _source_candidate(source, state.get("semantic_choices", {}))
        if candidate.get("format") != "rheology_frequency_intervals":
            _error("semantic_frequency_mixed_formats", "Bind frequency instrument intervals together; mixed acquisition formats need an explicit original mapping.")
        for block in candidate["blocks"]:
            selected = {}
            derived = block.get("derived_coordinates", {}).get(intent["y"]["quantity"])
            for role in ("x", "y"):
                coordinate = intent[role]
                columns = [column for column in block["columns"] if column["quantity"] == coordinate["quantity"]]
                for field in ("header", "column_id"):
                    value = coordinate.get(field, state.get("semantic_choices", {}).get(role + "_header") if field == "header" else None)
                    if value is not None:
                        columns = [column for column in columns if column[field] == value]
                if role == "y" and not columns and derived and not any(field in coordinate for field in ("header", "column_id")):
                    selected.update(derived["inputs"])
                    continue
                if len(columns) != 1:
                    _error("semantic_column_ambiguous", "Choose an exact original frequency coordinate; a viscosity component cannot stand for magnitude.", role=role)
                selected[role] = columns[0]
            identifiers = list(dict.fromkeys(column["column_id"] for column in selected.values()))
            source_id = source["source_id"] + ":" + block["block_id"]
            binding = {"source_id": source_id, "path": source["path"], "sha256": source["sha256"],
                       "table_selection": block["table_selection"]}
            # The formal select is also the loader's explicit original-column
            # contract. Text status columns stay untouched and unselected.
            select = {"id": f"transform:{len(nodes)}", "kind": "select", "inputs": [source_id],
                      "output": f"derived:{len(nodes)}", "parameters": {"columns": identifiers},
                      "executor": executor, "determinism": "deterministic"}
            raw = {"scientific": {"data_sources": [binding], "mappings": {}, "transforms": [select]}}
            datasets.update(load_sources(raw, _rule_id(intent)))
            sources.append(binding)
            current = transform("select", source_id, {"columns": identifiers})
            y_target = intent["y"].get("unit") or (derived["unit"] if "y" not in selected else _canonical_unit(selected["y"]["unit"]))
            if "y" not in selected:
                current = transform("rheology_complex_viscosity", current, {
                    "frequency_column": selected["angular_frequency"]["column_id"],
                    "storage_column": selected["storage_modulus"]["column_id"],
                    "loss_column": selected["loss_modulus"]["column_id"],
                    "output_column": "y", "output_unit": y_target})
            renames = {selected["x"]["column_id"]: {"id": "x", "label": "Angular Frequency"}}
            if "y" in selected:
                renames[selected["y"]["column_id"]] = {"id": "y", "label": intent["y"]["quantity"].title()}
            current = transform("rename", current, {"columns": renames})
            units = {"x": intent["x"].get("unit") or _canonical_unit(selected["x"]["unit"]), "y": y_target}
            for role in ("x", "y"):
                unit = datasets[current]["columns"][role]["unit"]
                if unit != units[role]:
                    current = transform("convert_unit", current, {"columns": [role], "from_unit": unit, "to_unit": units[role]})
            current = transform("select", current, {"columns": ["x", "y"]})
            records.append({"source_id": source_id, "dataset_id": current, "units": units,
                            "sample": block["sample"], "label": block["label"],
                            "stages": [{"block_id": block["block_id"], "table_selection": deepcopy(block["table_selection"]),
                                        "source_interval": deepcopy(block["source_interval"])}]})
    return _compose(state, records, sources, nodes, datasets, sources[0]["source_id"], axis_policy=frequency_axis)
