"""Admit a verified raw curve and preserve its existing scientific analysis."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.task_errors import TaskControlError


if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source_models import ResolvedScientificSource


def admit_raw_curve(state: dict[str, Any], plan: dict[str, Any],
                    observed: ResolvedScientificSource | None) -> bool:
    """Freeze the same source, columns, sample and units under Managed authority."""
    request = state["request"]
    source = Path(request["source"])
    rule_id = plan["rule_id"]
    fields = sorted(set(request) - {"version", "action", "source", "out", "rule_id", "template"})
    if (fields == ["mapping"] and rule_id == "uvvis_spectrum" and source.suffix.casefold() in {".csv", ".tsv"}
            and _admit_mapped_uvvis(state, plan, source, observed)):
        return True
    if fields:
        return _native_only(state, "raw_request_fields_not_managed",
                            "The source-only Managed curve contract does not cover: " + ", ".join(fields))
    if source.suffix.casefold() not in {".csv", ".tsv"} or source.is_dir():
        return _native_only(state, "raw_source_format_not_managed", "This Managed curve route needs one original CSV or TSV file.")
    if not source.is_file():
        raise TaskControlError("source_changed", "The original curve is unavailable after scientific planning.")
    if rule_id not in {"uvvis_spectrum", "dsc_curve", "tga_curve", "dtg_curve", "saxs_profile", "xrd_pattern", "ftir_spectrum",
                       "gpc_sec_chromatogram"}:
        return _native_only(state, "raw_rule_not_managed", f"{rule_id} has no verified ordinary Managed curve route.")
    if (plan["template"] != ("stacked_curve" if rule_id == "ftir_spectrum" else "curve")
            or "data_mapping" in plan or "source_options" in plan):
        return _native_only(state, "raw_plan_not_managed",
                            "The selected template, mapping or source options are outside the verified Managed curve contract.")
    if (
        observed is None or observed.source != source.resolve() or observed.rule_id != rule_id
        or observed.source_sha256 != state["source_sha256"] or observed.transform is None
        or observed.figure_plan is None
        or observed.figure_plan.plan_sha256 != plan["resolved_figure_plan"]["plan_sha256"]
    ):
        raise TaskControlError("source_changed", "The resolved observation does not match this scientific plan.")
    try:
        if _admit_verified_curve(state, plan, source, observed):
            return True
    except TaskControlError as exc:
        # These are specific observation-contract refusals. The registered
        # plan is still usable, provided it describes the same original bytes.
        if exc.reason_code not in {"semantic_coordinate_mapping_required", "semantic_table_not_found"}:
            raise
        if source_tree_sha256(source) != state["source_sha256"]:
            raise TaskControlError("source_changed", "The original curve changed during Managed admission.") from exc
    return _native_only(state, "raw_science_not_verified_for_managed",
                        "The registered plan and Managed binding do not prove identical original rows, samples, quantities and units without conversion or exclusion.")


def _admit_mapped_uvvis(state: dict[str, Any], plan: dict[str, Any], source: Path,
                         observed: ResolvedScientificSource | None) -> bool:
    """Admit one literal, complete, user-confirmed UV-vis pair, not derived data."""
    from sciplot_core.mapping_contract.source_identity import source_view_id

    mapping = state["request"]["mapping"]
    binding = plan.get("data_mapping")
    pair = mapping.get("column_mapping", {})
    if (binding is None or plan["template"] != "curve" or "source_options" in plan
            or set(mapping) != {"source_sha256", "table_selection", "column_mapping"}
            or set(pair) != {"x_column", "y_column"}):
        return False
    selection = mapping["table_selection"]
    if (selection.get("sheet") is not None or set(selection) != {
        "sheet", "header_rows", "unit_row", "sample_row", "data_start_row", "data_end_row",
    }):
        return False
    group = source_view_id(str(source), selection, [pair["x_column"], pair["y_column"]])
    if binding.get("source_group_ids") != [group] or binding["expected_sample_labels"] != [group]:
        return False
    if (observed is None or observed.transform is None or observed.figure_plan is None
            or observed.rule_id != plan["rule_id"] or observed.source != Path(binding["effective_input"])
            or observed.source_sha256 != binding["effective_input_sha256"]
            or observed.figure_plan.plan_sha256 != plan["resolved_figure_plan"]["plan_sha256"]
            or binding["original_input"] != str(source) or binding["original_input_sha256"] != state["source_sha256"]):
        raise TaskControlError("source_changed", "The resolved observation does not match this confirmed original mapping.")
    if observed.transform.contract.output.get("series_order") != [group]:
        return False
    try:
        return _admit_verified_curve(state, plan, source, observed, mapping=mapping)
    except TaskControlError as exc:
        if exc.reason_code not in {"semantic_coordinate_mapping_required", "semantic_table_not_found", "semantic_table_region_ambiguous"}:
            raise
        if source_tree_sha256(source) != state["source_sha256"]:
            raise TaskControlError("source_changed", "The original curve changed during Managed admission.") from exc
        return False


def _native_only(state: dict[str, Any], reason_code: str, message: str) -> bool:
    state["creation_admission"] = {"route": "native_compatibility", "reason_code": reason_code, "message": message}
    return False


def _admit_verified_curve(state: dict[str, Any], plan: dict[str, Any], source: Path,
                          observed: ResolvedScientificSource, *,
                          mapping: dict[str, Any] | None = None) -> bool:
    rule_id = observed.rule_id
    ftir = rule_id == "ftir_spectrum"
    gpc = rule_id == "gpc_sec_chromatogram"
    observed_transform = observed.transform
    assert observed_transform is not None
    transform = observed_transform.contract.to_payload()
    output = transform.get("output") or {}
    columns, series = transform.get("source_columns", []), output.get("series", [])
    if ftir and len(series) >= 2:
        return _admit_ftir_stack(state, plan, source, observed, transform, output, columns, series)
    if not (len(columns) == len(series) == 1
            and output.get("series_order") == [series[0]["sample"]]
            and columns[0]["sample"] == series[0]["sample"]
            and columns[0]["sources"] == [str(observed.source)]
            and series[0]["excluded_point_count"] == 0
            and transform["normalizer"]["operation"] == "none"
            and transform["anchor"]["scope"] == "none"
            and transform["x_coordinate_policy"]["operation"] == "preserve_source_coordinate_and_order"
            and len(plan["resolved_figure_plan"]["selected_figure_ids"]) == 1):
        return False
    from sciplot_core.materials_rules.catalog import get_rule
    from sciplot_core.policy.contract_queries import size_preset_contract
    from sciplot_core.task_semantic_plan import prepare_verified_curve_plan

    rule = get_rule(rule_id)
    selected_id, = plan["resolved_figure_plan"]["selected_figure_ids"]
    figure_task = next(item for item in plan["resolved_figure_plan"]["tasks"] if item["figure_id"] == selected_id)
    if figure_task["metric_binding"] != {"kind": "cartesian_xy", "x_metric": output["x_metric"], "y_metric": output["y_metric"]}:
        return False
    conversions = {(item["sample"], item["role"]): item for item in transform["unit_conversions"]}
    coordinates = (("x", "x", rule.x_axis), ("y", "distribution" if gpc else "response", rule.y_axis))
    intent: dict[str, Any] = {"rule_id": rule_id}
    ftir_mode = output.get("response_mode") if ftir else None
    if ftir and (ftir_mode not in {"transmittance", "absorbance"}
            or output["y_unit"] != {"transmittance": "%", "absorbance": "a.u."}[ftir_mode]
            or columns[0]["response"]["response_mode_detection"] != "detected_from_explicit_response_header"):
        return False
    indices = {role: (mapping["column_mapping"][role + "_column"] if mapping else
                      columns[0][original_role]["column_index_zero_based"])
               for role, original_role, _ in coordinates}
    for role, original_role, axis in coordinates:
        unit = output["y_unit"] if ftir and role == "y" else axis.canonical_unit
        compatibility = transform["axis_compatibility"][role]
        if (compatibility["registered_scale"] != axis.scale or not compatibility["finite_compatible"]
                or (axis.scale == "log" and not compatibility["log_compatible"])):
            return False
        original = columns[0][original_role]
        conversion = conversions.get((series[0]["sample"], original_role), {})
        identity = (conversion.get("operation") == "identity_no_numeric_conversion"
                    and conversion.get("source_unit_declared") and conversion.get("source_unit") == conversion.get("output_unit") == unit
                    if ftir else all(conversion.get(step) == {"factor": 1.0, "offset": 0.0}
                                     for step in ("source_to_canonical", "canonical_to_display")))
        methods = ({"detected_dimensionless_distribution_header"} if gpc and role == "y"
                   else {"detected_from_header", "detected_from_adjacent_unit_row"} if gpc
                   else {"detected_from_adjacent_unit_row"})
        if (original["unit"] != unit or output.get(role + "_unit") != unit or not identity
                or original["unit_detection"]["method"] not in methods):
            return False
        intent[role] = {"quantity": ftir_mode if ftir and role == "y" else output[role + "_metric"], "column_id": f"column:{indices[role]}",
                        "scale": axis.scale, "direction": "descending" if axis.reverse else "ascending"}

    if gpc:
        # The GPC scientific contract identifies the original instrument-exported
        # dimensionless dW/dLogM column. Record unit 1 without treating other
        # blank source units as dimensionless or altering the source cells.
        if columns[0]["distribution"]["header"].casefold() != "dw/dlogm":
            return False
        intent["y"]["source_unit"] = "1"
    if rule_id == "dtg_curve":
        from sciplot_core.source_inspection.semantic_evidence import _quantity

        if _quantity(columns[0]["response"]["header"]) != "derivative_mass":
            return False  # A generic "Derivative" header does not prove the DTG unit context.
    semantic = prepare_verified_curve_plan(source, intent, pairs=[indices])
    frozen = semantic["sources"][0]
    candidates = frozen["candidates"]
    bindings = semantic.get("resolved_bindings", [])
    if semantic["decisions"] or len(candidates) != 1 or len(candidates[0]["blocks"]) != 1 or len(bindings) != 1:
        return False
    block = candidates[0]["blocks"][0]
    sample = block.get("sample", source.stem if gpc else None)
    if ((mapping is None and sample != series[0]["sample"])
            or block["point_count"] != series[0]["point_count"]
            or (gpc and block["table_selection"]["header_rows"] != [columns[0]["header_row_index"]])):
        return False
    if mapping is not None:
        from sciplot_core.data_mapping.original_tables import read_original_table

        region = block["table_selection"]
        if not sample or region != mapping["table_selection"] or frozen["sha256"] != mapping["source_sha256"]:
            return False
        raw = read_original_table(source, None, frozen["sha256"])
        rows = raw.iloc[region["data_start_row"]:region["data_end_row"], [indices["x"], indices["y"]]]
        try:
            points = tuple((float(x), float(y)) for x, y in rows.itertuples(index=False, name=None))
        except (TypeError, ValueError):
            return False  # Leave other numeric encodings to their confirmed mapping owner.
        if points != observed_transform.series[0].points:
            return False
    if gpc:
        region = block["table_selection"]
        header = columns[0]["header_row_index"]
        original_x_unit = columns[0]["x"]["unit_detection"]
        expected_unit_row = header + 1 if original_x_unit["method"] == "detected_from_adjacent_unit_row" else None
        if (region.get("unit_row") != expected_unit_row
                or expected_unit_row is not None and original_x_unit["row_index_zero_based"] != expected_unit_row
                or region["data_start_row"] != header + 1 + int(expected_unit_row is not None) + int("sample_row" in region)):
            return False
    for role, original_role, _ in coordinates:
        actual, original = bindings[0]["coordinates"][role], columns[0][original_role]
        # Scattering quantities may be known to the registered plan without
        # aliases in the generic table. DTG needs the observed derivative.
        expected = intent[role]["quantity"]
        unit = output[role + "_unit"]
        allowed = (expected, None) if rule_id in {"saxs_profile", "xrd_pattern", "gpc_sec_chromatogram"} else (expected,)
        if ((actual["column_index"], actual["header"], actual["observed_unit"], actual["unit"])
                != (indices[role], original["header"], unit, "1" if gpc and role == "y" else unit)
                or actual["observed_quantity"] not in allowed
                or actual["unit_relation"]["kind"] != "identity"):
            return False

    from sciplot_core.studio_render.spectral_axis_display import spectral_frame_size

    size = size_preset_contract(spectral_frame_size(len(series)) if ftir else rule.render_options["size"])
    presentation: dict[str, Any] = {}
    if gpc:
        original = columns[0]["distribution"]
        presentation["registered_source_unit_evidence"] = {"kind": "registered_rule", "rule_id": rule_id, "sheet": None,
            "row_index": columns[0]["header_row_index"], "column_index": original["column_index_zero_based"],
            "text": original["header"]}
    if rule_id == "xrd_pattern":
        from sciplot_core.studio_render.spectral_axis_display import freeze_new_spectral_axis_display

        display = freeze_new_spectral_axis_display({}, rule_id=rule_id, template="curve", transform_contract=transform)
        presentation["show_y_ticks"] = display["render_options"]["show_y_ticks"]
    axis_labels = {role: axis.display_label.replace("$^{-1}$", "⁻¹") for role, _, axis in coordinates}
    if ftir:
        axis_labels["y"] = "Transmittance (%)" if ftir_mode == "transmittance" else "Absorbance (a.u.)"
    return _freeze_raw(state, plan, source, observed, intent, semantic, (size.width_mm, size.height_mm), axis_labels, presentation,
                       mapped_sample=sample if mapping is not None else None)


def _freeze_raw(state: dict[str, Any], plan: dict[str, Any], source: Path,
                observed: ResolvedScientificSource, intent: dict[str, Any],
                semantic: dict[str, Any], size: tuple[float, float], axis_labels: dict[str, str],
                presentation: dict[str, Any], *, mapped_sample: str | None = None) -> bool:
    request, rule_id = state["request"], plan["rule_id"]
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.materials_rules.analysis import compute_resolved_curve_metrics
    from sciplot_core.materials_rules.catalog import get_rule, semantic_payload_from_rule

    digest = semantic["sources"][0]["sha256"]
    original_sha = state["source_sha256"] if mapped_sample is not None else observed.source_sha256
    if (
        canonical_json_sha256({"kind": "file", "content_sha256": digest}) != original_sha
        or source_tree_sha256(source) != original_sha
    ):
        raise TaskControlError("source_changed", "The original scientific curve changed before its analysis.")
    transform = observed.transform
    assert transform is not None
    if mapped_sample is not None:
        from dataclasses import replace

        transform = replace(transform, series=(replace(transform.series[0], sample=mapped_sample),))
    analysis = compute_resolved_curve_metrics(
        transform, semantic=semantic_payload_from_rule(get_rule(rule_id), confidence=100.0),
    )
    if source_tree_sha256(source) != original_sha:
        raise TaskControlError("source_changed", "The original scientific curve changed during its analysis.")
    state.update(initial_request=deepcopy(request), analysis_metrics=analysis,
                 creation_admission={"route": "managed_plot", "reason_code": "verified_raw_curve"},
                 request={"version": 1, "action": "create", "sources": [str(source)], "intent": intent,
                          **({"out": request["out"]} if "out" in request else {})},
                 source_hashes={str(source): digest}, semantic_plan=semantic, semantic_choices={},
                 semantic_plan_confirmed=True, intent_revision=1,
                 plan_confirmation={"mode": "verified_raw_curve", "rule_id": rule_id,
                                    "figure_plan": plan["resolved_figure_plan"]["plan_sha256"],
                                    "size_mm": list(size), **presentation,
                                    "axis_labels": axis_labels})
    return True


def _admit_ftir_stack(
    state: dict[str, Any], plan: dict[str, Any], source: Path, observed: ResolvedScientificSource,
    transform: dict[str, Any],
    output: dict[str, Any], columns: list[dict[str, Any]], series: list[dict[str, Any]],
) -> bool:
    """Require every literal sample and paired original measurement in the old plan."""
    from sciplot_core.policy.contract_queries import size_preset_contract
    from sciplot_core.studio_render.spectral_axis_display import spectral_frame_size
    from sciplot_core.task_semantic_plan import prepare_verified_curve_plan

    mode = output.get("response_mode")
    if mode not in {"transmittance", "absorbance"}:
        return False
    y_unit = {"transmittance": "%", "absorbance": "a.u."}[mode]
    samples = [item["sample"] for item in series]
    figures = plan["resolved_figure_plan"]
    if (output.get("x_unit") != "cm^-1" or output.get("y_unit") != y_unit
            or len(columns) != len(series) or len(set(samples)) != len(samples) or output.get("series_order") != samples
            or [item["sample"] for item in columns] != samples
            or len(figures["selected_figure_ids"]) != 1 or transform["normalizer"]["operation"] != "none"
            or transform["anchor"]["scope"] != "none"
            or transform["x_coordinate_policy"]["operation"] != "preserve_source_coordinate_and_order"):
        return False
    selected = next(item for item in figures["tasks"] if item["figure_id"] == figures["selected_figure_ids"][0])
    if (selected["metric_binding"] != {"kind": "cartesian_xy", "x_metric": "wavenumber", "y_metric": "spectral_response"}
            or selected["template"] != "stacked_curve"):
        return False
    headers = {"x": columns[0]["x"]["header"], "response": columns[0]["response"]["header"]}
    units = {"x": "cm^-1", "response": y_unit}
    conversions = {(item["sample"], item["role"]): item for item in transform["unit_conversions"]}
    for group, trace in zip(columns, series, strict=True):
        if (group["sources"] != [str(source)] or trace["response_mode"] != mode or trace["excluded_point_count"]
                or trace["point_count"] < 2 or group["response"]["response_mode_detection"] != "detected_from_explicit_response_header"):
            return False
        for role, header in headers.items():
            col = group[role]
            conversion = conversions.get((group["sample"], role), {})
            if (col["header"] != header or col["unit"] != units[role]
                    or col["unit_detection"]["method"] != "detected_from_adjacent_unit_row"
                    or conversion.get("operation") != "identity_no_numeric_conversion" or not conversion.get("source_unit_declared")
                    or conversion.get("source_unit") != units[role] or conversion.get("output_unit") != units[role]):
                return False
    intent: dict[str, Any] = {"rule_id": "ftir_spectrum",
              "x": {"quantity": "wavenumber", "header": headers["x"], "scale": "linear", "direction": "descending"},
              "y": {"quantity": mode, "header": headers["response"], "scale": "linear", "direction": "ascending"}}
    semantic = prepare_verified_curve_plan(source, intent, pairs=[
        {"x": group["x"]["column_index_zero_based"], "y": group["response"]["column_index_zero_based"]}
        for group in columns
    ])
    frozen = semantic["sources"][0]
    candidates = frozen["candidates"]
    bindings = semantic.get("resolved_bindings", [])
    if semantic["decisions"] or len(candidates) != 1 or len(bindings) != len(series):
        return False
    blocks = candidates[0]["blocks"]
    if [block.get("sample") for block in blocks] != samples:
        return False
    for block, binding, group, trace in zip(blocks, bindings, columns, series, strict=True):
        region = binding["table_selection"]
        if (binding["block_id"] != block["block_id"] or block["point_count"] != trace["point_count"]
                or region["header_rows"] != [group["header_row_index"]]
                or region["data_start_row"] != group["data_start_row_index"]
                or "sample_row" not in region):
            return False
        for role, original in (("x", "x"), ("y", "response")):
            actual, column = binding["coordinates"][role], group[original]
            if ((actual["column_index"], actual["header"], actual["observed_unit"], actual["unit"])
                    != (column["column_index_zero_based"], column["header"], units[original], units[original])
                    or actual["observed_quantity"] != intent[role]["quantity"]
                    or actual["unit_relation"]["kind"] != "identity"
                    or region.get("unit_row") != column["unit_detection"]["row_index_zero_based"]):
                return False
    size = size_preset_contract(spectral_frame_size(len(series)))
    labels = {"x": "Wavenumber (cm⁻¹)", "y": "Transmittance (%)" if mode == "transmittance" else "Absorbance"}
    return _freeze_raw(state, plan, source, observed, intent, semantic, (size.width_mm, size.height_mm), labels,
                       {"display_stack": "spectral_stack_v1", "show_y_ticks": False})
