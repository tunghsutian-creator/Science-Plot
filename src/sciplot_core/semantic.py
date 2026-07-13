from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from os.path import commonprefix
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core._constants import _DEFAULT_RENDER_OPTIONS
from sciplot_core._utils import (
    clean_text as _clean_text,
)
from sciplot_core._utils import (
    decode_text as _decode_text,
)
from sciplot_core._utils import (
    json_safe as _json_safe,
)
from sciplot_core._utils import (
    text_preview as _text_preview,
)
from sciplot_core._utils import (
    token as _token,
)
from sciplot_core.materials_rules import (
    format_unit_label,
    get_rule,
    match_rule,
    semantic_payload_from_rule,
)
from sciplot_core.operation_modes import assisted_cleanup_mode_payload
from sciplot_core.publication import build_transform_step

ensure_legacy_core()

from src.data_loader import read_raw_table  # noqa: E402
from src.rendering.recommendation import inspect_input_file  # noqa: E402
from src.text_normalization import normalize_unit  # noqa: E402


@dataclass(frozen=True)
class CurveSeriesPayload:
    sample: str
    x_label: str
    x_unit: str
    y_label: str
    y_unit: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class RheologySweepSample:
    sample: str
    source: Path
    x_label: str
    x_unit: str
    metric_units: dict[str, str]
    rows: tuple[dict[str, float], ...]


_RHEOLOGY_SWEEP_METRICS = (
    ("storage_modulus", "Storage Modulus", ("storagemodulus", "storage modulus", "g'", "g′"), "Pa"),
    ("loss_modulus", "Loss Modulus", ("lossmodulus", 'g"', "g″"), "Pa"),
    ("loss_factor", "Loss Factor", ("lossfactor", "tandelta", "tanδ"), "1"),
    ("complex_viscosity", "Complex Viscosity", ("complexviscosity", "viscosity"), "Pa·s"),
)
_RHEOLOGY_COMPLEX_MODULUS_METRIC = (
    "complex_modulus",
    "Complex Modulus",
    ("complexmodulus", "complexshearmodulus", "|g*|", "g*"),
    "Pa",
)
_RHEOLOGY_FREQUENCY_OUTPUT_METRICS = (
    _RHEOLOGY_SWEEP_METRICS[0],
    _RHEOLOGY_SWEEP_METRICS[1],
    _RHEOLOGY_SWEEP_METRICS[2],
    _RHEOLOGY_SWEEP_METRICS[3],
)


def _vendor_inspection(input_path: Path, sheet: str | int) -> tuple[dict[str, Any] | None, str | None]:
    if input_path.is_dir():
        return None, "Vendor inspect expects a file, not a directory."
    try:
        payload = inspect_input_file(input_path, sheet)
    except Exception as exc:
        return None, str(exc)
    return _json_safe(payload), None


def _top_recommendation(vendor_inspection: dict[str, Any] | None) -> dict[str, Any] | None:
    if not vendor_inspection:
        return None
    recommendations = vendor_inspection.get("recommendations") or []
    top = recommendations[0] if recommendations else None
    return top if isinstance(top, dict) else None


def _template_from_vendor(vendor_inspection: dict[str, Any] | None, fallback: str = "curve") -> str:
    top = _top_recommendation(vendor_inspection)
    if top is None:
        return fallback
    return str(top.get("template_id") or fallback)


def _render_options_from_vendor(vendor_inspection: dict[str, Any] | None) -> dict[str, Any]:
    top = _top_recommendation(vendor_inspection)
    if top is None:
        return dict(_DEFAULT_RENDER_OPTIONS)
    defaults = top.get("default_render_overrides") or {}
    if not isinstance(defaults, dict):
        return dict(_DEFAULT_RENDER_OPTIONS)
    return {**_DEFAULT_RENDER_OPTIONS, **defaults}


def _classification(
    *,
    semantic_family: str,
    recommended_recipe: str | None,
    template: str,
    render_options: dict[str, Any],
    confidence: float,
    reason: str,
    needs_ai_intervention: bool = False,
    vendor_model: str | None = None,
    vendor_error: str | None = None,
) -> dict[str, Any]:
    return {
        "semantic_family": semantic_family,
        "recommended_recipe": recommended_recipe,
        "template": template,
        "render_options": render_options,
        "confidence": confidence,
        "reason": reason,
        "needs_ai_intervention": needs_ai_intervention,
        "vendor_model": vendor_model,
        "vendor_error": vendor_error,
    }


def _is_tensile_export_dir(path: Path) -> bool:
    return path.is_dir() and path.name.casefold().endswith(".is_tens_exports")


def _has_tensile_export_parent(path: Path) -> bool:
    return any(parent.name.casefold().endswith(".is_tens_exports") for parent in path.parents)


def classify_source(
    input_path: str | Path,
    *,
    sheet: str | int = 0,
    vendor_inspection: dict[str, Any] | None = None,
    requested_rule_id: str | None = None,
) -> dict[str, Any]:
    path = Path(input_path).expanduser()
    if vendor_inspection is None:
        vendor_inspection, vendor_error = _vendor_inspection(path, sheet)
    else:
        vendor_error = None

    vendor_model = str(vendor_inspection.get("model")) if vendor_inspection and vendor_inspection.get("model") else None
    top = _top_recommendation(vendor_inspection)
    experiment_family = str(top.get("experiment_family")) if top and top.get("experiment_family") else ""
    text = _text_preview(path)
    evidence = f"{path.as_posix()}\n{text}".casefold()
    compact_evidence = _token(evidence)
    matched_rule = match_rule(
        evidence=evidence,
        compact_evidence=compact_evidence,
        vendor_model=vendor_model,
        experiment_family=experiment_family,
        requested_rule_id=requested_rule_id,
    )
    if matched_rule is not None:
        if matched_rule.fixture_status != "ready":
            return semantic_payload_from_rule(
                matched_rule,
                confidence=0.0,
                reason=(
                    f"Explicitly requested material rule `{matched_rule.rule_id}` is pending "
                    "fixture-backed acceptance and cannot run in deterministic mode."
                ),
                vendor_model=vendor_model,
                vendor_error=vendor_error,
            )
        confidence = 96.0 if requested_rule_id else max(80.0, 98.0 - matched_rule.priority / 2)
        return semantic_payload_from_rule(
            matched_rule,
            confidence=confidence,
            reason=matched_rule.reason or f"Matched material rule `{matched_rule.rule_id}`.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if _is_tensile_export_dir(path) or _has_tensile_export_parent(path) or "结果表格2" in compact_evidence:
        return _classification(
            semantic_family="tensile_curve",
            recommended_recipe="tensile",
            template="curve",
            render_options=dict(_DEFAULT_RENDER_OPTIONS),
            confidence=95.0,
            reason="Detected Chinese tensile export table or `.is_tens_Exports` directory.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if (
        "stressrelaxation" in compact_evidence
        or "stresssrelaxation" in compact_evidence
        or "relaxationtest" in compact_evidence
        or "relaxationmodulus" in compact_evidence
        or "stepstrain" in compact_evidence
    ):
        return _classification(
            semantic_family="rheology_stress_relaxation",
            recommended_recipe="stress_relaxation",
            template="curve",
            render_options=dict(_DEFAULT_RENDER_OPTIONS),
            confidence=94.0,
            reason="Detected rheology stress-relaxation metadata or relaxation modulus columns.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if "creep" in compact_evidence or "creeptest" in compact_evidence or "creepcompliance" in compact_evidence:
        return _classification(
            semantic_family="rheology_creep",
            recommended_recipe="rheology_dma",
            template="curve",
            render_options=dict(_DEFAULT_RENDER_OPTIONS),
            confidence=94.0,
            reason="Detected rheology creep metadata or creep compliance columns.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if (
        vendor_model == "frequency_metric_sheet"
        or experiment_family == "rheology"
        or "frequencysweep" in compact_evidence
        or "angularfrequency" in compact_evidence
        or "pinlv" in compact_evidence
        or "流变" in evidence
    ):
        return _classification(
            semantic_family="rheology_frequency",
            recommended_recipe="rheology_dma",
            template=_template_from_vendor(vendor_inspection, "point_line"),
            render_options=_render_options_from_vendor(vendor_inspection),
            confidence=93.0 if vendor_model == "frequency_metric_sheet" else 80.0,
            reason="Detected rheology frequency-sweep data.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if "impact" in compact_evidence or "冲击" in evidence:
        return semantic_payload_from_rule(
            get_rule("impact_metric"),
            confidence=0.0,
            reason=(
                "Detected impact metric data, but its categorical/replicate Veusz contract is pending "
                "fixture-backed acceptance."
            ),
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if vendor_model == "tensile_curve" or "tensile" in compact_evidence or "拉伸" in evidence:
        return _classification(
            semantic_family="tensile_curve",
            recommended_recipe="tensile",
            template=_template_from_vendor(vendor_inspection, "curve"),
            render_options=_render_options_from_vendor(vendor_inspection),
            confidence=88.0,
            reason="Detected mechanical tensile-style curve data.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if vendor_model == "replicate_table":
        return _classification(
            semantic_family="generic_replicate",
            recommended_recipe="metrics_swelling",
            template=_template_from_vendor(vendor_inspection, "box"),
            render_options=_render_options_from_vendor(vendor_inspection),
            confidence=75.0,
            reason="Detected a generic replicate table.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    if vendor_model in {"curve_table", "heatmap_table", "table_summary"}:
        return _classification(
            semantic_family="generic_curve",
            recommended_recipe=None,
            template=_template_from_vendor(vendor_inspection, "curve"),
            render_options=_render_options_from_vendor(vendor_inspection),
            confidence=70.0,
            reason=f"Detected a generic plot-ready table through vendor model `{vendor_model}`.",
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )

    return _classification(
        semantic_family="unknown",
        recommended_recipe=None,
        template="curve",
        render_options=dict(_DEFAULT_RENDER_OPTIONS),
        confidence=0.0,
        reason="SciPlot could not map this input to a known experiment semantic family.",
        needs_ai_intervention=True,
        vendor_model=vendor_model,
        vendor_error=vendor_error,
    )


def _sample_from_interval_metadata(raw: pd.DataFrame, fallback: str) -> str:
    for row_index in range(min(12, raw.shape[0])):
        row = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        if row and _token(row[0]) == "test" and len(row) > 1 and row[1]:
            return row[1]
    return fallback


def _find_interval_header(raw: pd.DataFrame) -> int:
    for row_index in range(raw.shape[0]):
        row = [_token(value) for value in raw.iloc[row_index].tolist()]
        if row and row[0] == "intervaldata":
            return row_index
    raise ValueError("Could not find `Interval data` section in rheology export.")


def _find_column(headers: list[str], candidates: tuple[str, ...]) -> int:
    for index, header in enumerate(headers):
        token = _token(header)
        if any(candidate in token for candidate in candidates):
            return index
    raise ValueError(f"Could not find any expected column: {', '.join(candidates)}")


def _unit_for(units: list[str], index: int, fallback: str) -> str:
    if index < len(units):
        unit = _clean_text(units[index]).strip("[]() ")
        if unit:
            return format_unit_label(unit)
    return format_unit_label(fallback)


def _float(value: object) -> float | None:
    text = _clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_candidate_tables(source: Path) -> list[tuple[str, pd.DataFrame]]:
    if source.suffix.lower() in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(source)
        tables = [
            (sheet_name, pd.read_excel(source, sheet_name=sheet_name, header=None).dropna(axis=1, how="all"))
            for sheet_name in workbook.sheet_names
        ]
    else:
        tables = [(source.name, read_raw_table(source).dropna(axis=1, how="all"))]
    return [(name, table.dropna(how="all")) for name, table in tables if not table.dropna(how="all").empty]


def _axis_match(value: object, aliases: tuple[str, ...]) -> bool:
    text = _clean_text(value).casefold()
    token = _token(value)
    for alias in aliases:
        alias_text = alias.casefold()
        alias_token = _token(alias)
        if alias_text and (text == alias_text or alias_text in text):
            return True
        if not alias_token:
            continue
        if token == alias_token or alias_token in token:
            return True
    return False


def _looks_like_unit(value: object) -> bool:
    raw = _clean_text(value)
    if raw == "PA":
        return False
    token = _token(value)
    if not token:
        return False
    return token in {
        "s",
        "sec",
        "min",
        "h",
        "pa",
        "kpa",
        "mpa",
        "gpa",
        "百分比",
        "kjm2",
        "kjm²",
        "jm",
        "j",
    } or token in {"", "1"} or "%" in _clean_text(value)


def _unit_row_score(raw: pd.DataFrame, row_index: int, columns: tuple[int, ...]) -> int:
    if row_index >= raw.shape[0]:
        return -1
    return sum(1 for column in columns if _looks_like_unit(raw.iat[row_index, column]))


def _sample_from_row(raw: pd.DataFrame, row_index: int | None, *, start: int, stop: int, fallback: str) -> str:
    if row_index is None or row_index >= raw.shape[0]:
        return fallback
    for column in range(start, min(stop, raw.shape[1])):
        value = _clean_text(raw.iat[row_index, column])
        if value and not _looks_like_unit(value) and not _axis_match(value, ("time", "strain", "stress", "σ")):
            return value
    return fallback


def _scan_curve_series_table(
    raw: pd.DataFrame,
    *,
    x_aliases: tuple[str, ...],
    y_aliases: tuple[str, ...],
    x_label: str,
    y_label: str,
    default_x_unit: str,
    default_y_unit: str,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for header_index in range(max(0, raw.shape[0] - 2)):
        row_values = raw.iloc[header_index].tolist()
        pairs: list[tuple[int, int]] = []
        for x_index, value in enumerate(row_values[:-1]):
            if not _axis_match(value, x_aliases):
                continue
            search_stop = min(x_index + 5, raw.shape[1])
            for y_index in range(x_index + 1, search_stop):
                if _axis_match(row_values[y_index], y_aliases):
                    pairs.append((x_index, y_index))
                    break
        if not pairs:
            continue
        columns = tuple(column for pair in pairs for column in pair)
        first_extra = header_index + 1
        second_extra = header_index + 2
        first_unit_score = _unit_row_score(raw, first_extra, columns)
        second_unit_score = _unit_row_score(raw, second_extra, columns)
        unit_index = first_extra if first_unit_score >= second_unit_score else second_extra
        sample_index = second_extra if unit_index == first_extra else first_extra
        if max(first_unit_score, second_unit_score) <= 0:
            unit_index = -1
            sample_index = header_index + 1
        data_start = max(header_index + 1, unit_index + 1, sample_index + 1)
        candidate_series: list[CurveSeriesPayload] = []
        for series_index, (x_index, y_index) in enumerate(pairs, start=1):
            points: list[tuple[float, float]] = []
            for row_index in range(data_start, raw.shape[0]):
                x_value = _float(raw.iat[row_index, x_index])
                y_value = _float(raw.iat[row_index, y_index])
                if x_value is not None and y_value is not None:
                    points.append((x_value, y_value))
            if not points:
                continue
            x_unit = default_x_unit
            y_unit = default_y_unit
            if unit_index >= 0:
                x_unit = _clean_text(raw.iat[unit_index, x_index]).strip("[]") or x_unit
                y_unit = _clean_text(raw.iat[unit_index, y_index]).strip("[]") or y_unit
            sample = _sample_from_row(
                raw,
                sample_index,
                start=x_index,
                stop=min(y_index + 3, raw.shape[1]),
                fallback=f"{sample_prefix} {series_index}",
            )
            candidate_series.append(
                CurveSeriesPayload(
                    sample=sample,
                    x_label=x_label,
                    x_unit=x_unit,
                    y_label=y_label,
                    y_unit=y_unit,
                    points=tuple(points),
                )
            )
        if sum(len(series.points) for series in candidate_series) > sum(len(series.points) for series in best):
            best = candidate_series
    return best


def _scan_curve_series_source(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    y_aliases: tuple[str, ...],
    x_label: str,
    y_label: str,
    default_x_unit: str,
    default_y_unit: str,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for sheet_name, raw in _read_candidate_tables(source):
        series = _scan_curve_series_table(
            raw,
            x_aliases=x_aliases,
            y_aliases=y_aliases,
            x_label=x_label,
            y_label=y_label,
            default_x_unit=default_x_unit,
            default_y_unit=default_y_unit,
            sample_prefix=sheet_name or sample_prefix,
        )
        if sum(len(item.points) for item in series) > sum(len(item.points) for item in best):
            best = series
    return best


def _read_rheology_interval_series(
    source: Path,
    *,
    y_candidates: tuple[str, ...],
    y_label: str,
    y_unit: str,
) -> CurveSeriesPayload:
    raw = read_raw_table(source).dropna(axis=1, how="all")
    header_index = _find_interval_header(raw)
    headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
    units = [_clean_text(value) for value in raw.iloc[min(header_index + 2, raw.shape[0] - 1)].tolist()]
    x_index = _find_column(headers, ("time", "时间"))
    y_index = _find_column(headers, y_candidates)
    points: list[tuple[float, float]] = []
    for row_index in range(header_index + 1, raw.shape[0]):
        row = raw.iloc[row_index].tolist()
        x_value = _float(row[x_index] if x_index < len(row) else None)
        y_value = _float(row[y_index] if y_index < len(row) else None)
        if x_value is not None and y_value is not None:
            points.append((x_value, y_value))
    if not points:
        raise ValueError(f"No numeric rheology interval points found in {source}.")
    return CurveSeriesPayload(
        sample=_sample_from_interval_metadata(raw, source.stem),
        x_label="Time",
        x_unit=_unit_for(units, x_index, "s"),
        y_label=y_label,
        y_unit=_unit_for(units, y_index, y_unit),
        points=tuple(points),
    )


def _read_rheology_interval_series_list(
    source: Path,
    *,
    y_candidates: tuple[str, ...],
    y_label: str,
    y_unit: str,
) -> list[CurveSeriesPayload]:
    candidates = _sweep_source_files(source)
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for candidate in candidates:
        try:
            series = _read_rheology_interval_series(
                candidate,
                y_candidates=y_candidates,
                y_label=y_label,
                y_unit=y_unit,
            )
            series_list.append(
                CurveSeriesPayload(
                    sample=_source_display_sample(candidate),
                    x_label=series.x_label,
                    x_unit=series.x_unit,
                    y_label=series.y_label,
                    y_unit=series.y_unit,
                    points=series.points,
                )
            )
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(f"No {y_label.casefold()} exports found under {source}. {detail}".strip())
    return series_list


def _sweep_source_files(source: Path) -> list[Path]:
    if not source.is_dir():
        return [source]
    suffixes = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
    return sorted(
        (child for child in source.iterdir() if child.is_file() and child.suffix.lower() in suffixes),
        key=lambda path: path.name.casefold(),
    )


def _source_display_sample(source: Path) -> str:
    stem = source.stem.strip()
    if "__" in stem:
        group, _rest = stem.split("__", 1)
        group = group.strip()
        if group:
            return group
    return stem


def _find_rheology_sweep_header(raw: pd.DataFrame, *, x_aliases: tuple[str, ...]) -> int:
    try:
        return _find_interval_header(raw)
    except ValueError:
        storage_aliases = _RHEOLOGY_SWEEP_METRICS[0][2]
        for row_index in range(raw.shape[0]):
            headers = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
            try:
                _find_column(headers, x_aliases)
                _find_column(headers, storage_aliases)
            except ValueError:
                continue
            return row_index
    raise ValueError("Could not find rheology sweep X and storage-modulus columns.")


def _rheology_sweep_units(
    raw: pd.DataFrame,
    *,
    header_index: int,
    columns: tuple[int, ...],
) -> list[str]:
    candidates = [row_index for row_index in (header_index + 1, header_index + 2) if row_index < raw.shape[0]]
    if not candidates:
        return []
    best_index = max(candidates, key=lambda row_index: _unit_row_score(raw, row_index, columns))
    if _unit_row_score(raw, best_index, columns) <= 0:
        return []
    return [_clean_text(value) for value in raw.iloc[best_index].tolist()]


def _read_rheology_sweep_sample(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    x_label: str,
    default_x_unit: str,
) -> RheologySweepSample:
    raw = read_raw_table(source).dropna(axis=1, how="all")
    header_index = _find_rheology_sweep_header(raw, x_aliases=x_aliases)
    headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
    x_index = _find_column(headers, x_aliases)
    metric_indexes: dict[str, int] = {}
    for key, _label, aliases, _default_unit in _RHEOLOGY_SWEEP_METRICS:
        try:
            metric_index = _find_column(headers, aliases)
        except ValueError:
            continue
        metric_indexes[key] = metric_index
    if "storage_modulus" not in metric_indexes:
        raise ValueError(f"Could not find storage modulus in rheology sweep source {source}.")
    units = _rheology_sweep_units(
        raw,
        header_index=header_index,
        columns=(x_index, *metric_indexes.values()),
    )
    metric_units = {
        key: _unit_for(units, metric_index, default_unit)
        for key, _label, _aliases, default_unit in _RHEOLOGY_SWEEP_METRICS
        if (metric_index := metric_indexes.get(key)) is not None
    }
    should_derive_complex_modulus = (
        "complex_modulus" not in metric_indexes
        and "storage_modulus" in metric_indexes
        and "loss_modulus" in metric_indexes
    )
    if should_derive_complex_modulus:
        metric_units["complex_modulus"] = (
            metric_units.get("storage_modulus") or metric_units.get("loss_modulus") or "Pa"
        )

    rows: list[dict[str, float]] = []
    for row_index in range(header_index + 1, raw.shape[0]):
        x_value = _float(raw.iat[row_index, x_index])
        if x_value is None:
            continue
        row: dict[str, float] = {"x": x_value}
        for key, metric_index in metric_indexes.items():
            y_value = _float(raw.iat[row_index, metric_index])
            if y_value is not None:
                row[key] = y_value
        if should_derive_complex_modulus:
            storage = row.get("storage_modulus")
            loss = row.get("loss_modulus")
            if storage is not None and loss is not None:
                row["complex_modulus"] = math.hypot(storage, loss)
        if any(key in row for key in metric_indexes):
            rows.append(row)
    if not rows:
        raise ValueError(f"No numeric rheology sweep points found in {source}.")
    return RheologySweepSample(
        sample=_source_display_sample(source),
        source=source,
        x_label=x_label,
        x_unit=_unit_for(units, x_index, default_x_unit),
        metric_units=metric_units,
        rows=tuple(rows),
    )


def _read_rheology_sweep_comparison_samples(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    x_label: str,
    default_x_unit: str,
) -> list[RheologySweepSample]:
    samples: list[RheologySweepSample] = []
    for candidate in _sweep_source_files(source):
        try:
            samples.append(
                _read_rheology_sweep_sample(
                    candidate,
                    x_aliases=x_aliases,
                    x_label=x_label,
                    default_x_unit=default_x_unit,
                )
            )
        except Exception:
            continue
    return sorted(samples, key=_sweep_sample_order_key)


def _read_rheology_frequency_comparison_samples(source: Path) -> list[RheologySweepSample]:
    return _read_rheology_sweep_comparison_samples(
        source,
        x_aliases=("angularfrequency", "frequency", "omega", "ω"),
        x_label="Angular Frequency",
        default_x_unit="rad/s",
    )


def _read_rheology_temperature_comparison_samples(source: Path) -> list[RheologySweepSample]:
    return _read_rheology_sweep_comparison_samples(
        source,
        x_aliases=("temperature", "temp", "温度"),
        x_label="Temperature",
        default_x_unit="°C",
    )


def _confirmed_column_items(column_confirmations: object) -> list[dict[str, Any]]:
    if not isinstance(column_confirmations, list | tuple):
        return []
    return [item for item in column_confirmations if isinstance(item, dict)]


def _confirmation_names(confirmation: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    file_name = _clean_text(confirmation.get("file_name"))
    if file_name:
        names.add(file_name)
    source_path = _clean_text(confirmation.get("source_path"))
    if source_path:
        names.add(Path(source_path).name)
    return names


def _candidate_names(candidate: Path) -> set[str]:
    names = {candidate.name}
    if "__" in candidate.name:
        _sample, original = candidate.name.split("__", 1)
        if original:
            names.add(original)
    return names


def _matching_column_confirmation(
    candidate: Path,
    column_confirmations: object,
) -> dict[str, Any] | None:
    candidate_names = _candidate_names(candidate)
    for confirmation in _confirmed_column_items(column_confirmations):
        if candidate_names & _confirmation_names(confirmation):
            return confirmation
    return None


def _metric_key_from_label(
    label: object,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> str | None:
    token = _token(label)
    if not token:
        return None
    for key, metric_label, aliases, _default_unit in metrics:
        metric_tokens = {_token(metric_label), *(_token(alias) for alias in aliases)}
        if any(metric_token and metric_token in token for metric_token in metric_tokens):
            return key
    return None


def _metric_default_units(
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> dict[str, str]:
    units = {key: default_unit for key, _label, _aliases, default_unit in metrics}
    units.setdefault("complex_modulus", _RHEOLOGY_COMPLEX_MODULUS_METRIC[3])
    return units


def _confirmed_rheology_sweep_sample(
    source: Path,
    confirmation: dict[str, Any],
    *,
    x_label: str,
    default_x_unit: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> RheologySweepSample:
    raw = read_raw_table(source).dropna(axis=1, how="all").dropna(how="all")
    columns = confirmation.get("columns")
    if not isinstance(columns, list | tuple):
        raise ValueError("Column confirmation does not contain columns.")

    x_index: int | None = None
    metric_indexes: dict[str, int] = {}
    match_metrics = (*metrics, _RHEOLOGY_COMPLEX_MODULUS_METRIC)
    for column in columns:
        if not isinstance(column, dict):
            continue
        try:
            index = int(column.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= raw.shape[1]:
            continue
        confirmed_type = _clean_text(column.get("confirmed_type")).casefold()
        if confirmed_type == "ignore":
            continue
        role = _clean_text(column.get("role")).casefold()
        if role == "x" and x_index is None:
            x_index = index
            continue
        if role != "y":
            continue
        metric_key = _metric_key_from_label(column.get("name"), match_metrics)
        if metric_key and metric_key not in metric_indexes:
            metric_indexes[metric_key] = index

    if x_index is None:
        raise ValueError(f"No confirmed X column found in {source}.")
    if "storage_modulus" not in metric_indexes:
        raise ValueError(f"No confirmed storage modulus column found in {source}.")

    default_units = _metric_default_units(match_metrics)
    numeric_rows = [
        row_index
        for row_index in range(raw.shape[0])
        if _float(raw.iat[row_index, x_index]) is not None
        and any(_float(raw.iat[row_index, metric_index]) is not None for metric_index in metric_indexes.values())
    ]
    if not numeric_rows:
        raise ValueError(f"No numeric rheology sweep points found in {source}.")

    unit_index = numeric_rows[0] - 1
    units = [_clean_text(value) for value in raw.iloc[unit_index].tolist()] if unit_index >= 0 else []
    metric_units = {
        key: _unit_for(units, metric_index, default_units.get(key, ""))
        for key, metric_index in metric_indexes.items()
    }
    should_derive_complex_modulus = (
        "complex_modulus" not in metric_indexes
        and "storage_modulus" in metric_indexes
        and "loss_modulus" in metric_indexes
    )
    if should_derive_complex_modulus:
        metric_units["complex_modulus"] = (
            metric_units.get("storage_modulus") or metric_units.get("loss_modulus") or "Pa"
        )

    rows: list[dict[str, float]] = []
    for row_index in numeric_rows:
        x_value = _float(raw.iat[row_index, x_index])
        if x_value is None:
            continue
        row: dict[str, float] = {"x": x_value}
        for key, metric_index in metric_indexes.items():
            y_value = _float(raw.iat[row_index, metric_index])
            if y_value is not None:
                row[key] = y_value
        if should_derive_complex_modulus:
            storage = row.get("storage_modulus")
            loss = row.get("loss_modulus")
            if storage is not None and loss is not None:
                row["complex_modulus"] = math.hypot(storage, loss)
        rows.append(row)

    return RheologySweepSample(
        sample=_source_display_sample(source),
        source=source,
        x_label=x_label,
        x_unit=_unit_for(units, x_index, default_x_unit),
        metric_units=metric_units,
        rows=tuple(rows),
    )


def _read_confirmed_rheology_sweep_samples(
    source: Path,
    column_confirmations: object,
    *,
    x_label: str,
    default_x_unit: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> list[RheologySweepSample]:
    samples: list[RheologySweepSample] = []
    for candidate in _sweep_source_files(source):
        confirmation = _matching_column_confirmation(candidate, column_confirmations)
        if confirmation is None:
            continue
        try:
            samples.append(
                _confirmed_rheology_sweep_sample(
                    candidate,
                    confirmation,
                    x_label=x_label,
                    default_x_unit=default_x_unit,
                    metrics=metrics,
                )
            )
        except Exception:
            continue
    return sorted(samples, key=_sweep_sample_order_key)


def _sweep_sample_order_key(sample: RheologySweepSample) -> tuple[float, str]:
    storage_points = [
        (row["x"], row["storage_modulus"])
        for row in sample.rows
        if "x" in row and "storage_modulus" in row
    ]
    if not storage_points:
        return (float("inf"), sample.sample.casefold())
    reference_x = max(x_value for x_value, _storage in storage_points)
    _x_value, storage = min(storage_points, key=lambda item: abs(item[0] - reference_x))
    return (storage, sample.sample.casefold())


def _ordered_sweep_samples(
    samples: list[RheologySweepSample],
    series_order: object = None,
) -> list[RheologySweepSample]:
    if not isinstance(series_order, list | tuple):
        return samples
    order = {
        _token(sample): index
        for index, sample in enumerate(series_order)
        if isinstance(sample, str) and sample.strip()
    }
    if not order:
        return samples
    fallback = len(order)
    return sorted(samples, key=lambda sample: (order.get(_token(sample.sample), fallback), sample.sample.casefold()))


def _normalized_replicate_mode(value: object) -> str:
    token = _clean_text(value).casefold()
    aliases = {
        "": "mean",
        "average": "mean",
        "avg": "mean",
        "best": "representative",
        "all": "individual",
    }
    token = aliases.get(token, token)
    return token if token in {"mean", "representative", "individual"} else "mean"


def _terminal_storage(sample: RheologySweepSample) -> float | None:
    points = [
        (row["x"], row["storage_modulus"])
        for row in sample.rows
        if "x" in row and "storage_modulus" in row
    ]
    if not points:
        return None
    return max(points, key=lambda item: item[0])[1]


def _mean_replicate_sample(samples: list[RheologySweepSample]) -> RheologySweepSample:
    representative = samples[0]
    metric_keys = sorted({key for sample in samples for row in sample.rows for key in row if key != "x"})
    x_values = sorted({row["x"] for sample in samples for row in sample.rows if "x" in row})
    metric_units: dict[str, str] = {}
    for sample in samples:
        for key, unit in sample.metric_units.items():
            metric_units.setdefault(key, unit)
    rows: list[dict[str, float]] = []
    for x_value in x_values:
        row: dict[str, float] = {"x": x_value}
        for key in metric_keys:
            values = [
                metric_value
                for sample in samples
                for point in sample.rows
                if point.get("x") == x_value
                for metric_value in [point.get(key)]
                if metric_value is not None and math.isfinite(metric_value)
            ]
            if values:
                row[key] = sum(values) / len(values)
        if len(row) > 1:
            rows.append(row)
    return RheologySweepSample(
        sample=representative.sample,
        source=representative.source,
        x_label=representative.x_label,
        x_unit=representative.x_unit,
        metric_units=metric_units,
        rows=tuple(rows),
    )


def _representative_replicate_sample(samples: list[RheologySweepSample]) -> RheologySweepSample:
    terminal_values = [value for sample in samples if (value := _terminal_storage(sample)) is not None]
    if not terminal_values:
        return max(samples, key=lambda sample: (len(sample.rows), sample.source.name))
    ordered = sorted(terminal_values)
    median = ordered[len(ordered) // 2]

    def score(sample: RheologySweepSample) -> tuple[int, float, str]:
        terminal = _terminal_storage(sample)
        distance = abs((terminal if terminal is not None else median) - median)
        return (-len(sample.rows), distance, sample.source.name)

    return min(samples, key=score)


def _coalesce_replicate_sweep_samples(
    samples: list[RheologySweepSample],
    *,
    replicate_mode: object = None,
) -> list[RheologySweepSample]:
    mode = _normalized_replicate_mode(replicate_mode)
    if mode == "individual":
        return samples
    grouped: dict[str, list[RheologySweepSample]] = {}
    order: list[str] = []
    for sample in samples:
        key = _clean_text(sample.sample) or sample.source.stem
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(sample)
    coalesced: list[RheologySweepSample] = []
    for key in order:
        group = grouped[key]
        if len(group) == 1:
            coalesced.append(group[0])
        elif mode == "representative":
            coalesced.append(_representative_replicate_sample(group))
        else:
            coalesced.append(_mean_replicate_sample(group))
    return coalesced


def is_rheology_frequency_comparison_dir(source: str | Path) -> bool:
    path = Path(source).expanduser()
    if not path.is_dir():
        return False
    return len(_read_rheology_frequency_comparison_samples(path)) >= 2


def is_rheology_temperature_comparison_dir(source: str | Path) -> bool:
    path = Path(source).expanduser()
    if not path.is_dir():
        return False
    text = path.as_posix().casefold()
    if "/temp/" not in text and "temperature" not in text and "温度" not in text:
        return False
    return len(_read_rheology_temperature_comparison_samples(path)) >= 2


def _sheet_name(value: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]+", "_", value).strip() or "Sample"
    base = cleaned[:31]
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = f"{base[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def _sweep_comparison_frame_for_metrics(
    samples: list[RheologySweepSample],
    *,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> pd.DataFrame:
    metric_keys = tuple(key for key, _label, _aliases, _unit in metrics)
    headers: list[object] = []
    sample_row: list[object] = []
    unit_row: list[object] = []
    max_rows = max(len(sample.rows) for sample in samples)
    for sample in samples:
        headers.append(sample.x_label)
        sample_row.append(sample.sample)
        unit_row.append(sample.x_unit)
        for key, label, _aliases, default_unit in metrics:
            headers.append(label)
            sample_row.append(sample.sample)
            unit_row.append(sample.metric_units.get(key, default_unit))
    rows: list[list[object]] = [headers, sample_row, unit_row]
    for point_index in range(max_rows):
        row: list[object] = []
        for sample in samples:
            if point_index < len(sample.rows):
                point = sample.rows[point_index]
                row.append(point.get("x", ""))
                row.extend(point.get(key, "") for key in metric_keys)
            else:
                row.extend([""] * (1 + len(metric_keys)))
        rows.append(row)
    return pd.DataFrame(rows)


def _sweep_comparison_frame(samples: list[RheologySweepSample]) -> pd.DataFrame:
    return _sweep_comparison_frame_for_metrics(samples, metrics=_RHEOLOGY_SWEEP_METRICS)


def _sample_sweep_frame(
    sample: RheologySweepSample,
    *,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...] = _RHEOLOGY_SWEEP_METRICS,
) -> pd.DataFrame:
    headers = [sample.x_label, *[label for _key, label, _aliases, _unit in metrics]]
    units = [
        sample.x_unit,
        *[
            sample.metric_units.get(key, default_unit)
            for key, _label, _aliases, default_unit in metrics
        ],
    ]
    rows: list[list[object]] = [headers, units]
    for point in sample.rows:
        rows.append(
            [
                point.get("x", ""),
                *[point.get(key, "") for key, _label, _aliases, _unit in metrics],
            ]
        )
    return pd.DataFrame(rows)


def _write_rheology_sweep_comparison_workbook(
    samples: list[RheologySweepSample],
    output_path: Path,
    *,
    comparison_sheet: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...] = _RHEOLOGY_SWEEP_METRICS,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    used_sheet_names: set[str] = set()
    with pd.ExcelWriter(output_path) as writer:
        _sweep_comparison_frame_for_metrics(samples, metrics=metrics).to_excel(
            writer,
            sheet_name=_sheet_name(comparison_sheet, used_sheet_names),
            header=False,
            index=False,
        )
        for sample in samples:
            _sample_sweep_frame(sample, metrics=metrics).to_excel(
                writer,
                sheet_name=_sheet_name(sample.sample, used_sheet_names),
                header=False,
                index=False,
            )


def _read_wide_stress_relaxation_series(source: Path) -> list[CurveSeriesPayload]:
    series_list = _scan_curve_series_source(
        source,
        x_aliases=("time", "时间"),
        y_aliases=("shear stress", "shearstress", "stress", "应力"),
        x_label="Time",
        y_label="Shear stress",
        default_x_unit="s",
        default_y_unit="Pa",
        sample_prefix=source.stem,
    )
    series_list = [
        _normalize_series(series, y_label="Normalized stress", y_unit="sigma/sigma0")
        for series in series_list
    ]
    if not series_list:
        raise ValueError("Could not find wide stress-relaxation time/stress series.")
    return series_list


def _read_stress_relaxation_source_series(source: Path) -> list[CurveSeriesPayload]:
    sample = _source_display_sample(source)
    try:
        series = _read_rheology_interval_series(
            source,
            y_candidates=("shearstress", "stress", "应力"),
            y_label="Shear stress",
            y_unit="Pa",
        )
        normalized = _normalize_series(series, y_label="Normalized stress", y_unit="sigma/sigma0")
        return [_with_series_sample(normalized, sample)]
    except ValueError:
        try:
            series_list = _read_wide_stress_relaxation_series(source)
        except ValueError:
            series = _read_rheology_interval_series(
                source,
                y_candidates=("relaxationmodulus", "modulus", "松弛模量"),
                y_label="Relaxation modulus",
                y_unit="Pa",
            )
            normalized = _normalize_series(series, y_label="Normalized modulus", y_unit="G/G0")
            return [_with_series_sample(normalized, sample)]
        if len(series_list) == 1:
            return [_with_series_sample(series_list[0], sample)]
        return series_list


def _read_stress_relaxation_series_list(source: Path) -> list[CurveSeriesPayload]:
    if not source.is_dir():
        return _read_stress_relaxation_source_series(source)
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for candidate in _sweep_source_files(source):
        try:
            series_list.extend(_read_stress_relaxation_source_series(candidate))
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(f"No stress-relaxation exports found under {source}. {detail}".strip())
    return series_list


def _normalize_series(series: CurveSeriesPayload, *, y_label: str, y_unit: str) -> CurveSeriesPayload:
    if not series.points:
        return series
    finite_y_values = [y_value for _x_value, y_value in series.points if y_value and math.isfinite(y_value)]
    if not finite_y_values:
        raise ValueError("Cannot normalize a stress-relaxation curve without a non-zero finite y value.")
    baseline = max(finite_y_values, key=abs)
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=y_label,
        y_unit=y_unit,
        points=tuple((x_value, y_value / baseline) for x_value, y_value in series.points),
    )


def _read_tensile_export_series(source: Path) -> CurveSeriesPayload:
    text = _decode_tensile_export_text(source)
    lines = text.splitlines()
    header_indexes = [
        index
        for index, line in enumerate(lines)
        if "拉伸应变" in line and "拉伸应力" in line and "," in line
    ]
    section_two_index = next(
        (index for index, line in enumerate(lines) if _token(line) == "结果表格2"),
        None,
    )
    if section_two_index is not None:
        preferred = [index for index in header_indexes if index > section_two_index]
        header_indexes = [*preferred, *[index for index in header_indexes if index not in preferred]]
    for header_index in header_indexes:
        headers = next(csv.reader([lines[header_index]]))
        units = next(csv.reader([lines[header_index + 1]])) if header_index + 1 < len(lines) else []
        x_index = _find_column(headers, ("拉伸应变", "strain"))
        y_index = _find_column(headers, ("拉伸应力", "stress"))
        points: list[tuple[float, float]] = []
        for line in lines[header_index + 2 :]:
            if not line.strip():
                if points:
                    break
                continue
            row = next(csv.reader([line]))
            x_value = _float(row[x_index] if x_index < len(row) else None)
            y_value = _float(row[y_index] if y_index < len(row) else None)
            if x_value is not None and y_value is not None:
                points.append((x_value, y_value))
        if len(points) < 2:
            continue
        return CurveSeriesPayload(
            sample=source.stem,
            x_label="Tensile strain",
            x_unit=_unit_for(units, x_index, "%"),
            y_label="Tensile stress",
            y_unit=_unit_for(units, y_index, "MPa"),
            points=tuple(points),
        )
    raise ValueError(f"Could not find a multi-point tensile curve table in {source}.")


def _decode_tensile_export_text(source: Path) -> str:
    text = _decode_text(source)
    if _looks_like_tensile_export_text(text):
        return text
    payload = source.read_bytes()
    for encoding in ("gb18030", "gbk", "utf-8-sig", "utf-8", "latin-1"):
        try:
            candidate = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _looks_like_tensile_export_text(candidate):
            return candidate
    return text


def _looks_like_tensile_export_text(text: str) -> bool:
    lowered = text.casefold()
    return (
        ("拉伸应变" in text and "拉伸应力" in text)
        or ("tensile strain" in lowered and "stress" in lowered)
        or "结果表格" in text
    )


def _read_tensile_workbook_series(source: Path) -> list[CurveSeriesPayload]:
    series_list = _scan_curve_series_source(
        source,
        x_aliases=("strain", "拉伸应变"),
        y_aliases=("stress", "σ", "sigma", "拉伸应力", "应力"),
        x_label="Tensile strain",
        y_label="Tensile stress",
        default_x_unit="%",
        default_y_unit="MPa",
        sample_prefix=source.stem,
    )
    if not series_list:
        raise ValueError("No tensile curves found by structure scan.")
    return series_list


def _read_impact_block_table(source: Path) -> list[list[object]]:
    raw = read_raw_table(source).dropna(axis=1, how="all")
    if raw.shape[0] < 3:
        raise ValueError("Impact block table needs at least three rows.")
    re_columns: list[tuple[str, int, str]] = []
    for column in range(raw.shape[1]):
        header = _clean_text(raw.iat[1, column] if raw.shape[0] > 1 else "")
        header_token = _token(header)
        if not (header_token.startswith("re") or "impact" in header_token or "冲击" in header_token):
            continue
        sample = ""
        for sample_column in range(column, -1, -1):
            candidate = _clean_text(raw.iat[0, sample_column])
            if candidate:
                sample = candidate
                break
        if not sample:
            sample = f"Sample {len(re_columns) + 1}"
        unit = "kJ/m2"
        if "kj" in header_token:
            unit = "kJ/m2"
        re_columns.append((sample, column, unit))
    if len(re_columns) < 2:
        raise ValueError("Could not find grouped impact strength columns.")
    value_columns: list[list[float]] = []
    for _sample, column, _unit in re_columns:
        values: list[float] = []
        for row_index in range(2, raw.shape[0]):
            value = _float(raw.iat[row_index, column])
            if value is not None:
                values.append(value)
        value_columns.append(values)
    if not any(value_columns):
        raise ValueError("Grouped impact strength columns did not contain numeric values.")
    max_len = max(len(values) for values in value_columns)
    rows: list[list[object]] = [
        ["Impact strength" for _sample, _column, _unit in re_columns],
        [unit for _sample, _column, unit in re_columns],
        [sample for sample, _column, _unit in re_columns],
    ]
    for row_index in range(max_len):
        rows.append([values[row_index] if row_index < len(values) else "" for values in value_columns])
    return rows


def _read_impact_compact_table(source: Path) -> list[list[object]]:
    raw = read_raw_table(source).dropna(how="all").dropna(axis=1, how="all")
    if raw.shape[0] < 2:
        raise ValueError("Impact compact table needs a header and at least one data row.")
    headers = [_token(value) for value in raw.iloc[0].tolist()]
    sample_col = next((index for index, token in enumerate(headers) if token in {"sample", "samplename"}), None)
    metric_col = next((index for index, token in enumerate(headers) if "impact" in token or "冲击" in token), None)
    if sample_col is None or metric_col is None:
        raise ValueError("Impact compact table needs sample and impact columns.")
    unit_col = metric_col + 1 if metric_col + 1 < raw.shape[1] else None
    samples: list[str] = []
    values: list[float] = []
    units: list[str] = []
    for row_index in range(1, raw.shape[0]):
        sample = _clean_text(raw.iat[row_index, sample_col])
        value = _float(raw.iat[row_index, metric_col])
        if not sample or value is None:
            continue
        samples.append(sample)
        values.append(value)
        if unit_col is not None:
            unit = _clean_text(raw.iat[row_index, unit_col])
            if unit:
                units.append(unit)
    if not values:
        raise ValueError("Impact compact table did not contain numeric impact values.")
    unit = units[0] if units else "kJ/m2"
    return [
        ["Impact strength" for _sample in samples],
        [unit for _sample in samples],
        samples,
        values,
    ]


def _write_curve_table(series_list: list[CurveSeriesPayload], output_path: Path) -> None:
    max_points = max(len(series.points) for series in series_list)
    rows: list[list[object]] = [[], [], []]
    for series in series_list:
        rows[0].extend([series.x_label, series.y_label])
        rows[1].extend([series.x_unit, series.y_unit])
        rows[2].extend([series.sample, series.sample])
    for point_index in range(max_points):
        row: list[object] = []
        for series in series_list:
            if point_index < len(series.points):
                x_value, y_value = series.points[point_index]
                row.extend([x_value, y_value])
            else:
                row.extend(["", ""])
        rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, header=False, index=False)


def _ftir_source_files(source: Path) -> list[Path]:
    suffixes = {".csv", ".tsv", ".txt"}
    if source.is_file() and source.suffix.lower() in suffixes:
        return [source]
    if not source.is_dir():
        return []
    return sorted(
        (path for path in source.iterdir() if path.is_file() and path.suffix.lower() in suffixes),
        key=lambda path: path.name.casefold(),
    )


def _read_headerless_ftir_series(source: Path) -> CurveSeriesPayload:
    raw: pd.DataFrame | None = None
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            raw = pd.read_csv(source, header=None, sep=None, engine="python", encoding=encoding)
            break
        except Exception as exc:
            last_error = exc
    if raw is None:
        raise ValueError(f"Could not read FTIR spectrum {source}.") from last_error
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    numeric = raw.apply(pd.to_numeric, errors="coerce")
    best_points: list[tuple[float, float]] = []
    for x_index in range(max(0, numeric.shape[1] - 1)):
        y_index = x_index + 1
        points = [
            (float(x_value), float(y_value))
            for x_value, y_value in zip(numeric.iloc[:, x_index], numeric.iloc[:, y_index], strict=False)
            if pd.notna(x_value) and pd.notna(y_value)
        ]
        if len(points) > len(best_points):
            best_points = points
    if len(best_points) < 4:
        raise ValueError(f"No numeric two-column FTIR spectrum found in {source}.")
    x_values = [point[0] for point in best_points]
    if min(x_values) < 50.0 or max(x_values) > 10000.0 or max(x_values) - min(x_values) < 100.0:
        raise ValueError(f"FTIR wavenumber range is not plausible in {source}.")
    return CurveSeriesPayload(
        sample=_source_display_sample(source),
        x_label="Wavenumber",
        x_unit="cm^-1",
        y_label="Transmittance",
        y_unit="%",
        points=tuple(best_points),
    )


def _read_ftir_series(source: Path) -> list[CurveSeriesPayload]:
    structured = _scan_curve_series_source(
        source,
        x_aliases=("wavenumber", "cm-1", "cm^-1"),
        y_aliases=("transmittance", "%t", "absorbance"),
        x_label="Wavenumber",
        y_label="Transmittance",
        default_x_unit="cm^-1",
        default_y_unit="%",
        sample_prefix=source.stem,
    )
    if len(structured) == 1:
        series = structured[0]
        return [
            CurveSeriesPayload(
                sample=_source_display_sample(source),
                x_label=series.x_label,
                x_unit=series.x_unit,
                y_label=series.y_label,
                y_unit=series.y_unit,
                points=series.points,
            )
        ]
    if structured:
        return structured
    return [_read_headerless_ftir_series(source)]


def _read_ftir_series_list(source: Path) -> list[CurveSeriesPayload]:
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for path in _ftir_source_files(source):
        try:
            series_list.extend(_read_ftir_series(path))
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(f"No FTIR spectra found under {source}. {detail}".strip())
    return series_list


def _series_order_map(series_order: object) -> dict[str, int]:
    if not isinstance(series_order, list | tuple):
        return {}
    ordered: dict[str, int] = {}
    for index, value in enumerate(series_order):
        label = _clean_text(value)
        if label and label not in ordered:
            ordered[label] = index
    return ordered


def _order_curve_series(
    series_list: list[CurveSeriesPayload],
    series_order: object,
) -> list[CurveSeriesPayload]:
    order = _series_order_map(series_order)
    if not order:
        return series_list

    def key(item: tuple[int, CurveSeriesPayload]) -> tuple[int, int]:
        index, series = item
        group_name = _intake_group_name(series.sample) or series.sample
        rank = order.get(series.sample, order.get(group_name, len(order) + index))
        return (rank, index)

    return [series for _index, series in sorted(enumerate(series_list), key=key)]


def _finite_series_points(series: CurveSeriesPayload) -> list[tuple[float, float]]:
    return sorted(
        ((x_value, y_value) for x_value, y_value in series.points if math.isfinite(x_value) and math.isfinite(y_value)),
        key=lambda item: item[0],
    )


def _interpolated_y_at(points: list[tuple[float, float]], target_x: float) -> float | None:
    if not points:
        return None
    if target_x <= points[0][0]:
        return points[0][1]
    for index in range(1, len(points)):
        x0, y0 = points[index - 1]
        x1, y1 = points[index]
        if target_x > x1:
            continue
        if math.isclose(x0, x1):
            return y1
        fraction = (target_x - x0) / (x1 - x0)
        return y0 + (y1 - y0) * fraction
    return points[-1][1]


def _order_curve_series_by_shared_right_height(series_list: list[CurveSeriesPayload]) -> list[CurveSeriesPayload]:
    if len(series_list) < 2:
        return series_list
    point_sets = [_finite_series_points(series) for series in series_list]
    usable_ranges = [(points[0][0], points[-1][0]) for points in point_sets if points]
    if len(usable_ranges) != len(series_list):
        return series_list
    shared_min = max(start for start, _end in usable_ranges)
    shared_max = min(end for _start, end in usable_ranges)
    target_x = shared_max if shared_min <= shared_max else None

    scored: list[tuple[float, int, CurveSeriesPayload]] = []
    for index, (series, points) in enumerate(zip(series_list, point_sets, strict=True)):
        if target_x is None:
            score = points[-1][1]
        else:
            interpolated = _interpolated_y_at(points, target_x)
            score = interpolated if interpolated is not None else points[-1][1]
        scored.append((score, index, series))
    return [series for _score, _index, series in sorted(scored, key=lambda item: (-item[0], item[1]))]


def _compact_torque_sample_labels(labels: list[str]) -> list[str]:
    if len(labels) < 2:
        return labels
    prefix = commonprefix(labels)
    separator_index = max(prefix.rfind("-"), prefix.rfind("_"), prefix.rfind(" "))
    if separator_index < 3:
        return labels
    prefix = prefix[: separator_index + 1]
    compacted = [label[len(prefix) :] if label.startswith(prefix) else label for label in labels]
    compacted = [label or original for label, original in zip(compacted, labels, strict=False)]
    if len(set(compacted)) != len(compacted):
        return labels
    return compacted


def _with_series_sample(series: CurveSeriesPayload, sample: str) -> CurveSeriesPayload:
    return CurveSeriesPayload(
        sample=sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=series.points,
    )


def _compact_torque_series_labels(series_list: list[CurveSeriesPayload]) -> list[CurveSeriesPayload]:
    labels = _compact_torque_sample_labels([series.sample for series in series_list])
    return [_with_series_sample(series, label) for series, label in zip(series_list, labels, strict=False)]


def _torque_source_files(source: Path) -> list[Path]:
    suffixes = {".txt", ".csv", ".tsv"}
    if source.is_file() and source.suffix.lower() in suffixes:
        return [source]
    if not source.is_dir():
        return []
    return sorted(
        (path for path in source.iterdir() if path.is_file() and path.suffix.lower() in suffixes),
        key=lambda path: path.name,
    )


def _read_torque_table(source: Path) -> pd.DataFrame:
    first_error: Exception | None = None
    try:
        raw = read_raw_table(source).dropna(axis=1, how="all")
        evidence = " ".join(str(value) for value in [*raw.columns.tolist(), *raw.iloc[:4].to_numpy().ravel().tolist()])
        if "torque" in evidence.casefold() or "转矩" in evidence:
            return raw
    except Exception as exc:
        first_error = exc
    last_error: Exception | None = first_error
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "utf-16", "latin-1"):
        try:
            raw = pd.read_csv(source, sep="\t", header=None, encoding=encoding).dropna(axis=1, how="all")
            evidence = " ".join(str(value) for value in raw.iloc[:4].to_numpy().ravel().tolist())
            if "torque" in evidence.casefold() or "转矩" in evidence:
                return raw
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not read torque export {source}.") from last_error


def _read_torque_full_series(source: Path) -> CurveSeriesPayload:
    raw = _read_torque_table(source)
    header_index = 0
    x_index: int | None = None
    y_index: int | None = None
    header_candidates: list[tuple[int, list[object]]] = [(-1, raw.columns.tolist())]
    header_candidates.extend((index, raw.iloc[index].tolist()) for index in range(min(8, raw.shape[0])))
    for candidate_index, candidate_values in header_candidates:
        headers = [_clean_text(value) for value in candidate_values]
        try:
            candidate_x = _find_column(headers, ("index", "time", "时间"))
            candidate_y = _find_column(headers, ("screwtorque", "torque", "转矩"))
        except ValueError:
            continue
        header_index = candidate_index
        x_index = candidate_x
        y_index = candidate_y
        break
    if x_index is None or y_index is None:
        raise ValueError(f"Could not find Index/Time and Screw Torque columns in {source}.")
    unit_index = max(0, header_index + 1)
    units = [_clean_text(value) for value in raw.iloc[unit_index].tolist()] if raw.shape[0] > unit_index else []
    points: list[tuple[float, float]] = []
    for row_index in range(max(0, header_index + 1), raw.shape[0]):
        x_value = _float(raw.iat[row_index, x_index])
        y_value = _float(raw.iat[row_index, y_index])
        if x_value is not None and y_value is not None:
            points.append((x_value, y_value))
    if not points:
        raise ValueError(f"No numeric torque points found in {source}.")
    y_unit = _normalize_torque_unit(_unit_for(units, y_index, "N·m"))
    sample = source.stem
    intake_group = _intake_group_name(sample)
    if intake_group is not None:
        sample = intake_group
    return CurveSeriesPayload(
        sample=sample,
        x_label="Time",
        x_unit="s",
        y_label="Screw torque",
        y_unit=y_unit,
        points=tuple(points),
    )


def _normalize_torque_unit(unit: str) -> str:
    cleaned = _clean_text(unit).strip("[]()")
    if cleaned in {"Nm", "N m", "N.m", "N·m"}:
        return "N·m"
    return normalize_unit(cleaned)


def _smooth_torque(values: list[float]) -> list[float]:
    if len(values) < 5:
        return values
    window = max(3, min(21, len(values) // 80))
    if window % 2 == 0:
        window += 1
    return list(pd.Series(values).rolling(window, center=True, min_periods=1).median())


def _contiguous_true_runs(flags: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def _median_positive_step(values: list[float]) -> float:
    diffs = [abs(stop - start) for start, stop in zip(values, values[1:], strict=False) if abs(stop - start) > 0]
    if not diffs:
        return 1.0
    return float(pd.Series(diffs).median())


def _auto_torque_event_selection(series: CurveSeriesPayload) -> dict[str, Any]:
    points = list(series.points)
    if len(points) < 3:
        raise ValueError(f"Torque series `{series.sample}` needs at least three numeric points.")
    x_values = [x_value for x_value, _y_value in points]
    y_values = [y_value for _x_value, y_value in points]
    smooth = _smooth_torque(y_values)
    y_frame = pd.Series(y_values)
    low_level = float(y_frame.quantile(0.05))
    work_level = float(y_frame[y_frame > y_frame.quantile(0.25)].median())
    if pd.isna(work_level):
        work_level = float(y_frame.median())
    low_threshold = min(max(low_level + 0.5, min(1.5, work_level * 0.45)), work_level * 0.75)
    high_threshold = work_level + max(5.0, (max(y_values) - work_level) * 0.35)
    pre_drop_threshold = low_threshold + max(0.75, (work_level - low_threshold) * 0.25)

    high_flags = [value >= high_threshold for value in y_values]
    raw_low_runs = _contiguous_true_runs([value <= low_threshold for value in y_values])
    low_runs = _contiguous_true_runs([value <= low_threshold for value in smooth])
    discharge_run: tuple[int, int] | None = None
    for start, stop in reversed(low_runs):
        if stop - start + 1 < 3:
            continue
        if not any(high_flags[:start]):
            continue
        before_start = max(0, start - 30)
        if start > 0 and max(smooth[before_start:start] or [0.0]) > pre_drop_threshold:
            discharge_run = (start, stop)
            break

    if discharge_run is None:
        tail_count = max(2, min(1200, int(len(points) * 0.25)))
        start_index = len(points) - tail_count
        end_index = len(points) - 1
        feed_peak_index = max(range(start_index, end_index + 1), key=lambda index: y_values[index])
        return {
            "sample": series.sample,
            "start_s": x_values[start_index],
            "feed_peak_s": x_values[feed_peak_index],
            "discharge_drop_s": x_values[end_index],
            "end_s": x_values[end_index],
            "time_zero": "start_s",
            "source": "auto_fallback_tail",
            "confidence": 35.0,
            "needs_human_review": True,
            "reason": "Could not detect a final discharge drop; fell back to the final quarter of the trace.",
        }

    discharge_start, discharge_stop = discharge_run
    search_stop = max(0, discharge_start - 1)
    peak_runs = _contiguous_true_runs([index < search_stop and flag for index, flag in enumerate(high_flags)])
    if peak_runs:
        peak_start, peak_stop = peak_runs[-1]
        feed_peak_index = max(range(peak_start, peak_stop + 1), key=lambda index: y_values[index])
    else:
        feed_peak_index = max(range(0, max(1, search_stop)), key=lambda index: y_values[index])

    prior_low_runs = [run for run in raw_low_runs if run[1] < feed_peak_index]
    if prior_low_runs:
        start_index = max(0, prior_low_runs[-1][0] - 5)
    else:
        time_step = _median_positive_step(x_values)
        buffer_points = max(5, int(round(60 / time_step))) if time_step else 30
        start_index = max(0, feed_peak_index - buffer_points)
    time_step = _median_positive_step(x_values)
    event_span = max(time_step, x_values[discharge_start] - x_values[start_index])
    post_drop_span = max(time_step * 5, min(60.0, event_span * 0.05))
    target_end = x_values[discharge_start] + post_drop_span
    end_index = discharge_start
    while end_index < discharge_stop and x_values[end_index] < target_end:
        end_index += 1
    return {
        "sample": series.sample,
        "start_s": x_values[start_index],
        "feed_peak_s": x_values[feed_peak_index],
        "discharge_drop_s": x_values[discharge_start],
        "end_s": x_values[end_index],
        "time_zero": "start_s",
        "source": "auto_detected",
        "confidence": 82.0 if peak_runs else 55.0,
        "needs_human_review": not bool(peak_runs),
        "reason": "Detected the final feed peak and discharge drop event.",
    }


def _apply_torque_selection(
    series: CurveSeriesPayload,
    selection: dict[str, Any],
) -> CurveSeriesPayload:
    start_s = float(selection.get("start_s", series.points[0][0]))
    end_s = float(selection.get("end_s", series.points[-1][0]))
    if end_s < start_s:
        start_s, end_s = end_s, start_s
    selected = [(x_value, y_value) for x_value, y_value in series.points if start_s <= x_value <= end_s]
    if not selected:
        selected = list(series.points)
        start_s = selected[0][0]
    zero = start_s if selection.get("time_zero", "start_s") == "start_s" else selected[0][0]
    sample = _clean_text(selection.get("plot_label")) or series.sample
    return CurveSeriesPayload(
        sample=sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=tuple((x_value - zero, y_value) for x_value, y_value in selected),
    )


def _load_torque_curation(curation_path: str | Path | None) -> dict[str, Any] | None:
    if curation_path is None:
        return None
    path = Path(curation_path).expanduser()
    if not path.exists():
        raise ValueError(f"Torque curation file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Torque curation file must contain a JSON object.")
    return payload


def _torque_selection_for_source(
    *,
    source: Path,
    series: CurveSeriesPayload,
    curation: dict[str, Any] | None,
) -> dict[str, Any]:
    if curation is not None:
        resolved = str(source.expanduser().resolve())
        source_name = source.name
        for item in curation.get("samples", []):
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source_path") or "")
            item_sample = str(item.get("sample") or "")
            if item_source == resolved or Path(item_source).name == source_name or item_sample == series.sample:
                return item
    return {
        "sample": series.sample,
        "start_s": series.points[0][0],
        "end_s": series.points[-1][0],
        "time_zero": "absolute",
        "source": "full_curve",
        "confidence": 100.0,
        "needs_human_review": False,
        "reason": "Using the full torque curve; event trimming requires an explicit curation file.",
    }


def _read_torque_series(source: Path, *, curation: dict[str, Any] | None = None) -> CurveSeriesPayload:
    full_series = _read_torque_full_series(source)
    if curation is None:
        return full_series
    selection = _torque_selection_for_source(source=source, series=full_series, curation=curation)
    return _apply_torque_selection(full_series, selection)


def _tensile_export_files(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        return sorted(input_path.rglob("*.csv"))
    return [input_path]


def _read_tensile_export_series_list(source: Path) -> list[CurveSeriesPayload]:
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for path in _tensile_export_files(source):
        try:
            series_list.append(_read_tensile_export_series(path))
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(f"No tensile CSV exports found under {source}. {detail}".strip())
    return series_list


def _intake_group_name(sample: str) -> str | None:
    if "__" not in sample:
        return None
    group, _rest = sample.split("__", 1)
    group = group.strip()
    return group or None


def _series_summary(series: CurveSeriesPayload) -> tuple[float, float]:
    y_values = [y_value for _x_value, y_value in series.points]
    x_values = [x_value for x_value, _y_value in series.points]
    return (max(y_values), x_values[-1])


def _representative_tensile_series(series_list: list[CurveSeriesPayload]) -> list[CurveSeriesPayload]:
    groups: dict[str, list[CurveSeriesPayload]] = {}
    for series in series_list:
        group = _intake_group_name(series.sample)
        if group is None:
            return series_list
        groups.setdefault(group, []).append(series)

    representatives: list[CurveSeriesPayload] = []
    for group, items in groups.items():
        summaries = [_series_summary(item) for item in items]
        median_strength = float(pd.Series(strength for strength, _strain in summaries).median())
        median_strain = float(pd.Series(strain for _strength, strain in summaries).median())
        representative = min(
            zip(items, summaries, strict=True),
            key=lambda item: (
                abs(item[1][0] - median_strength),
                abs(item[1][1] - median_strain),
                item[0].sample.casefold(),
            ),
        )[0]
        representatives.append(
            CurveSeriesPayload(
                sample=group,
                x_label=representative.x_label,
                x_unit=representative.x_unit,
                y_label=representative.y_label,
                y_unit=representative.y_unit,
                points=representative.points,
            )
        )
    return representatives


def _has_intake_grouped_series(series_list: list[CurveSeriesPayload]) -> bool:
    return any(_intake_group_name(series.sample) for series in series_list)


def _semantic_preparation_result(
    source: Path,
    *,
    processed_source: Path | None,
    operation: str,
    parameters: dict[str, Any] | None = None,
    additional_outputs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    output_path = processed_source if processed_source is not None else source
    return {
        "source": str(output_path),
        "processed": processed_source is not None,
        "processed_source": str(processed_source) if processed_source is not None else None,
        "transform_steps": [
            build_transform_step(
                step_id="semantic_preparation",
                operation=operation,
                input_path=source,
                output_path=output_path,
                implementation_ref="sciplot_core.semantic.prepare_semantic_source",
                parameters=parameters,
                additional_outputs=additional_outputs,
            )
        ],
    }


def prepare_semantic_source(
    input_path: str | Path,
    *,
    output_dir: Path,
    semantic: dict[str, Any],
    curation_path: str | Path | None = None,
    series_order: object = None,
    column_confirmations: object = None,
    replicate_mode: object = None,
) -> dict[str, Any]:
    source = Path(input_path).expanduser()
    processed_dir = output_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    family = semantic["semantic_family"]

    if family == "rheology_frequency" and source.is_dir():
        processed_source = processed_dir / "rheology_frequency_comparison.xlsx"
        samples = _read_rheology_frequency_comparison_samples(source)
        if not samples:
            samples = _read_confirmed_rheology_sweep_samples(
                source,
                column_confirmations,
                x_label="Angular Frequency",
                default_x_unit="rad/s",
                metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
            )
        source_sample_count = len(samples)
        source_sample_files = [str(sample.source) for sample in samples]
        samples = _coalesce_replicate_sweep_samples(samples, replicate_mode=replicate_mode)
        samples = _ordered_sweep_samples(samples, series_order=series_order)
        if not samples:
            raise ValueError(
                "Rheology frequency folders need at least one parseable sample export."
            )
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet="Frequency_Comparison",
            metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
        )
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="aggregate_rheology_frequency_replicates",
            parameters={
                "replicate_mode": _normalized_replicate_mode(replicate_mode),
                "source_sample_count": source_sample_count,
                "output_sample_count": len(samples),
                "source_sample_files": source_sample_files,
                "output_sample_labels": [sample.sample for sample in samples],
                "mean_definition": "arithmetic mean at exactly matching x values",
                "representative_definition": "longest trace then closest terminal storage modulus to group median",
                "series_order": list(series_order) if isinstance(series_order, list | tuple) else [],
            },
        )

    if family == "rheology_temperature_sweep" and source.is_dir():
        processed_source = processed_dir / "rheology_temperature_comparison.xlsx"
        samples = _read_rheology_temperature_comparison_samples(source)
        if not samples:
            samples = _read_confirmed_rheology_sweep_samples(
                source,
                column_confirmations,
                x_label="Temperature",
                default_x_unit="°C",
                metrics=_RHEOLOGY_SWEEP_METRICS,
            )
        source_sample_count = len(samples)
        source_sample_files = [str(sample.source) for sample in samples]
        samples = _coalesce_replicate_sweep_samples(samples, replicate_mode=replicate_mode)
        samples = _ordered_sweep_samples(samples, series_order=series_order)
        if not samples:
            raise ValueError(
                "Rheology temperature folders need at least one parseable sample export."
            )
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet="Temperature_Comparison",
        )
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="aggregate_rheology_temperature_replicates",
            parameters={
                "replicate_mode": _normalized_replicate_mode(replicate_mode),
                "source_sample_count": source_sample_count,
                "output_sample_count": len(samples),
                "source_sample_files": source_sample_files,
                "output_sample_labels": [sample.sample for sample in samples],
                "mean_definition": "arithmetic mean at exactly matching x values",
                "representative_definition": "longest trace then closest terminal storage modulus to group median",
                "series_order": list(series_order) if isinstance(series_order, list | tuple) else [],
            },
        )

    if family == "rheology_creep":
        processed_source = processed_dir / f"{source.stem}_creep_curve.csv"
        series_list = _read_rheology_interval_series_list(
            source,
            y_candidates=("creepcompliance", "compliance", "蠕变柔量"),
            y_label="Creep compliance",
            y_unit="1/Pa",
        )
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_rheology_creep_curve",
            parameters={
                "y_metric": "creep_compliance",
                "unit": "1/Pa",
                "source_sample_count": len(series_list),
                "series_order": [series.sample for series in series_list],
            },
        )

    if family == "rheology_stress_relaxation":
        processed_source = processed_dir / f"{source.stem}_stress_relaxation_curve.csv"
        series_list = _read_stress_relaxation_series_list(source)
        if _series_order_map(series_order):
            series_list = _order_curve_series(series_list, series_order)
        elif source.is_dir():
            series_list = _order_curve_series_by_shared_right_height(series_list)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_and_normalize_stress_relaxation_curves",
            parameters={
                "normalization_definition": (
                    "divide each normalized source series by its maximum absolute finite y value"
                ),
                "series_order": [series.sample for series in series_list],
                "automatic_visual_ordering": not bool(_series_order_map(series_order)) and source.is_dir(),
            },
        )

    if family == "ftir_spectrum":
        processed_source = processed_dir / "ftir_comparison.csv"
        series_list = _order_curve_series(_read_ftir_series_list(source), series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="reformat_and_order_ftir_spectra",
            parameters={"series_order": [series.sample for series in series_list]},
        )

    if family == "tensile_curve" and (source.is_dir() or source.suffix.lower() == ".csv"):
        processed_source = processed_dir / f"{source.stem}_tensile_curves.csv"
        series_list = _read_tensile_export_series_list(source)
        input_series_labels = [series.sample for series in series_list]
        representative_applied = False
        additional_outputs: tuple[Path, ...] = ()
        if _has_intake_grouped_series(series_list):
            all_source = processed_source.with_name(f"{processed_source.stem}_all.csv")
            _write_curve_table(series_list, all_source)
            series_list = _representative_tensile_series(series_list)
            representative_applied = True
            additional_outputs = (all_source,)
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_tensile_curves",
            parameters={
                "input_series_labels": input_series_labels,
                "output_series_labels": [series.sample for series in series_list],
                "representative_selection_applied": representative_applied,
                "representative_definition": (
                    "closest to group median tensile strength, then break strain, with deterministic sample order"
                    if representative_applied
                    else None
                ),
                "all_series_preserved_in_supporting_output": representative_applied,
            },
            additional_outputs=additional_outputs,
        )

    if family == "tensile_curve" and source.suffix.lower() in {".xlsx", ".xls"}:
        processed_source = processed_dir / f"{source.stem}_tensile_workbook_curves.csv"
        series_list = _read_tensile_workbook_series(source)
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_tensile_workbook_curves",
            parameters={"series_order": [series.sample for series in series_list]},
        )

    if family == "torque_curve":
        processed_source = processed_dir / "torque_comparison.csv"
        curation = _load_torque_curation(curation_path)
        series_list = [_read_torque_series(path, curation=curation) for path in _torque_source_files(source)]
        if not series_list:
            raise ValueError(f"No torque exports found under {source}.")
        series_list = _order_curve_series(series_list, series_order)
        if curation is None and not _series_order_map(series_order):
            series_list = _compact_torque_series_labels(series_list)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_torque_curves",
            parameters={
                "curation_path": str(Path(curation_path).expanduser()) if curation_path is not None else None,
                "curation_applied": curation is not None,
                "series_order": [series.sample for series in series_list],
                "time_zero_or_event_selection_requires_explicit_curation": True,
            },
        )

    if family == "impact_metric" and source.suffix.lower() in {".xlsx", ".xls", ".csv"}:
        try:
            rows = _read_impact_block_table(source)
        except ValueError:
            rows = _read_impact_compact_table(source)
        processed_source = processed_dir / f"{source.stem}_impact_replicates.csv"
        pd.DataFrame(rows).to_csv(processed_source, header=False, index=False)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_impact_replicates",
            parameters={"replicate_count": len(rows)},
        )

    return _semantic_preparation_result(
        source,
        processed_source=None,
        operation="identity",
        parameters={"reason": "The input is already plot-ready for the selected semantic family."},
    )


def build_intervention_request(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    semantic: dict[str, Any],
    request: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    category = _classify_intervention(semantic, error)
    return {
        "kind": "sciplot_intervention_request",
        "input": str(Path(input_path).expanduser()),
        "output": str(Path(output_dir).expanduser()),
        "needs_ai_intervention": bool(semantic.get("needs_ai_intervention", True)),
        "category": category,
        "semantic": semantic,
        "request": request or {},
        "error": error,
        "recommended_action": _intervention_action(category),
        "operation_mode": assisted_cleanup_mode_payload(reason=category),
    }


def _classify_intervention(semantic: dict[str, Any], error: str | None) -> str:
    if semantic.get("needs_ai_intervention"):
        if not semantic.get("semantic_family") or semantic.get("semantic_family") == "unknown":
            return "unrecognized_format"
        return "semantic_gap"
    if error and "Could not recognize" in str(error):
        return "format_mismatch"
    if error and "column" in str(error).casefold():
        return "column_missing"
    if error and ("parse" in str(error).casefold() or "read" in str(error).casefold()):
        return "parse_failure"
    if error and "not found" in str(error).casefold():
        return "missing_dependency"
    if error:
        return "render_failure"
    return "unknown"


def _intervention_action(category: str) -> str:
    actions = {
        "unrecognized_format": (
            "Use Codex-assisted cleanup to inspect this file, update semantic classification rules, "
            "add a new material rule or recipe preprocessor, create a simulated fixture, "
            "run tests, and rerun the plotting request."
        ),
        "semantic_gap": (
            "The semantic family is identified but no recipe can process it. "
            "Use assisted repair to add a new recipe module or extend an existing one with fixture data."
        ),
        "format_mismatch": (
            "The file format is recognized but columns don't match expectations. "
            "Use assisted cleanup to update column aliases in materials_rules or add a preprocessor."
        ),
        "column_missing": (
            "Expected columns are missing from the input. "
            "Use assisted cleanup to add column aliases or update the column detection logic."
        ),
        "parse_failure": (
            "The file could not be parsed. Use assisted cleanup to investigate encoding, delimiter, "
            "or file structure issues and add a fixture for this instrument export format."
        ),
        "render_failure": (
            "Rendering failed after successful preparation. Use assisted repair to inspect the "
            "render options, template compatibility, and vendor rendering path."
        ),
        "missing_dependency": (
            "A required component or file is missing. Use assisted repair to check dependencies "
            "and file paths."
        ),
    }
    return actions.get(category, actions["unrecognized_format"])


__all__ = [
    "build_intervention_request",
    "classify_source",
    "is_rheology_frequency_comparison_dir",
    "is_rheology_temperature_comparison_dir",
    "prepare_semantic_source",
]
