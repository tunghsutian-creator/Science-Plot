"""Resolve explicit declarations without overwriting raw facts or changing values."""

from __future__ import annotations

from typing import Any

import pandas as pd

from sciplot_core.data_mapping.column_choice import _original_text
from sciplot_core.mapping_contract.table_metadata import validate_metadata_confirmations
from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources.paired_curve_table_metadata import axis_match, explicit_header_unit
from sciplot_core.semantic_sources.registered_paired_curve_transform import _comparable_unit, _resolve_output_unit


def resolve_column_metadata(
    columns: list[dict[str, Any]], confirmations: list[dict[str, Any]], *,
    source_sha256: str, sheet: str | None, frame: pd.DataFrame, rule: SemanticRule,
) -> None:
    validate_metadata_confirmations(confirmations)
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for item in confirmations:
        if item["source_sha256"] != source_sha256 or item["sheet"] != sheet:
            raise ValueError("Metadata confirmation has a stale source hash or different worksheet.")
        if item["column_index"] >= len(columns):
            raise ValueError("Metadata confirmation column is outside the original table.")
        evidence = item["evidence"]
        if evidence["kind"] == "source_cell":
            row, col = evidence["row_index"], evidence["column_index"]
            if evidence["sheet"] != sheet or row >= len(frame) or col >= frame.shape[1]:
                raise ValueError("Metadata evidence cell is outside the selected original worksheet.")
            if _original_text(frame.iat[row, col]) != evidence["text"]:
                raise ValueError("Metadata evidence cell text does not match the original.")
            # The association is explicit, but a cell citation cannot invent its value.
            if item["value"] not in evidence["text"]:
                raise ValueError("Confirmed value is absent from the cited original cell.")
        grouped.setdefault((item["column_index"], item["field"]), []).append(item)

    for column in columns:
        index = column["index"]
        raw = {key: column[key] for key in ("header", "unit", "sample")}
        column["raw_metadata"] = raw
        column["metadata_confirmations"] = [item for item in confirmations if item["column_index"] == index]
        problems: list[dict[str, Any]] = []
        header_unit = explicit_header_unit(raw["header"])
        if header_unit and raw["unit"] and _comparable_unit(header_unit) != _comparable_unit(raw["unit"]):
            problems.append({"code": "raw_metadata_conflict", "field": "unit",
                             "header_unit": header_unit, "unit_row": raw["unit"]})
        resolved = {"quantity": raw["header"], "unit": raw["unit"], "sample": raw["sample"]}
        # Establish explicit identity before interpreting a sample-labelled header.
        for field in ("sample", "quantity", "unit"):
            items = grouped.get((index, field), [])
            if not items:
                continue
            values = {item["value"] for item in items}
            if len(values) != 1:
                problems.append({"code": "conflicting_confirmations", "field": field, "values": sorted(values)})
                continue
            value = next(iter(values))
            if field == "quantity" and value.casefold() not in {
                label.casefold() for axis in (rule.x_axis, rule.y_axis)
                for label in (axis.canonical_label, *axis.aliases)
            }:
                problems.append({"code": "unsupported_quantity", "field": field, "declared": value})
                continue
            original = resolved[field]
            if field == "quantity" and original == resolved["sample"] and not any(
                axis_match(original, (axis.canonical_label, *axis.aliases)) for axis in (rule.x_axis, rule.y_axis)
            ):
                original = ""  # Explicitly identified sample cell, retained above as raw fact.
            equivalent = original == value
            if field == "unit":
                equivalent = _comparable_unit(original) == _comparable_unit(value)
            elif field == "quantity":
                equivalent = any(axis_match(original, (axis.canonical_label, *axis.aliases))
                    and value.casefold() in {label.casefold() for label in (axis.canonical_label, *axis.aliases)}
                    for axis in (rule.x_axis, rule.y_axis))
            if original and not equivalent:
                problems.append({"code": "raw_metadata_conflict", "field": field,
                                 "original": original, "declared": value})
            else:
                resolved[field] = value
        column.update(header=resolved["quantity"], unit=resolved["unit"], sample=resolved["sample"])
        column["metadata_conflicts"] = problems
        for role, axis in (("x", rule.x_axis), ("y", rule.y_axis)):
            reasons = list(problems)
            if not axis_match(resolved["quantity"], (axis.canonical_label, *axis.aliases)):
                reasons.append({"code": "quantity_missing_or_mismatched", "field": "quantity",
                                "observed": resolved["quantity"], "expected": axis.canonical_label})
            if not resolved["unit"]:
                reasons.append({"code": "missing_unit", "field": "unit", "expected": axis.canonical_unit})
            else:
                try:
                    _resolve_output_unit(resolved["unit"], canonical_unit=axis.canonical_unit, axis=role, rule_id=rule.rule_id)
                except ValueError as exc:
                    reasons.append({"code": "unsupported_unit", "field": "unit", "message": str(exc)})
            if not column["numeric"]["valid"]:
                reasons.append({"code": "nonfinite_or_missing_values", "field": "data",
                                "row_indices": column["numeric"]["invalid_row_indices"]})
            column[f"{role}_rejection_reasons"] = reasons
            column[f"{role}_eligible"] = not reasons
        column["sample_rejection_reasons"] = ([] if resolved["sample"] else [
            {"code": "missing_sample", "field": "sample", "message": "Confirm identity or select a matching paired sample; legacy single-pair filename fallback remains available."}])
        column["output_header"] = (resolved["quantity"] if explicit_header_unit(resolved["quantity"])
                                   else f"{resolved['quantity']} ({resolved['unit']})")
