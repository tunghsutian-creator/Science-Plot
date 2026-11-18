"""Admit a verified raw curve and preserve its existing scientific analysis."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.task_errors import TaskControlError


def raw_curve_analysis(source: Path, rule_id: str, plan: dict[str, Any], source_sha256: str) -> list[dict[str, Any]]:
    """Run the same registered scientific analysis on the verified canonical curve."""
    from tempfile import TemporaryDirectory

    from sciplot_core.materials_rules.analysis import compute_analysis_metrics
    from sciplot_core.materials_rules.catalog import get_rule, semantic_payload_from_rule
    from sciplot_core.semantic_sources.curve_output import _write_curve_table
    from sciplot_core.semantic_sources.scientific_source_single_curve import resolve_single_curve_transform

    rule = get_rule(rule_id)
    resolved = resolve_single_curve_transform(source, rule=rule)
    if file_sha256(source) != source_sha256 or resolved.contract.to_payload() != plan["scientific_transform"]:
        raise TaskControlError("source_changed", "The original scientific curve changed before its analysis.")
    # The old owner analyzes this normalized table. Using its exact writer
    # preserves header aliases and per-sample parsing even for TSV originals.
    with TemporaryDirectory(prefix="sciplot-raw-analysis-") as directory:
        workspace = Path(directory)
        canonical = workspace / "curve.csv"
        _write_curve_table(list(resolved.series), canonical)
        semantic = semantic_payload_from_rule(rule, confidence=100.0)
        return compute_analysis_metrics(source_path=canonical, processed_source=canonical,
                                        semantic=semantic, output_dir=workspace)


def admit_raw_curve(state: dict[str, Any], plan: dict[str, Any]) -> bool:
    """Freeze the same source, columns, sample and units under Managed authority."""
    request = state["request"]
    source = Path(request["source"])
    rule_id = plan["rule_id"]
    ftir = rule_id == "ftir_spectrum"
    if (set(request) - {"version", "action", "source", "out", "rule_id", "template"}
            or source.suffix.casefold() not in {".csv", ".tsv"} or not source.is_file()
            or rule_id not in {"uvvis_spectrum", "dsc_curve", "tga_curve", "dtg_curve", "saxs_profile", "xrd_pattern", "ftir_spectrum"}
            or plan["template"] != ("stacked_curve" if ftir else "curve") or "data_mapping" in plan or "source_options" in plan):
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
    from sciplot_core.task_semantic_plan import prepare_plan

    rule = get_rule(rule_id)
    selected_id, = plan["resolved_figure_plan"]["selected_figure_ids"]
    figure_task = next(item for item in plan["resolved_figure_plan"]["tasks"] if item["figure_id"] == selected_id)
    if figure_task["metric_binding"] != {"kind": "cartesian_xy", "x_metric": output["x_metric"], "y_metric": output["y_metric"]}:
        return False
    conversions = {(item["sample"], item["role"]): item for item in transform["unit_conversions"]}
    coordinates = (("x", "x", rule.x_axis), ("y", "response", rule.y_axis))
    intent: dict[str, Any] = {"rule_id": rule_id}
    ftir_mode = output.get("response_mode") if ftir else None
    if ftir and (ftir_mode not in {"transmittance", "absorbance"}
            or output["y_unit"] != {"transmittance": "%", "absorbance": "a.u."}[ftir_mode]
            or columns[0]["response"]["response_mode_detection"] != "detected_from_explicit_response_header"):
        return False
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
        if (original["unit"] != unit or output.get(role + "_unit") != unit or not identity
                or original["unit_detection"]["method"] != "detected_from_adjacent_unit_row"):
            return False
        intent[role] = {"quantity": ftir_mode if ftir and role == "y" else output[role + "_metric"], "column_id": f"column:{original['column_index_zero_based']}",
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
    for role, original_role, _ in coordinates:
        actual, original = bindings[0]["coordinates"][role], columns[0][original_role]
        # Scattering quantities may be known to the registered plan without
        # aliases in the generic table. DTG needs the observed derivative.
        expected = intent[role]["quantity"]
        unit = output[role + "_unit"]
        allowed = (expected, None) if rule_id in {"saxs_profile", "xrd_pattern"} else (expected,)
        if ((actual["column_index"], actual["header"], actual["observed_unit"], actual["unit"])
                != (original["column_index_zero_based"], original["header"], unit, unit)
                or actual["observed_quantity"] not in allowed
                or actual["unit_relation"]["kind"] != "identity"):
            return False

    size = size_preset_contract(rule.render_options["size"])
    presentation: dict[str, Any] = {}
    if rule_id == "xrd_pattern":
        from sciplot_core.studio_render.spectral_axis_display import freeze_new_spectral_axis_display

        display = freeze_new_spectral_axis_display({}, rule_id=rule_id, template="curve", transform_contract=transform)
        presentation["show_y_ticks"] = display["render_options"]["show_y_ticks"]
    axis_labels = {role: axis.display_label.replace("$^{-1}$", "⁻¹") for role, _, axis in coordinates}
    if ftir:
        axis_labels["y"] = "Transmittance (%)" if ftir_mode == "transmittance" else "Absorbance"
    analysis = raw_curve_analysis(source, rule_id, plan, frozen["sha256"])
    state.update(initial_request=deepcopy(request), analysis_metrics=analysis,
                 request={"version": 1, "action": "create", "sources": [str(source)], "intent": intent,
                          **({"out": request["out"]} if "out" in request else {})},
                 source_hashes={str(source): frozen["sha256"]}, semantic_plan=semantic, semantic_choices={},
                 semantic_plan_confirmed=True, intent_revision=1,
                 plan_confirmation={"mode": "verified_raw_curve", "rule_id": rule_id,
                                    "figure_plan": plan["resolved_figure_plan"]["plan_sha256"],
                                    "size_mm": [size.width_mm, size.height_mm], **presentation,
                                    "axis_labels": axis_labels})
    return True
