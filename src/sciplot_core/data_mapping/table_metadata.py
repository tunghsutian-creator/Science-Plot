"""Resolve explicit declarations without overwriting raw facts or changing values."""

from __future__ import annotations

from typing import Any
from pathlib import Path

import pandas as pd

from sciplot_core.data_mapping.column_choice import _original_text
from sciplot_core.mapping_contract.table_metadata import validate_metadata_confirmations
from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources.paired_curve_table_metadata import axis_match, explicit_header_unit
from sciplot_core.semantic_sources.registered_paired_curve_transform import _comparable_unit, _resolve_output_unit


def resolve_column_metadata(
    columns: list[dict[str, Any]], confirmations: list[dict[str, Any]], *,
    source_sha256: str, sheet: str | None, frame: pd.DataFrame, rule: SemanticRule,
    source: Path | None = None,
) -> None:
    validate_metadata_confirmations(confirmations)
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    errors: list[str] = []
    evidence_frames = {sheet: frame}
    for position, item in enumerate(confirmations):
        try:
            _validate_declaration(item, source_sha256=source_sha256, sheet=sheet,
                                  frame=frame, source=source, column_count=len(columns), evidence_frames=evidence_frames)
        except ValueError as exc:
            errors.append(f"metadata_confirmations[{position}] target sheet={item['sheet']!r} "
                          f"column={item['column_index']} field={item['field']}: {exc}")
        grouped.setdefault((item["column_index"], item["field"]), []).append(item)
    if errors:
        detail = "\n".join(errors[:8])
        remaining = f"\n{len(errors) - 8} further invalid declarations omitted." if len(errors) > 8 else ""
        raise ValueError(f"{len(errors)} invalid metadata declaration(s):\n{detail}{remaining}")

    for column in columns:
        index = column["index"]
        raw = {key: column[key] for key in ("header", "unit", "sample")}
        column.setdefault("raw_metadata", raw)
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
                if rule.scientific_source_adapter == "ftir" and equivalent:
                    from sciplot_core.semantic_sources.ftir_sources import _response_mode

                    equivalent = _response_mode(original) == _response_mode(value)
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
                    canonical = axis.canonical_unit
                    if rule.scientific_source_adapter == "ftir" and role == "y":
                        from sciplot_core.semantic_sources.ftir_sources import _response_mode

                        mode = _response_mode(resolved["quantity"])
                        permitted = {"transmittance": {"%", "1"}, "absorbance": {"a.u.", "1"}, "unknown": {"a.u.", "1"}}[mode]
                        if resolved["unit"] not in permitted:
                            raise ValueError(f"Unsupported {mode} response unit {resolved['unit']!r}; explicitly declare one of {sorted(permitted)}.")
                        canonical = resolved["unit"]
                    _resolve_output_unit(resolved["unit"], canonical_unit=canonical, axis=role, rule_id=rule.rule_id)
                except ValueError as exc:
                    reasons.append({"code": "unsupported_unit", "field": "unit", "message": str(exc)})
            if not column["numeric"]["valid"]:
                reasons.append({"code": "nonfinite_or_missing_values", "field": "data",
                                "row_indices": column["numeric"]["invalid_row_indices"]})
            column[f"{role}_rejection_reasons"] = reasons
            column[f"{role}_eligible"] = not reasons
        column["sample_rejection_reasons"] = ([] if resolved["sample"] else [
            {"code": "missing_sample", "field": "sample", "message": "Confirm identity or select a matching paired sample; legacy single-pair filename fallback remains available."}])
        # Replay older confirmations whose then-unrecognized angular spelling
        # required an appended declared unit, while retaining old header rules.
        header_unit = explicit_header_unit(resolved["quantity"])
        newly_recognized = header_unit.casefold() in {"deg", "degrees", "°", "º", "˚"}
        keep_header = bool(header_unit) and (not newly_recognized or header_unit == resolved["unit"])
        column["output_header"] = (resolved["quantity"] if keep_header
                                   else f"{resolved['quantity']} ({resolved['unit']})")


def _validate_declaration(
    item: dict[str, Any], *, source_sha256: str, sheet: str | None,
    frame: pd.DataFrame, source: Path | None, column_count: int,
    evidence_frames: dict[str | None, pd.DataFrame],
) -> None:
    if item["source_sha256"] != source_sha256:
        raise ValueError(f"Stale source hash; use current source_sha256={source_sha256}.")
    if item["sheet"] != sheet:
        raise ValueError(f"Declaration targets a different worksheet. Target worksheet must be {sheet!r}; "
                         "evidence.sheet names the cited worksheet.")
    if item["column_index"] >= column_count:
        raise ValueError("Column is outside the original table.")
    evidence = item["evidence"]
    if evidence["kind"] != "source_cell":
        return
    row, col = evidence["row_index"], evidence["column_index"]
    evidence_sheet = evidence["sheet"]
    if evidence_sheet not in evidence_frames:
        if source is None or source.suffix.casefold() not in {".xls", ".xlsx", ".xlsm"}:
            raise ValueError("Cross-sheet evidence requires the same original workbook.")
        from sciplot_core.data_mapping.raw_tables import _read_raw_table
        from sciplot_core.mapping_contract import DataSourceReference

        evidence_frames[evidence_sheet] = _read_raw_table(DataSourceReference(
            "evidence", source.name, source_sha256, sheet=evidence["sheet"], header_row=None,
        ), source, preserve_cells=True).frame
    evidence_frame = evidence_frames[evidence_sheet]
    if row >= len(evidence_frame) or col >= evidence_frame.shape[1]:
        raise ValueError("Evidence cell is outside the cited original worksheet.")
    if _original_text(evidence_frame.iat[row, col]) != evidence["text"]:
        raise ValueError("Evidence cell text does not match the original.")
    # Only spelling-equivalent explicit units may differ from the cited text.
    # Quantities and samples still need literal evidence; never infer a response.
    observed_unit = explicit_header_unit(evidence["text"])
    equivalent_unit = (item["field"] == "unit" and bool(observed_unit)
                       and _comparable_unit(item["value"]) == _comparable_unit(observed_unit))
    if item["value"] not in evidence["text"] and not equivalent_unit:
        raise ValueError(f"Value {item['value']!r} is absent from original cell "
                         f"({evidence['sheet']!r}, row={row}, column={col}): {evidence['text'][:120]!r}. "
                         "Use the literal source value; declarations do not rename scientific quantities.")
