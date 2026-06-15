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
from sciplot_core.ingest import decode_text_file
from sciplot_core.materials_rules import match_rule, semantic_payload_from_rule

ensure_legacy_core()

from src.data_loader import read_raw_table  # noqa: E402
from src.rendering.recommendation import inspect_input_file  # noqa: E402
from src.text_normalization import normalize_unit  # noqa: E402

_DEFAULT_RENDER_OPTIONS = {
    "legend_position": "auto",
    "series_label_mode": "legend",
    "visual_theme_id": "clean_light",
    "style_preset": "nature",
    "size": "60x55",
    "palette_preset": "colorblind_safe",
}


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
    _RHEOLOGY_COMPLEX_MODULUS_METRIC,
)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _token(value: object) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", _clean_text(value).casefold())


def _decode_text(path: Path) -> str:
    return decode_text_file(path)


def _text_preview(path: Path, *, lines: int = 40) -> str:
    if path.is_dir():
        parts = [path.as_posix()]
        preview_files = [
            child
            for child in sorted(path.rglob("*"))
            if child.is_file() and child.suffix.lower() in {".csv", ".tsv", ".txt"}
        ]
        for child in preview_files[:3]:
            with contextlib_suppress_decode():
                parts.append("\n".join(_decode_text(child).splitlines()[:lines]))
        return "\n".join(parts)
    if not path.is_file():
        return path.as_posix()
    with contextlib_suppress_decode():
        return "\n".join(_decode_text(path).splitlines()[:lines])
    return path.as_posix()


class contextlib_suppress_decode:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> bool:
        return exc_type in {UnicodeError, OSError, ValueError}


def _vendor_inspection(input_path: Path, sheet: str | int) -> tuple[dict[str, Any] | None, str | None]:
    if input_path.is_dir():
        return None, "Vendor inspect expects a file, not a directory."
    try:
        payload = inspect_input_file(input_path, sheet)
    except Exception as exc:
        return None, str(exc)
    return _json_safe(payload), None


def _json_safe(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(value.__dict__)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


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
        return _classification(
            semantic_family="impact_metric",
            recommended_recipe="metrics_swelling",
            template=_template_from_vendor(vendor_inspection, "box"),
            render_options=_render_options_from_vendor(vendor_inspection),
            confidence=85.0,
            reason="Detected impact or impact-resistance metric data.",
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
            return unit
    return fallback


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


def _read_rheology_sweep_sample(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    x_label: str,
    default_x_unit: str,
) -> RheologySweepSample:
    raw = read_raw_table(source).dropna(axis=1, how="all")
    header_index = _find_interval_header(raw)
    headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
    units = [_clean_text(value) for value in raw.iloc[min(header_index + 2, raw.shape[0] - 1)].tolist()]
    x_index = _find_column(headers, x_aliases)
    metric_indexes: dict[str, int] = {}
    metric_units: dict[str, str] = {}
    for key, _label, aliases, default_unit in _RHEOLOGY_SWEEP_METRICS:
        try:
            metric_index = _find_column(headers, aliases)
        except ValueError:
            continue
        metric_indexes[key] = metric_index
        metric_units[key] = _unit_for(units, metric_index, default_unit)
    if "storage_modulus" not in metric_indexes:
        raise ValueError(f"Could not find storage modulus in rheology sweep source {source}.")
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
    text = _decode_text(source)
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
    try:
        raw = read_raw_table(source).dropna(axis=1, how="all")
        evidence = " ".join(str(value) for value in [*raw.columns.tolist(), *raw.iloc[:4].to_numpy().ravel().tolist()])
        if "torque" in evidence.casefold() or "转矩" in evidence:
            return raw
    except Exception:
        pass
    last_error: Exception | None = None
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


def prepare_semantic_source(
    input_path: str | Path,
    *,
    output_dir: Path,
    semantic: dict[str, Any],
    curation_path: str | Path | None = None,
    series_order: object = None,
) -> dict[str, Any]:
    source = Path(input_path).expanduser()
    processed_dir = output_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    family = semantic["semantic_family"]

    if family == "rheology_frequency" and source.is_dir():
        processed_source = processed_dir / "rheology_frequency_comparison.xlsx"
        samples = _ordered_sweep_samples(
            _read_rheology_frequency_comparison_samples(source),
            series_order=series_order,
        )
        if len(samples) < 2:
            raise ValueError(
                "Rheology frequency comparison folders need at least two parseable sample exports."
            )
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet="Frequency_Comparison",
            metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
        )
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

    if family == "rheology_temperature_sweep" and source.is_dir():
        processed_source = processed_dir / "rheology_temperature_comparison.xlsx"
        samples = _ordered_sweep_samples(
            _read_rheology_temperature_comparison_samples(source),
            series_order=series_order,
        )
        if len(samples) < 2:
            raise ValueError(
                "Rheology temperature comparison folders need at least two parseable sample exports."
            )
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet="Temperature_Comparison",
        )
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

    if family == "rheology_creep":
        processed_source = processed_dir / f"{source.stem}_creep_curve.csv"
        series = _read_rheology_interval_series(
            source,
            y_candidates=("creepcompliance", "compliance", "蠕变柔量"),
            y_label="Creep compliance",
            y_unit="1/Pa",
        )
        _write_curve_table([series], processed_source)
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

    if family == "rheology_stress_relaxation":
        processed_source = processed_dir / f"{source.stem}_stress_relaxation_curve.csv"
        series_list = _read_stress_relaxation_series_list(source)
        if _series_order_map(series_order):
            series_list = _order_curve_series(series_list, series_order)
        else:
            series_list = _order_curve_series_by_shared_right_height(series_list)
        _write_curve_table(series_list, processed_source)
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

    if family == "tensile_curve" and (source.is_dir() or source.suffix.lower() == ".csv"):
        processed_source = processed_dir / f"{source.stem}_tensile_curves.csv"
        series_list = _read_tensile_export_series_list(source)
        if _has_intake_grouped_series(series_list):
            all_source = processed_source.with_name(f"{processed_source.stem}_all.csv")
            _write_curve_table(series_list, all_source)
            series_list = _representative_tensile_series(series_list)
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

    if family == "tensile_curve" and source.suffix.lower() in {".xlsx", ".xls"}:
        processed_source = processed_dir / f"{source.stem}_tensile_workbook_curves.csv"
        series_list = _read_tensile_workbook_series(source)
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

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
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

    if family == "impact_metric" and source.suffix.lower() in {".xlsx", ".xls", ".csv"}:
        try:
            rows = _read_impact_block_table(source)
        except ValueError:
            rows = _read_impact_compact_table(source)
        processed_source = processed_dir / f"{source.stem}_impact_replicates.csv"
        pd.DataFrame(rows).to_csv(processed_source, header=False, index=False)
        return {"source": str(processed_source), "processed": True, "processed_source": str(processed_source)}

    return {"source": str(source), "processed": False, "processed_source": None}


def build_intervention_request(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    semantic: dict[str, Any],
    request: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "sciplot_intervention_request",
        "input": str(Path(input_path).expanduser()),
        "output": str(Path(output_dir).expanduser()),
        "needs_ai_intervention": bool(semantic.get("needs_ai_intervention", True)),
        "semantic": semantic,
        "request": request or {},
        "error": error,
        "recommended_action": (
            "Codex should inspect this file, update semantic classification or recipe preprocessing, "
            "add a simulated fixture, run tests, and rerun the plotting request."
        ),
    }


__all__ = [
    "build_intervention_request",
    "classify_source",
    "is_rheology_frequency_comparison_dir",
    "is_rheology_temperature_comparison_dir",
    "prepare_semantic_source",
]
