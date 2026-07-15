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
from sciplot_core._utils import (
    clean_text as _clean_text,
    decode_text as _decode_text,
    json_safe as _json_safe,
    text_preview as _text_preview,
    token as _token,
)
from sciplot_core.ingest import normalized_source
from sciplot_core.materials_rules import (
    format_unit_label,
    get_rule,
    match_rule,
    semantic_payload_from_rule,
    tensile_curve_metric_values,
)
from sciplot_core.operation_modes import assisted_cleanup_mode_payload
from sciplot_core.policy import DEFAULT_RENDER_OPTIONS as _DEFAULT_RENDER_OPTIONS
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
    diagnostics: dict[str, Any] | None = None


@dataclass(frozen=True)
class RheologySweepSample:
    sample: str
    source: Path
    x_label: str
    x_unit: str
    metric_units: dict[str, str]
    rows: tuple[dict[str, float], ...]
    interval_count: int = 1
    selected_interval_index: int = 1
    interval_selection_policy: str = "single_interval"
    source_x_unit: str = ""
    x_conversion: dict[str, Any] | None = None
    metric_conversions: dict[str, dict[str, Any]] | None = None


@dataclass(frozen=True)
class ImpactReplicatePayload:
    rows: tuple[tuple[object, ...], ...]
    samples: tuple[str, ...]
    replicate_counts: tuple[int, ...]
    values: tuple[tuple[float, ...], ...]
    unit: str = "kJ/m2"

    @property
    def total_replicates(self) -> int:
        return sum(self.replicate_counts)


class _ImpactDataValidationError(ValueError):
    """Raised when an impact-shaped table contains scientifically invalid data."""


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
_RHEOLOGY_AMPLITUDE_OUTPUT_METRICS = (
    _RHEOLOGY_SWEEP_METRICS[0],
    _RHEOLOGY_SWEEP_METRICS[1],
    _RHEOLOGY_SWEEP_METRICS[2],
)
_RHEOLOGY_TIME_OUTPUT_METRICS = (_RHEOLOGY_COMPLEX_MODULUS_METRIC,)


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
    match_vendor_model = vendor_model
    match_experiment_family = experiment_family
    structured_temperature_comparison = bool(path.is_dir() and is_rheology_temperature_comparison_dir(path))
    if vendor_model == "frequency_metric_sheet" and (
        "temperaturesweep" in compact_evidence
        or "temperatureramp" in compact_evidence
        or structured_temperature_comparison
    ):
        # The legacy recommendation layer calls any aligned rheology metric
        # sheet a frequency sheet, even when the instrument metadata and X
        # column explicitly identify a temperature sweep.  Keep the vendor
        # model for diagnostics, but do not let that structural shortcut
        # override stronger experiment semantics.
        match_vendor_model = None
        match_experiment_family = None
    if requested_rule_id is None and structured_temperature_comparison:
        return semantic_payload_from_rule(
            get_rule("rheology_temperature_sweep"),
            confidence=94.0,
            reason=(
                "Detected a temperature-sweep folder with at least two structurally parseable sample exports; "
                "temperature semantics take precedence over constant angular-frequency columns."
            ),
            vendor_model=vendor_model,
            vendor_error=vendor_error,
        )
    matched_rule = match_rule(
        evidence=evidence,
        compact_evidence=compact_evidence,
        vendor_model=match_vendor_model,
        experiment_family=match_experiment_family,
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
        confidence = 100.0 if requested_rule_id else max(80.0, 98.0 - matched_rule.priority / 2)
        return semantic_payload_from_rule(
            matched_rule,
            confidence=confidence,
            reason=(
                f"Explicit material rule `{matched_rule.rule_id}` selected by the user or Luna/Codex."
                if requested_rule_id
                else matched_rule.reason or f"Matched material rule `{matched_rule.rule_id}`."
            ),
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
            confidence=86.0,
            reason=(
                "Detected impact-strength data; preserve every observation and use the categorical replicate "
                "Veusz contract without fabricating missing replicates."
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


def _float(value: object, *, decimal_comma: bool = False) -> float | None:
    text = (
        _clean_text(value)
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
    )
    if not text:
        return None
    if decimal_comma:
        if "," in text and "." in text:
            text = text.replace(".", "")
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _read_raw_table_normalized(path: Path) -> pd.DataFrame:
    with normalized_source(path) as normalized:
        return read_raw_table(normalized)


def _table_uses_decimal_comma(raw: pd.DataFrame, *, start_row: int = 0) -> bool:
    comma_decimal = 0
    point_decimal = 0
    stop = min(raw.shape[0], start_row + 240)
    for row_index in range(start_row, stop):
        for value in raw.iloc[row_index].tolist():
            text = _clean_text(value)
            if re.search(r"[+-]?\d+,\d+(?:[Ee][+-]?\d+)?", text):
                comma_decimal += 1
            if re.search(r"[+-]?\d+\.\d+(?:[Ee][+-]?\d+)?", text):
                point_decimal += 1
    return comma_decimal >= 3 and comma_decimal > point_decimal * 2


def _read_candidate_tables(source: Path) -> list[tuple[str, pd.DataFrame]]:
    if source.is_dir():
        paths = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        ]
    else:
        paths = [source]
    tables: list[tuple[str, pd.DataFrame]] = []
    for path in paths:
        if path.suffix.lower() in {".xlsx", ".xls"}:
            workbook = pd.ExcelFile(path)
            tables.extend(
                (
                    f"{path.stem}:{sheet_name}",
                    pd.read_excel(path, sheet_name=sheet_name, header=None).dropna(axis=1, how="all"),
                )
                for sheet_name in workbook.sheet_names
            )
        else:
            tables.append((path.stem, _read_raw_table_normalized(path).dropna(axis=1, how="all")))
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
    if "%" in raw:
        return True
    token = _token(value)
    if not token:
        return False
    return token in {
        "c",
        "degc",
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
    } or token in {"", "1"}


def _unit_row_score(raw: pd.DataFrame, row_index: int, columns: tuple[int, ...]) -> int:
    if row_index >= raw.shape[0]:
        return -1
    return sum(1 for column in columns if _looks_like_unit(raw.iat[row_index, column]))


def _sample_from_row(raw: pd.DataFrame, row_index: int | None, *, start: int, stop: int, fallback: str) -> str:
    if row_index is None or row_index >= raw.shape[0]:
        return fallback
    for column in range(start, min(stop, raw.shape[1])):
        value = _clean_text(raw.iat[row_index, column])
        if (
            value
            and (not _looks_like_unit(value) or len(_token(value)) > 5)
            and not _axis_match(value, ("time", "strain", "stress", "σ"))
        ):
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
            first_row_is_numeric_data = any(
                _float(raw.iat[first_extra, x_index]) is not None and _float(raw.iat[first_extra, y_index]) is not None
                for x_index, y_index in pairs
                if first_extra < raw.shape[0]
            )
            preceding_sample_index = header_index - 1
            preceding_row_has_samples = header_index > 0 and all(
                any(
                    (label := _clean_text(raw.iat[preceding_sample_index, column]))
                    and _float(label) is None
                    and (not _looks_like_unit(label) or len(_token(label)) > 5)
                    and not _axis_match(label, (*x_aliases, *y_aliases))
                    for column in range(x_index, min(y_index + 1, raw.shape[1]))
                )
                for x_index, y_index in pairs
            )
            if first_row_is_numeric_data:
                sample_index = preceding_sample_index if preceding_row_has_samples else None
            else:
                sample_index = header_index + 1
            data_start = header_index + 1 if first_row_is_numeric_data else header_index + 2
        else:
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
            best = [
                CurveSeriesPayload(
                    sample=item.sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={**(item.diagnostics or {}), "source_table": sheet_name},
                )
                for item in series
            ]
    return best


def _read_agilent_gpc_series(source: Path) -> CurveSeriesPayload | None:
    """Read the analysed RT/RI slice from an Agilent GPC/SEC workbook."""

    tables = _read_candidate_tables(source)
    sample = source.stem
    detector_unit = "a.u."
    for _table_name, raw in tables:
        for row_index in range(min(raw.shape[0], 80)):
            first = _token(raw.iat[row_index, 0]) if raw.shape[1] else ""
            if first == "samplename" and raw.shape[1] > 1:
                sample = _clean_text(raw.iat[row_index, 1]) or sample
            headers = [_token(value) for value in raw.iloc[row_index].tolist()]
            if "detectortype" not in headers or "detectorunits" not in headers:
                continue
            detector_column = headers.index("detectortype")
            unit_column = headers.index("detectorunits")
            for data_index in range(row_index + 1, min(raw.shape[0], row_index + 16)):
                if _token(raw.iat[data_index, detector_column]) != "ri":
                    continue
                detector_unit = _clean_text(raw.iat[data_index, unit_column]) or detector_unit
                break

    best_points: list[tuple[float, float]] = []
    best_table = ""
    for table_name, raw in tables:
        for header_index in range(max(0, raw.shape[0] - 1)):
            headers = [_token(value) for value in raw.iloc[header_index].tolist()]
            x_index = next((index for index, value in enumerate(headers) if value in {"rt", "rtmin", "rtmins"}), None)
            y_index = next((index for index, value in enumerate(headers) if value == "ri"), None)
            if x_index is None or y_index is None:
                continue
            points: list[tuple[float, float]] = []
            for row_index in range(header_index + 1, raw.shape[0]):
                x_value = _float(raw.iat[row_index, x_index])
                y_value = _float(raw.iat[row_index, y_index])
                if x_value is not None and y_value is not None:
                    points.append((x_value, y_value))
            if len(points) > len(best_points):
                best_points = points
                best_table = table_name
    if not best_points:
        return None
    if _float(sample) is not None:
        sample = f"Sample {sample}"
    return CurveSeriesPayload(
        sample=sample,
        x_label="Elution time",
        x_unit="min",
        y_label="Detector response",
        y_unit=detector_unit,
        points=tuple(best_points),
        diagnostics={
            "source_table": best_table,
            "source_file": source.name,
            "detector": "RI",
            "detector_unit": detector_unit,
        },
    )


def _read_gpc_series_list(source: Path) -> list[CurveSeriesPayload]:
    """Extract one or more RI chromatograms from Agilent or canonical GPC tables."""

    paths = (
        [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        ]
        if source.is_dir()
        else [source]
    )
    result: list[CurveSeriesPayload] = []
    for path in paths:
        agilent_series = _read_agilent_gpc_series(path)
        if agilent_series is not None:
            candidate = [agilent_series]
        else:
            candidate = _scan_curve_series_source(
                path,
                x_aliases=("elution time", "time", "rt"),
                y_aliases=("detector response", "rayleigh ratio", "dri", "ri"),
                x_label="Elution time",
                y_label="Detector response",
                default_x_unit="min",
                default_y_unit="a.u.",
                sample_prefix=path.stem,
            )
        if len(candidate) == 1:
            item = candidate[0]
            sample = item.sample if agilent_series is not None else path.stem
            candidate = [
                CurveSeriesPayload(
                    sample=sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={**(item.diagnostics or {}), "source_file": path.name},
                )
            ]
        else:
            candidate = [
                CurveSeriesPayload(
                    sample=item.sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={**(item.diagnostics or {}), "source_file": path.name},
                )
                for item in candidate
            ]
        result.extend(candidate)
    return result


_SWELLING_Y_ALIASES = ("swelling ratio", "ai/a0", "normalized projected area")


def _swelling_time_conversion(header: object) -> tuple[str, float]:
    text = _clean_text(header).casefold().replace("µ", "u")
    if re.search(r"\b(?:s|sec|secs|second|seconds)\b", text) or "(s)" in text or "[s]" in text:
        return "s", 1.0 / 3600.0
    if re.search(r"\b(?:min|mins|minute|minutes)\b", text) or "(min)" in text or "[min]" in text:
        return "min", 1.0 / 60.0
    return "h", 1.0


def _source_row_number(value: object) -> int | str:
    try:
        return int(value) + 1
    except (TypeError, ValueError):
        return str(value)


def _contiguous_table_stop(raw: pd.DataFrame, data_start: int) -> int:
    """Stop before a disconnected lower table whose blank separator was dropped."""

    stop = raw.shape[0]
    for row_position in range(data_start + 1, raw.shape[0]):
        try:
            previous = int(raw.index[row_position - 1])
            current = int(raw.index[row_position])
        except (TypeError, ValueError):
            continue
        if current - previous > 1:
            stop = row_position
            break
    return stop


def _nearest_row_label(raw: pd.DataFrame, row_position: int, column: int) -> str:
    if row_position < 0 or row_position >= raw.shape[0]:
        return ""
    for candidate_column in range(column, 0, -1):
        label = _clean_text(raw.iat[row_position, candidate_column])
        if label:
            return label
    return ""


def _clean_swelling_condition(value: object, fallback: str) -> str:
    label = _clean_text(value).replace("_", " ")
    label = re.sub(r"^\s*fig(?:ure)?\s*\d+\s*\([^)]+\)\s*:\s*", "", label, flags=re.IGNORECASE)
    label = re.sub(r"\s+", " ", label).strip(" :;,-")
    return label or fallback or "Sample"


def _replicate_label(value: object, fallback: int) -> str:
    numeric = _float(value)
    if numeric is not None and numeric.is_integer():
        return str(int(numeric))
    return _clean_text(value) or str(fallback)


def _parallel_swelling_series(sheet_name: str, raw: pd.DataFrame) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for header_index in range(min(raw.shape[0], 32)):
        headers = raw.iloc[header_index].tolist()
        pairs: list[tuple[int, int]] = []
        for x_index, header in enumerate(headers[:-1]):
            if not _axis_match(header, ("time",)):
                continue
            for y_index in range(x_index + 1, min(x_index + 4, raw.shape[1])):
                if _axis_match(headers[y_index], _SWELLING_Y_ALIASES):
                    pairs.append((x_index, y_index))
                    break
        if not pairs:
            continue
        data_start = header_index + 1
        while data_start < raw.shape[0] and not any(
            _float(raw.iat[data_start, x_index]) is not None
            and _float(raw.iat[data_start, y_index]) is not None
            for x_index, y_index in pairs
        ):
            data_start += 1
        if data_start >= raw.shape[0]:
            continue
        data_stop = _contiguous_table_stop(raw, data_start)
        excluded_rows = raw.shape[0] - data_stop
        block_diagnostics: dict[str, Any] = {
            "selection_policy": "contiguous_labeled_swelling_block",
            "source_header_row": _source_row_number(raw.index[header_index]),
            "source_data_row_start": _source_row_number(raw.index[data_start]),
            "source_data_row_end": _source_row_number(raw.index[data_stop - 1]),
            "excluded_disconnected_rows": excluded_rows,
        }
        if excluded_rows:
            block_diagnostics["excluded_source_row_span"] = [
                _source_row_number(raw.index[data_stop]),
                _source_row_number(raw.index[-1]),
            ]
        candidate: list[CurveSeriesPayload] = []
        for series_index, (x_index, y_index) in enumerate(pairs, start=1):
            points: list[tuple[float, float]] = []
            source_unit, factor = _swelling_time_conversion(headers[x_index])
            for row_index in range(data_start, data_stop):
                x_value = _float(raw.iat[row_index, x_index])
                y_value = _float(raw.iat[row_index, y_index])
                if x_value is not None and y_value is not None:
                    points.append((x_value * factor, y_value))
            if not points:
                continue
            condition = _clean_swelling_condition(
                _nearest_row_label(raw, header_index - 2, x_index),
                sheet_name,
            )
            replicate = _replicate_label(
                raw.iat[header_index - 1, x_index] if header_index > 0 else None,
                series_index,
            )
            candidate.append(
                CurveSeriesPayload(
                    sample=f"{condition} replicate {replicate}",
                    x_label="Time",
                    x_unit="h",
                    y_label="Swelling ratio",
                    y_unit="1",
                    points=tuple(points),
                    diagnostics={
                        "source_table": sheet_name,
                        "source_columns": {
                            "x": _clean_text(headers[x_index]),
                            "y": _clean_text(headers[y_index]),
                        },
                        "condition": condition,
                        "replicate": replicate,
                        "time_conversion": {
                            "source_unit": source_unit,
                            "canonical_unit": "h",
                            "factor": factor,
                        },
                        "source_block": block_diagnostics,
                    },
                )
            )
        if sum(len(item.points) for item in candidate) > sum(len(item.points) for item in best):
            best = candidate
    return best


def _read_swelling_series_list(source: Path) -> list[CurveSeriesPayload]:
    """Keep labeled swelling observations separate and normalize time to hours."""

    best: list[CurveSeriesPayload] = []
    for sheet_name, raw in _read_candidate_tables(source):
        parallel = _parallel_swelling_series(sheet_name, raw)
        if sum(len(item.points) for item in parallel) > sum(len(item.points) for item in best):
            best = parallel
        for header_index in range(min(raw.shape[0], 32)):
            headers = raw.iloc[header_index].tolist()
            sample_column = next(
                (index for index, value in enumerate(headers) if _token(value) in {"sample", "samplename"}),
                None,
            )
            time_column = next(
                (index for index, value in enumerate(headers) if _axis_match(value, ("time",))),
                None,
            )
            swelling_column = next(
                (index for index, value in enumerate(headers) if _axis_match(value, _SWELLING_Y_ALIASES)),
                None,
            )
            if time_column is None or swelling_column is None:
                continue
            data_start = header_index + 1
            data_stop = _contiguous_table_stop(raw, data_start)
            source_unit, factor = _swelling_time_conversion(headers[time_column])
            grouped: dict[str, list[tuple[float, float]]] = {}
            for row_index in range(data_start, data_stop):
                x_value = _float(raw.iat[row_index, time_column])
                y_value = _float(raw.iat[row_index, swelling_column])
                if x_value is None or y_value is None:
                    continue
                sample = (
                    (_clean_text(raw.iat[row_index, sample_column]) if sample_column is not None else sheet_name)
                    or sheet_name
                    or "Sample"
                )
                grouped.setdefault(sample, []).append((x_value * factor, y_value))
            candidate = [
                CurveSeriesPayload(
                    sample=sample,
                    x_label="Time",
                    x_unit="h",
                    y_label="Swelling ratio",
                    y_unit="1",
                    points=tuple(points),
                    diagnostics={
                        "source_table": sheet_name,
                        "source_columns": {
                            "x": _clean_text(headers[time_column]),
                            "y": _clean_text(headers[swelling_column]),
                        },
                        "time_conversion": {
                            "source_unit": source_unit,
                            "canonical_unit": "h",
                            "factor": factor,
                        },
                    },
                )
                for sample, points in grouped.items()
                if points
            ]
            if sum(len(item.points) for item in candidate) > sum(len(item.points) for item in best):
                best = candidate
    if best:
        return best
    return _scan_curve_series_source(
        source,
        x_aliases=("time",),
        y_aliases=_SWELLING_Y_ALIASES,
        x_label="Time",
        y_label="Swelling ratio",
        default_x_unit="h",
        default_y_unit="1",
        sample_prefix=source.stem,
    )


def _constant_sample_label(source: Path) -> str | None:
    for _sheet_name, raw in _read_candidate_tables(source):
        for header_index in range(min(raw.shape[0], 32)):
            sample_column = next(
                (
                    index
                    for index, value in enumerate(raw.iloc[header_index].tolist())
                    if _token(value) in {"sample", "samplename"}
                ),
                None,
            )
            if sample_column is None:
                continue
            labels = list(
                dict.fromkeys(
                    _clean_text(raw.iat[row_index, sample_column])
                    for row_index in range(header_index + 1, raw.shape[0])
                    if _clean_text(raw.iat[row_index, sample_column])
                )
            )
            if len(labels) == 1:
                return labels[0]
    return None


def _read_rheology_interval_series(
    source: Path,
    *,
    y_candidates: tuple[str, ...],
    y_label: str,
    y_unit: str,
    preferred_result_tokens: tuple[str, ...] = (),
) -> CurveSeriesPayload:
    raw = _read_raw_table_normalized(source).dropna(axis=1, how="all")
    result_markers: list[tuple[int, str]] = []
    header_indexes: list[int] = []
    for row_index in range(raw.shape[0]):
        row = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        first_token = _token(row[0]) if row else ""
        if first_token == "result":
            result_markers.append((row_index, next((value for value in row[1:] if value), "")))
        elif first_token == "intervaldata":
            header_indexes.append(row_index)
    if not header_indexes:
        raise ValueError("Could not find `Interval data` section in rheology export.")

    spans: list[tuple[int, int, str]] = []
    if result_markers:
        first_marker = result_markers[0][0]
        if any(header_index < first_marker for header_index in header_indexes):
            spans.append((-1, first_marker, ""))
        for marker_index, (start, label) in enumerate(result_markers):
            stop = result_markers[marker_index + 1][0] if marker_index + 1 < len(result_markers) else raw.shape[0]
            spans.append((start, stop, label))
    else:
        spans.append((-1, raw.shape[0], ""))

    result_candidates: list[dict[str, Any]] = []
    for result_index, (start, stop, result_label) in enumerate(spans, start=1):
        result_headers = [header_index for header_index in header_indexes if start < header_index < stop]
        intervals: list[dict[str, Any]] = []
        for interval_index, header_index in enumerate(result_headers, start=1):
            headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
            units = [_clean_text(value) for value in raw.iloc[min(header_index + 2, raw.shape[0] - 1)].tolist()]
            x_index = _find_column(headers, ("time", "时间"))
            y_index = _find_column(headers, y_candidates)
            next_header = result_headers[interval_index] if interval_index < len(result_headers) else stop
            interval_stop = next_header
            for row_index in range(header_index + 1, next_header):
                first_value = raw.iloc[row_index, 0] if raw.shape[1] else None
                if _token(first_value) in {"intervalanddatapoints", "result"}:
                    interval_stop = row_index
                    break
            points: list[tuple[float, float]] = []
            numeric_x_rows = 0
            for row_index in range(header_index + 1, interval_stop):
                row = raw.iloc[row_index].tolist()
                x_value = _float(row[x_index] if x_index < len(row) else None)
                y_value = _float(row[y_index] if y_index < len(row) else None)
                if x_value is not None and math.isfinite(x_value):
                    numeric_x_rows += 1
                if x_value is not None and y_value is not None and math.isfinite(x_value) and math.isfinite(y_value):
                    points.append((x_value, y_value))
            if points:
                intervals.append(
                    {
                        "interval_index": interval_index,
                        "header_index": header_index,
                        "x_unit": _unit_for(units, x_index, "s"),
                        "y_unit": _unit_for(units, y_index, y_unit),
                        "points": tuple(points),
                        "numeric_x_rows": numeric_x_rows,
                    }
                )
        combined_points = tuple(point for interval in intervals for point in interval["points"])
        if not combined_points:
            continue
        normalized_label = _token(result_label)
        preferred = any(_token(token) in normalized_label for token in preferred_result_tokens if _token(token))
        numeric_x_rows = sum(int(interval["numeric_x_rows"]) for interval in intervals)
        result_candidates.append(
            {
                "result_index": result_index,
                "result_label": result_label,
                "preferred": preferred,
                "intervals": intervals,
                "points": combined_points,
                "coverage": len(combined_points) / max(numeric_x_rows, 1),
            }
        )
    if not result_candidates:
        raise ValueError(f"No numeric rheology interval points found in {source}.")

    selected = max(
        result_candidates,
        key=lambda item: (
            int(item["preferred"]),
            float(item["coverage"]),
            len(item["points"]),
            len(item["intervals"]),
            int(item["result_index"]),
        ),
    )
    selected_points = tuple(selected["points"])
    x_deltas = [right[0] - left[0] for left, right in zip(selected_points, selected_points[1:], strict=False)]
    if x_deltas and all(delta >= 0.0 for delta in x_deltas):
        x_direction = "increasing"
    elif x_deltas and all(delta <= 0.0 for delta in x_deltas):
        x_direction = "decreasing"
    else:
        x_direction = "mixed"
    selected_intervals = selected["intervals"]
    diagnostics = {
        "result_selection_policy": (
            "preferred_result_label_then_completeness" if preferred_result_tokens else "most_complete_result"
        ),
        "preferred_result_tokens": list(preferred_result_tokens),
        "detected_result_count": len(result_candidates),
        "detected_interval_count": sum(len(item["intervals"]) for item in result_candidates),
        "selected_result_index": selected["result_index"],
        "selected_result_label": selected["result_label"],
        "selected_interval_indexes": [interval["interval_index"] for interval in selected_intervals],
        "selected_interval_point_counts": [len(interval["points"]) for interval in selected_intervals],
        "selected_point_count": len(selected_points),
        "selected_y_coverage_fraction": round(float(selected["coverage"]), 6),
        "x_direction": x_direction,
        "candidate_results": [
            {
                "result_index": item["result_index"],
                "result_label": item["result_label"],
                "preferred_label_match": bool(item["preferred"]),
                "interval_count": len(item["intervals"]),
                "valid_point_count": len(item["points"]),
                "y_coverage_fraction": round(float(item["coverage"]), 6),
            }
            for item in result_candidates
        ],
    }
    return CurveSeriesPayload(
        sample=_sample_from_interval_metadata(raw, source.stem),
        x_label="Time",
        x_unit=str(selected_intervals[0]["x_unit"]),
        y_label=y_label,
        y_unit=str(selected_intervals[0]["y_unit"]),
        points=selected_points,
        diagnostics=diagnostics,
    )


def _read_rheology_interval_series_list(
    source: Path,
    *,
    y_candidates: tuple[str, ...],
    y_label: str,
    y_unit: str,
    preferred_result_tokens: tuple[str, ...] = (),
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
                preferred_result_tokens=preferred_result_tokens,
            )
            series_list.append(
                CurveSeriesPayload(
                    sample=_source_display_sample(candidate),
                    x_label=series.x_label,
                    x_unit=series.x_unit,
                    y_label=series.y_label,
                    y_unit=series.y_unit,
                    points=series.points,
                    diagnostics=series.diagnostics,
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
    candidates = sorted(
        (child for child in source.iterdir() if child.is_file() and child.suffix.lower() in suffixes),
        key=lambda path: path.name.casefold(),
    )
    instrument_exports = [candidate for candidate in candidates if candidate.suffix.lower() in {".csv", ".tsv", ".txt"}]
    # Instrument folders often retain an Origin/Excel workbook derived from
    # the same raw exports.  Prefer the original text exports as the sole
    # evidence surface so a saved analysis workbook cannot become a duplicate
    # sample during direct CLI preparation.
    return instrument_exports or candidates


def _source_display_sample(source: Path) -> str:
    stem = source.stem.strip()
    if "__" in stem:
        group, _rest = stem.split("__", 1)
        group = group.strip()
        if group:
            return group
    return stem


def _find_rheology_sweep_headers(
    raw: pd.DataFrame,
    *,
    x_aliases: tuple[str, ...],
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...] = _RHEOLOGY_SWEEP_METRICS,
) -> list[int]:
    metric_alias_groups = tuple(metric[2] for metric in metrics)

    def is_sweep_header(row_index: int) -> bool:
        headers = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        try:
            _find_column(headers, x_aliases)
            return any(
                any(_axis_match(header, aliases) for header in headers)
                for aliases in metric_alias_groups
            )
        except ValueError:
            return False

    # Instrument exports can include project metadata such as an operator name
    # containing the single-letter symbolic alias ``G``.  That metadata may
    # also contain "frequency sweep", so a loose token scan can mistake it for
    # the table header.  The explicitly labelled interval header is the
    # authority whenever it exists; the generic scan remains available for
    # plain public tables without an interval wrapper.
    interval_matches = [
        row_index
        for row_index in range(raw.shape[0])
        if _token(raw.iat[row_index, 0] if raw.shape[1] else None) == "intervaldata"
        and is_sweep_header(row_index)
    ]
    if interval_matches:
        return interval_matches

    matches: list[int] = []
    for row_index in range(raw.shape[0]):
        if is_sweep_header(row_index):
            matches.append(row_index)
    if matches:
        return matches
    raise ValueError("Could not find rheology sweep X and requested response columns.")


def _unit_conversion(source_unit: str, target_unit: str) -> tuple[str, float, str]:
    source = source_unit.strip()
    target = format_unit_label(target_unit).strip()
    if source == target:
        return target, 1.0, "identity"
    conversions = {
        ("1", "%"): (100.0, "fraction_to_percent"),
        ("fraction", "%"): (100.0, "fraction_to_percent"),
        ("kPa", "Pa"): (1000.0, "kPa_to_Pa"),
        ("MPa", "Pa"): (1_000_000.0, "MPa_to_Pa"),
        ("Pa", "kPa"): (0.001, "Pa_to_kPa"),
        ("Pa", "MPa"): (0.000001, "Pa_to_MPa"),
    }
    conversion = conversions.get((source, target))
    if conversion is None:
        return source or target, 1.0, "source_unit_preserved"
    factor, method = conversion
    return target, factor, method


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
    interval_selection: str = "all_numeric_rows",
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...] = _RHEOLOGY_SWEEP_METRICS,
) -> RheologySweepSample:
    raw = _read_raw_table_normalized(source).dropna(axis=1, how="all")
    header_indexes = _find_rheology_sweep_headers(raw, x_aliases=x_aliases, metrics=metrics)
    select_last_interval = interval_selection == "last_numeric_interval"
    header_index = header_indexes[-1] if select_last_interval else header_indexes[0]
    headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
    x_index = _find_column(headers, x_aliases)
    metric_indexes: dict[str, int] = {}
    for key, _label, aliases, _default_unit in metrics:
        try:
            metric_index = _find_column(headers, aliases)
        except ValueError:
            continue
        metric_indexes[key] = metric_index
    if not metric_indexes:
        raise ValueError(f"Could not find a requested rheology response in {source}.")
    units = _rheology_sweep_units(
        raw,
        header_index=header_index,
        columns=(x_index, *metric_indexes.values()),
    )
    source_x_unit = _unit_for(units, x_index, default_x_unit)
    x_unit, x_factor, x_method = _unit_conversion(source_x_unit, default_x_unit)
    metric_units: dict[str, str] = {}
    metric_factors: dict[str, float] = {}
    metric_conversions: dict[str, dict[str, Any]] = {}
    for key, _label, _aliases, default_unit in metrics:
        metric_index = metric_indexes.get(key)
        if metric_index is None:
            continue
        source_unit = _unit_for(units, metric_index, default_unit)
        output_unit, factor, method = _unit_conversion(source_unit, default_unit)
        metric_units[key] = output_unit
        metric_factors[key] = factor
        metric_conversions[key] = {
            "source_unit": source_unit,
            "output_unit": output_unit,
            "factor": factor,
            "method": method,
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

    decimal_comma = _table_uses_decimal_comma(raw, start_row=header_index + 1)
    rows: list[dict[str, float]] = []
    for row_index in range(header_index + 1, raw.shape[0]):
        x_value = _float(raw.iat[row_index, x_index], decimal_comma=decimal_comma)
        if x_value is None:
            continue
        row: dict[str, float] = {"x": x_value * x_factor}
        for key, metric_index in metric_indexes.items():
            y_value = _float(raw.iat[row_index, metric_index], decimal_comma=decimal_comma)
            if y_value is not None:
                row[key] = y_value * metric_factors.get(key, 1.0)
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
        x_unit=x_unit,
        metric_units=metric_units,
        rows=tuple(rows),
        interval_count=len(header_indexes),
        selected_interval_index=(len(header_indexes) if select_last_interval else 1),
        interval_selection_policy=(
            "last_numeric_interval" if select_last_interval and len(header_indexes) > 1 else "single_interval"
        ),
        source_x_unit=source_x_unit,
        x_conversion={
            "source_unit": source_x_unit,
            "output_unit": x_unit,
            "factor": x_factor,
            "method": x_method,
        },
        metric_conversions=metric_conversions,
    )


def _read_rheology_sweep_comparison_samples(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    x_label: str,
    default_x_unit: str,
    interval_selection: str = "all_numeric_rows",
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...] = _RHEOLOGY_SWEEP_METRICS,
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
                    interval_selection=interval_selection,
                    metrics=metrics,
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
        interval_selection="last_numeric_interval",
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
    raw = _read_raw_table_normalized(source).dropna(axis=1, how="all").dropna(how="all")
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
        key: _unit_for(units, metric_index, default_units.get(key, "")) for key, metric_index in metric_indexes.items()
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
        (row["x"], row["storage_modulus"]) for row in sample.rows if "x" in row and "storage_modulus" in row
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
        _token(sample): index for index, sample in enumerate(series_order) if isinstance(sample, str) and sample.strip()
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
    points = [(row["x"], row["storage_modulus"]) for row in sample.rows if "x" in row and "storage_modulus" in row]
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
        interval_count=max(sample.interval_count for sample in samples),
        selected_interval_index=representative.selected_interval_index,
        interval_selection_policy=representative.interval_selection_policy,
        source_x_unit=representative.source_x_unit,
        x_conversion=representative.x_conversion,
        metric_conversions=representative.metric_conversions,
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


def _sample_sweep_frame(
    sample: RheologySweepSample,
    *,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...] = _RHEOLOGY_SWEEP_METRICS,
) -> pd.DataFrame:
    headers = [sample.x_label, *[label for _key, label, _aliases, _unit in metrics]]
    units = [
        sample.x_unit,
        *[sample.metric_units.get(key, default_unit) for key, _label, _aliases, default_unit in metrics],
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
    source_replicates: list[RheologySweepSample] | None = None,
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
        for replicate_index, sample in enumerate(source_replicates or [], start=1):
            _sample_sweep_frame(sample, metrics=metrics).to_excel(
                writer,
                sheet_name=_sheet_name(f"Raw_{replicate_index}_{sample.sample}", used_sheet_names),
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
        _normalize_series(series, y_label="Normalized stress", y_unit="sigma/sigma0") for series in series_list
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
            preferred_result_tokens=("stress relaxation", "relaxation"),
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
                preferred_result_tokens=("stress relaxation", "relaxation"),
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
    finite_points = [
        (x_value, y_value)
        for x_value, y_value in series.points
        if y_value and math.isfinite(x_value) and math.isfinite(y_value)
    ]
    if not finite_points:
        raise ValueError("Cannot normalize a stress-relaxation curve without a non-zero finite y value.")
    baseline_time, baseline = max(finite_points, key=lambda point: abs(point[1]))
    normalized_points = tuple((x_value, y_value / baseline) for x_value, y_value in series.points)
    normalized_values = [value for _time, value in normalized_points if math.isfinite(value)]
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=y_label,
        y_unit=y_unit,
        points=normalized_points,
        diagnostics={
            **(series.diagnostics or {}),
            "normalization_definition": "divide by maximum absolute finite response",
            "normalization_baseline_value": baseline,
            "normalization_baseline_time": baseline_time,
            "normalized_minimum": min(normalized_values),
            "normalized_maximum": max(normalized_values),
            "normalized_final": normalized_values[-1],
        },
    )


def _reported_tensile_metrics(lines: list[str], *, stop_index: int | None) -> dict[str, Any]:
    upper_bound = stop_index if stop_index is not None else len(lines)
    candidates: list[tuple[list[str], list[str], list[str]]] = []
    for header_index in range(upper_bound):
        line = lines[header_index]
        if "," not in line:
            continue
        headers = [_clean_text(value) for value in next(csv.reader([line]))]
        evidence = " ".join(headers).casefold()
        if not any(token in evidence for token in ("拉伸应力", "拉伸应变", "模量", "tensile stress", "modulus")):
            continue
        units = (
            [_clean_text(value) for value in next(csv.reader([lines[header_index + 1]]))]
            if header_index + 1 < upper_bound
            else []
        )
        values: list[str] = []
        for row_index in range(header_index + 2, upper_bound):
            if not lines[row_index].strip():
                continue
            values = [_clean_text(value) for value in next(csv.reader([lines[row_index]]))]
            break
        if values:
            candidates.append((headers, units, values))

    reported: dict[str, Any] = {}
    metric_headers: dict[str, str] = {}
    for headers, _units, values in candidates:

        def value_for(
            candidate_headers: list[str],
            candidate_values: list[str],
            predicate: Any,
        ) -> tuple[float | None, str | None]:
            compact_headers = [re.sub(r"\s+", "", header.casefold()) for header in candidate_headers]
            for column, compact in enumerate(compact_headers):
                if not predicate(compact):
                    continue
                value = _float(candidate_values[column] if column < len(candidate_values) else None)
                if value is not None:
                    return value, candidate_headers[column]
            return None, None

        strength, strength_header = value_for(
            headers,
            values,
            lambda header: (
                ("拉伸应力" in header and "最大值" in header)
                or ("tensilestress" in header and any(token in header for token in ("maximum", "maxforce")))
            ),
        )
        if strength is None:
            strength, strength_header = value_for(
                headers,
                values,
                lambda header: (
                    ("拉伸应力" in header and "断裂" in header) or ("tensilestress" in header and "break" in header)
                ),
            )
        strain, strain_header = value_for(
            headers,
            values,
            lambda header: (
                ("拉伸应变" in header and "断裂" in header) or ("tensilestrain" in header and "break" in header)
            ),
        )
        modulus, modulus_header = value_for(
            headers,
            values,
            lambda header: (
                ("模量" in header and "最大值斜率" not in header)
                or ("modulus" in header and "maximumslope" not in header)
            ),
        )
        for metric_name, value, header in (
            ("strength_MPa", strength, strength_header),
            ("strain_at_break_percent", strain, strain_header),
            ("modulus_MPa", modulus, modulus_header),
        ):
            if value is not None and metric_name not in reported:
                reported[metric_name] = value
                if header:
                    metric_headers[metric_name] = header
    if metric_headers:
        reported["reported_metric_headers"] = metric_headers
    return reported


def _read_tensile_export_series(source: Path) -> CurveSeriesPayload:
    text = _decode_tensile_export_text(source)
    lines = text.splitlines()
    header_indexes = [
        index for index, line in enumerate(lines) if "拉伸应变" in line and "拉伸应力" in line and "," in line
    ]
    section_two_index = next(
        (index for index, line in enumerate(lines) if _token(line) == "结果表格2"),
        None,
    )
    reported = _reported_tensile_metrics(lines, stop_index=section_two_index)
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
            diagnostics={
                **reported,
                "source_file": str(source),
            },
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


def _canonical_impact_unit(value: object) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    compact = text.casefold().replace("²", "2").replace("^", "").replace("−", "-").replace("⁻", "-")
    compact = re.sub(r"[\s·*/()\[\]{}]", "", compact)
    if "kj" in compact and ("m2" in compact or "m-2" in compact):
        return "kJ/m2"
    return None


def _validated_impact_unit(values: list[object]) -> str:
    explicit = [_clean_text(value) for value in values if _clean_text(value)]
    unknown = [value for value in explicit if _canonical_impact_unit(value) is None]
    if unknown:
        raise _ImpactDataValidationError(
            "Impact strength units must resolve to kJ/m2; unsupported values: " + ", ".join(sorted(set(unknown)))
        )
    return "kJ/m2"


def _impact_unit_candidate_from_header(header: str) -> str | None:
    bracketed = re.search(r"\(([^)]+)\)|\[([^\]]+)\]", header)
    if bracketed:
        candidate = next((group for group in bracketed.groups() if group), "")
        return candidate.strip() or None
    compact = header.casefold()
    if any(token in compact for token in ("kj", "mpa", "gpa", "j/", "m²", "m2", "m^2")):
        return header
    return None


def _impact_payload(groups: dict[str, list[float]], *, unit: str) -> ImpactReplicatePayload:
    populated = [(sample, values) for sample, values in groups.items() if values]
    if not populated:
        raise ValueError("Impact table did not contain numeric impact values.")
    max_len = max(len(values) for _sample, values in populated)
    rows: list[tuple[object, ...]] = [
        tuple("Impact strength" for _sample, _values in populated),
        tuple(unit for _sample, _values in populated),
        tuple(sample for sample, _values in populated),
    ]
    for row_index in range(max_len):
        rows.append(tuple(values[row_index] if row_index < len(values) else "" for _sample, values in populated))
    return ImpactReplicatePayload(
        rows=tuple(rows),
        samples=tuple(sample for sample, _values in populated),
        replicate_counts=tuple(len(values) for _sample, values in populated),
        values=tuple(tuple(values) for _sample, values in populated),
        unit=unit,
    )


def _read_impact_canonical_tables(source: Path) -> ImpactReplicatePayload:
    """Read three-label-row impact tables, preserving every workbook sheet."""

    parsed: list[tuple[str, str, list[float]]] = []
    unit_candidates: list[object] = []
    for table_name, raw in _read_candidate_tables(source):
        raw = raw.dropna(axis=1, how="all")
        if raw.shape[0] < 4:
            continue
        sheet_label = table_name.split(":", 1)[-1] if ":" in table_name else ""
        for column in range(raw.shape[1]):
            metric_token = _token(raw.iat[0, column])
            if not (metric_token == "re" or "impact" in metric_token or "冲击" in metric_token):
                continue
            sample = _clean_text(raw.iat[2, column])
            if not sample:
                continue
            values = [
                value
                for row_index in range(3, raw.shape[0])
                if (value := _float(raw.iat[row_index, column])) is not None
            ]
            if not values:
                continue
            parsed.append((sheet_label, sample, values))
            unit_candidates.append(raw.iat[1, column])
    if not parsed:
        raise ValueError("Could not find a three-label-row impact table.")

    sample_counts = {
        sample: sum(1 for _sheet, candidate, _values in parsed if candidate == sample)
        for _sheet, sample, _values in parsed
    }
    groups: dict[str, list[float]] = {}
    for sheet_label, sample, values in parsed:
        label = f"{sample} ({sheet_label})" if sample_counts[sample] > 1 and sheet_label else sample
        groups.setdefault(label, []).extend(values)
    return _impact_payload(groups, unit=_validated_impact_unit(unit_candidates))


def _read_impact_block_table(source: Path) -> ImpactReplicatePayload:
    raw = read_raw_table(source).dropna(axis=1, how="all")
    if raw.shape[0] < 3:
        raise ValueError("Impact block table needs at least three rows.")
    re_columns: list[tuple[str, int]] = []
    unit_candidates: list[object] = []
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
        unit_candidate = _impact_unit_candidate_from_header(header)
        if unit_candidate:
            unit_candidates.append(unit_candidate)
        re_columns.append((sample, column))
    if not re_columns:
        raise ValueError("Could not find grouped impact strength columns.")
    groups: dict[str, list[float]] = {}
    for sample, column in re_columns:
        values = groups.setdefault(sample, [])
        for row_index in range(2, raw.shape[0]):
            value = _float(raw.iat[row_index, column])
            if value is not None:
                values.append(value)
    return _impact_payload(groups, unit=_validated_impact_unit(unit_candidates))


def _read_impact_compact_table(source: Path) -> ImpactReplicatePayload:
    raw = read_raw_table(source).dropna(how="all").dropna(axis=1, how="all")
    if raw.shape[0] < 2:
        raise ValueError("Impact compact table needs a header and at least one data row.")
    headers = [_token(value) for value in raw.iloc[0].tolist()]
    sample_col = next((index for index, token in enumerate(headers) if token in {"sample", "samplename"}), None)
    metric_col = next((index for index, token in enumerate(headers) if "impact" in token or "冲击" in token), None)
    if sample_col is None or metric_col is None:
        raise ValueError("Impact compact table needs sample and impact columns.")
    unit_col = metric_col + 1 if metric_col + 1 < raw.shape[1] else None
    groups: dict[str, list[float]] = {}
    units: list[object] = []
    for row_index in range(1, raw.shape[0]):
        sample = _clean_text(raw.iat[row_index, sample_col])
        value = _float(raw.iat[row_index, metric_col])
        if not sample or value is None:
            continue
        groups.setdefault(sample, []).append(value)
        if unit_col is not None:
            unit = _clean_text(raw.iat[row_index, unit_col])
            if unit:
                units.append(unit)
    return _impact_payload(groups, unit=_validated_impact_unit(units))


def _read_impact_source(source: Path) -> ImpactReplicatePayload:
    if source.is_dir():
        sources = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".csv"}
        ]
    else:
        sources = [source]
    if not sources:
        raise ValueError(f"No impact-strength tables found under {source}.")
    groups: dict[str, list[float]] = {}
    errors: list[str] = []
    for path in sources:
        try:
            try:
                payload = _read_impact_canonical_tables(path)
            except _ImpactDataValidationError:
                raise
            except ValueError:
                try:
                    payload = _read_impact_block_table(path)
                except _ImpactDataValidationError:
                    raise
                except ValueError:
                    payload = _read_impact_compact_table(path)
        except _ImpactDataValidationError:
            raise
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        for sample, values in zip(payload.samples, payload.values, strict=True):
            groups.setdefault(sample, []).extend(values)
    if not groups:
        raise ValueError("Could not parse impact-strength tables: " + "; ".join(errors))
    return _impact_payload(groups, unit="kJ/m2")


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


def _dma_modulus_unit(value: object) -> tuple[str, float] | None:
    text = _clean_text(value).casefold().replace(" ", "")
    for token, canonical, factor in (
        ("gpa", "GPa", 1.0e9),
        ("mpa", "MPa", 1.0e6),
        ("kpa", "kPa", 1.0e3),
        ("pa", "Pa", 1.0),
    ):
        if token in text:
            return canonical, factor
    return None


def _dma_temperature_sample_label(
    raw: pd.DataFrame,
    *,
    header_index: int,
    y_index: int,
    y_header: str,
    fallback: str,
) -> str:
    label = re.sub(r"storage\s*modulus", "", y_header, flags=re.IGNORECASE)
    label = re.sub(r"\([^)]*\)", "", label)
    label = re.sub(r"\b[GMk]?Pa\b", "", label, flags=re.IGNORECASE)
    label = _clean_text(label).strip(" _-:;,/")
    if label:
        return label
    for row_index in range(header_index + 1, min(raw.shape[0], header_index + 4)):
        value = _clean_text(raw.iat[row_index, y_index])
        if not value or _float(value) is not None or _dma_modulus_unit(value) is not None:
            continue
        return value
    return fallback


def _read_dma_temperature_series(source: Path) -> list[CurveSeriesPayload]:
    raw = read_raw_table(source).dropna(axis=1, how="all").dropna(how="all")
    best: tuple[int, list[tuple[int, int]]] | None = None
    for row_index in range(raw.shape[0]):
        headers = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        pairs = [
            (column_index, column_index + 1)
            for column_index in range(len(headers) - 1)
            if "temperature" in _token(headers[column_index]) and "storagemodulus" in _token(headers[column_index + 1])
        ]
        if pairs and (best is None or len(pairs) > len(best[1])):
            best = (row_index, pairs)
    if best is None:
        raise ValueError(f"Could not find repeated temperature/storage-modulus pairs in {source}.")

    header_index, pairs = best
    series_list: list[CurveSeriesPayload] = []
    for pair_index, (x_index, y_index) in enumerate(pairs, start=1):
        x_header = _clean_text(raw.iat[header_index, x_index])
        y_header = _clean_text(raw.iat[header_index, y_index])
        unit_match = _dma_modulus_unit(y_header)
        if unit_match is None:
            for row_index in range(header_index + 1, min(raw.shape[0], header_index + 4)):
                unit_match = _dma_modulus_unit(raw.iat[row_index, y_index])
                if unit_match is not None:
                    break
        source_unit, factor_to_pa = unit_match or ("Pa", 1.0)
        sample = _dma_temperature_sample_label(
            raw,
            header_index=header_index,
            y_index=y_index,
            y_header=y_header,
            fallback=f"{source.stem} {pair_index}" if len(pairs) > 1 else source.stem,
        )
        points: list[tuple[float, float]] = []
        for row_index in range(header_index + 1, raw.shape[0]):
            x_value = _float(raw.iat[row_index, x_index])
            y_value = _float(raw.iat[row_index, y_index])
            if x_value is None or y_value is None:
                continue
            points.append((x_value, y_value * factor_to_pa))
        if not points:
            continue
        series_list.append(
            CurveSeriesPayload(
                sample=sample,
                x_label="Temperature",
                x_unit="°C",
                y_label="Storage modulus, E′",
                y_unit="Pa",
                points=tuple(points),
                diagnostics={
                    "source_file": str(source),
                    "source_x_header": x_header,
                    "source_y_header": y_header,
                    "source_y_unit": source_unit,
                    "canonical_y_unit": "Pa",
                    "conversion_factor_to_Pa": factor_to_pa,
                    "source_point_count": len(points),
                },
            )
        )
    if not series_list:
        raise ValueError(f"No numeric DMA temperature curves found in {source}.")
    return series_list


def _read_dma_temperature_series_list(source: Path) -> list[CurveSeriesPayload]:
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for path in _sweep_source_files(source):
        try:
            series_list.extend(_read_dma_temperature_series(path))
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(f"No DMA temperature-sweep tables found under {source}. {detail}".strip())
    return series_list


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


def _clean_ftir_boundary_artifacts(
    points: tuple[tuple[float, float], ...] | list[tuple[float, float]],
) -> tuple[tuple[tuple[float, float], ...], dict[str, Any]]:
    """Remove only an isolated percent-transmittance acquisition sentinel.

    Zero absorbance can be scientifically valid, so the gate activates only
    when the local trace is unmistakably on a percent-transmittance scale.
    """

    cleaned = list(points)
    removed: list[int] = []

    def is_sentinel(boundary: int) -> bool:
        if len(cleaned) < 4:
            return False
        candidate = cleaned[boundary][1]
        neighbor_index = 1 if boundary == 0 else -2
        neighbor = cleaned[neighbor_index][1]
        window = cleaned[1:33] if boundary == 0 else cleaned[-33:-1]
        local_values = sorted(value for _x, value in window if math.isfinite(value))
        if not local_values:
            return False
        local_median = local_values[len(local_values) // 2]
        return candidate <= 5.0 and neighbor > 20.0 and local_median > 20.0 and neighbor - candidate > 20.0

    original_count = len(cleaned)
    if is_sentinel(0):
        cleaned.pop(0)
        removed.append(0)
    if is_sentinel(-1):
        cleaned.pop()
        removed.append(original_count - 1)
    diagnostics = {
        "source_point_count": original_count,
        "selected_point_count": len(cleaned),
        "boundary_sentinel_removed_source_indices": removed,
        "boundary_sentinel_rule": ("isolated <=5 %T endpoint next to a >20 %T trace with local median >20 %T"),
    }
    return tuple(cleaned), diagnostics


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
    cleaned_points, diagnostics = _clean_ftir_boundary_artifacts(best_points)
    if len(cleaned_points) < 4:
        raise ValueError(f"FTIR spectrum has too few points after boundary cleanup in {source}.")
    return CurveSeriesPayload(
        sample=_source_display_sample(source),
        x_label="Wavenumber",
        x_unit="cm^-1",
        y_label="Transmittance",
        y_unit="%",
        points=cleaned_points,
        diagnostics={"source_file": str(source), **diagnostics},
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
        cleaned_points, diagnostics = _clean_ftir_boundary_artifacts(series.points)
        return [
            CurveSeriesPayload(
                sample=_source_display_sample(source),
                x_label=series.x_label,
                x_unit=series.x_unit,
                y_label=series.y_label,
                y_unit=series.y_unit,
                points=cleaned_points,
                diagnostics={"source_file": str(source), **diagnostics},
            )
        ]
    if structured:
        cleaned: list[CurveSeriesPayload] = []
        for series in structured:
            cleaned_points, diagnostics = _clean_ftir_boundary_artifacts(series.points)
            cleaned.append(
                CurveSeriesPayload(
                    sample=series.sample,
                    x_label=series.x_label,
                    x_unit=series.x_unit,
                    y_label=series.y_label,
                    y_unit=series.y_unit,
                    points=cleaned_points,
                    diagnostics={"source_file": str(source), **diagnostics},
                )
            )
        return cleaned
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
        diagnostics=series.diagnostics,
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
    selected_peak_runs: list[tuple[int, int]] = []
    time_step = _median_positive_step(x_values)
    minimum_mixing_span_s = max(120.0, time_step * 30.0)
    for start, stop in reversed(low_runs):
        if stop - start + 1 < 3:
            continue
        if not any(high_flags[:start]):
            continue
        before_start = max(0, start - 30)
        if start <= 0 or max(smooth[before_start:start] or [0.0]) <= pre_drop_threshold:
            continue
        candidate_peak_runs = _contiguous_true_runs([index < start and flag for index, flag in enumerate(high_flags)])
        if not candidate_peak_runs:
            continue
        peak_start, peak_stop = candidate_peak_runs[-1]
        candidate_peak_index = max(range(peak_start, peak_stop + 1), key=lambda index: y_values[index])
        # A cleaning/start-up spike can occur after the real discharge.  It is
        # not a new mixing event unless the high-torque feed signal is followed
        # by a substantial working interval before the next low-torque run.
        if x_values[start] - x_values[candidate_peak_index] < minimum_mixing_span_s:
            continue
        discharge_run = (start, stop)
        selected_peak_runs = candidate_peak_runs
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
    peak_runs = selected_peak_runs or _contiguous_true_runs(
        [index < search_stop and flag for index, flag in enumerate(high_flags)]
    )
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
        "mixing_span_s": x_values[discharge_start] - x_values[feed_peak_index],
        "minimum_mixing_span_s": minimum_mixing_span_s,
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
        diagnostics={
            **(series.diagnostics or {}),
            "event_selection": _json_safe(selection),
            "source_point_count": len(series.points),
            "selected_point_count": len(selected),
        },
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
    if curation is not None:
        selection = _torque_selection_for_source(source=source, series=full_series, curation=curation)
    else:
        candidate = _auto_torque_event_selection(full_series)
        if candidate.get("needs_human_review"):
            selection = {
                "sample": full_series.sample,
                "start_s": full_series.points[0][0],
                "end_s": full_series.points[-1][0],
                "time_zero": "start_s",
                "source": "full_curve_unconfirmed_event",
                "confidence": candidate.get("confidence", 0.0),
                "needs_human_review": True,
                "reason": (
                    "Automatic final-event detection was not confident, so SciPlot preserved the full curve "
                    "instead of silently trimming it."
                ),
                "automatic_candidate": candidate,
            }
        else:
            selection = candidate
    return _apply_torque_selection(full_series, selection)


def _tensile_export_files(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        return sorted(input_path.rglob("*.csv"))
    return [input_path]


def _read_tensile_export_series_list(source: Path) -> list[CurveSeriesPayload]:
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    direct_export_group = source.name[: -len(".is_tens_Exports")].strip() if _is_tensile_export_dir(source) else ""
    for path in _tensile_export_files(source):
        try:
            series = _read_tensile_export_series(path)
            if direct_export_group and "__" not in series.sample:
                series = _with_series_sample(series, f"{direct_export_group}__{series.sample}")
            series_list.append(series)
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
                diagnostics=representative.diagnostics,
            )
        )
    return representatives


def _write_tensile_summary_table(series_list: list[CurveSeriesPayload], output: Path) -> Path:
    rows: list[dict[str, Any]] = []
    for series in series_list:
        group = _intake_group_name(series.sample) or series.sample
        replicate = series.sample.split("__", 1)[1] if "__" in series.sample else series.sample
        diagnostics = series.diagnostics or {}
        reported = {
            key: float(diagnostics[key])
            for key in ("strength_MPa", "strain_at_break_percent", "modulus_MPa")
            if diagnostics.get(key) is not None
        }
        metrics = tensile_curve_metric_values(
            series.points,
            x_unit=series.x_unit,
            reported=reported,
        )
        rows.append(
            {
                "sample": group,
                "replicate": replicate,
                **metrics,
                "source_file": diagnostics.get("source_file"),
                "reported_metric_headers": json.dumps(
                    diagnostics.get("reported_metric_headers") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output, index=False)
    return output


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


_SHARED_RHEOLOGY_SWEEP_CONFIG: dict[str, dict[str, Any]] = {
    "rheology_strain_sweep": {
        "x_aliases": ("shearstrain", "strain", "gamma", "γ"),
        "x_label": "Strain",
        "x_unit": "%",
        "metrics": _RHEOLOGY_AMPLITUDE_OUTPUT_METRICS,
        "comparison_sheet": "Strain_Comparison",
    },
    "rheology_stress_sweep": {
        "x_aliases": ("shearstress", "stress"),
        "x_label": "Stress",
        "x_unit": "Pa",
        "metrics": _RHEOLOGY_AMPLITUDE_OUTPUT_METRICS,
        "comparison_sheet": "Stress_Comparison",
    },
    "rheology_time_sweep": {
        "x_aliases": ("time", "elapsedtime"),
        "x_label": "Time",
        "x_unit": "s",
        "metrics": _RHEOLOGY_TIME_OUTPUT_METRICS,
        "comparison_sheet": "Time_Comparison",
    },
}


def _rheology_replicate_inventory(samples: list[RheologySweepSample]) -> list[dict[str, Any]]:
    grouped: dict[str, list[RheologySweepSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.sample, []).append(sample)
    return [
        {
            "sample": sample_label,
            "replicate_count": len(replicates),
            "source_files": [str(replicate.source) for replicate in replicates],
        }
        for sample_label, replicates in grouped.items()
    ]


def _rheology_unit_conversion_inventory(samples: list[RheologySweepSample]) -> list[dict[str, Any]]:
    return [
        {
            "sample": sample.sample,
            "source": str(sample.source),
            "x": sample.x_conversion,
            "metrics": sample.metric_conversions or {},
        }
        for sample in samples
    ]


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

    shared_sweep = _SHARED_RHEOLOGY_SWEEP_CONFIG.get(family)
    if shared_sweep is not None and source.is_dir():
        processed_source = processed_dir / f"{family}_comparison.xlsx"
        source_samples = _read_rheology_sweep_comparison_samples(
            source,
            x_aliases=shared_sweep["x_aliases"],
            x_label=shared_sweep["x_label"],
            default_x_unit=shared_sweep["x_unit"],
            metrics=shared_sweep["metrics"],
        )
        if not source_samples:
            raise ValueError(f"{family} folders need at least one parseable sample export.")
        samples = _coalesce_replicate_sweep_samples(source_samples, replicate_mode=replicate_mode)
        samples = _ordered_sweep_samples(samples, series_order=series_order)
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet=shared_sweep["comparison_sheet"],
            metrics=shared_sweep["metrics"],
            source_replicates=source_samples,
        )
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="aggregate_shared_rheology_sweep_replicates",
            parameters={
                "semantic_family": family,
                "replicate_mode": _normalized_replicate_mode(replicate_mode),
                "source_sample_count": len(source_samples),
                "output_sample_count": len(samples),
                "source_sample_files": [str(sample.source) for sample in source_samples],
                "output_sample_labels": [sample.sample for sample in samples],
                "replicate_inventory": _rheology_replicate_inventory(source_samples),
                "source_replicates_preserved_in_workbook": True,
                "unit_conversions": _rheology_unit_conversion_inventory(source_samples),
                "mean_definition": "arithmetic mean at exactly matching x values",
                "representative_definition": "longest trace then closest terminal storage modulus to group median",
                "series_order": list(series_order) if isinstance(series_order, list | tuple) else [],
            },
        )

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
            raise ValueError("Rheology frequency folders need at least one parseable sample export.")
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
        interval_selections = [
            {
                "sample": sample.sample,
                "source": str(sample.source),
                "detected_interval_count": sample.interval_count,
                "selected_interval_index": sample.selected_interval_index,
                "selection_policy": sample.interval_selection_policy,
                "selected_point_count": len(sample.rows),
                "x_direction": (
                    "increasing"
                    if len(sample.rows) < 2 or sample.rows[-1]["x"] >= sample.rows[0]["x"]
                    else "decreasing"
                ),
            }
            for sample in samples
        ]
        samples = _coalesce_replicate_sweep_samples(samples, replicate_mode=replicate_mode)
        samples = _ordered_sweep_samples(samples, series_order=series_order)
        if not samples:
            raise ValueError("Rheology temperature folders need at least one parseable sample export.")
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
                "interval_selection_policy": "last_numeric_interval",
                "interval_selections": interval_selections,
            },
        )

    if family == "dma_temperature_sweep":
        processed_source = processed_dir / "dma_temperature_comparison.csv"
        series_list = _read_dma_temperature_series_list(source)
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_and_convert_dma_temperature_curves",
            parameters={
                "y_metric": "storage_modulus",
                "canonical_y_unit": "Pa",
                "source_sample_count": len(series_list),
                "series_order": [series.sample for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})} for series in series_list
                ],
                "unit_conversion_recorded": True,
            },
        )

    if family == "rheology_creep":
        processed_source = processed_dir / f"{source.stem}_creep_curve.csv"
        series_list = _read_rheology_interval_series_list(
            source,
            y_candidates=("creepcompliance", "compliance", "蠕变柔量"),
            y_label="Creep compliance",
            y_unit="1/Pa",
            preferred_result_tokens=("creep",),
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
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})} for series in series_list
                ],
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
                "source_normalizations": [
                    {"sample": series.sample, **(series.diagnostics or {})} for series in series_list
                ],
            },
        )

    if family in {"saxs_profile", "gpc_sec_chromatogram"}:
        if family == "saxs_profile":
            processed_source = processed_dir / f"{source.stem}_saxs_profile.csv"
            series_list = _scan_curve_series_source(
                source,
                x_aliases=("q", "q_nm-1"),
                y_aliases=("intensity",),
                x_label="q",
                y_label="Intensity",
                default_x_unit="nm^-1",
                default_y_unit="a.u.",
                sample_prefix=source.stem,
            )
            operation = "extract_saxs_q_intensity_profile"
            selected_columns = {"x": "q", "y": "intensity"}
            sample_label = _constant_sample_label(source)
            if sample_label and len(series_list) == 1:
                series = series_list[0]
                series_list = [
                    CurveSeriesPayload(
                        sample=sample_label,
                        x_label=series.x_label,
                        x_unit=series.x_unit,
                        y_label=series.y_label,
                        y_unit=series.y_unit,
                        points=series.points,
                        diagnostics=series.diagnostics,
                    )
                ]
        else:
            processed_source = processed_dir / f"{source.stem}_gpc_chromatogram.csv"
            series_list = _read_gpc_series_list(source)
            operation = "extract_gpc_detector_chromatograms"
            selected_columns = {"x": "elution time", "y": "detector response"}
        if not series_list:
            raise ValueError(f"No canonical {family} curve found in {source}.")
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation=operation,
            parameters={
                "series_order": [series.sample for series in series_list],
                "selected_axis_columns": selected_columns,
                "source_point_counts": [len(series.points) for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})} for series in series_list
                ],
            },
        )

    if family == "swelling_curve":
        processed_source = processed_dir / f"{source.stem}_swelling_curve.csv"
        series_list = _order_curve_series(_read_swelling_series_list(source), series_order)
        if not series_list:
            raise ValueError(f"No sample/time/swelling-ratio curves found in {source}.")
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_swelling_ratio_by_sample",
            parameters={
                "series_order": [series.sample for series in series_list],
                "selected_axis_columns": {"x": "time", "y": "swelling ratio"},
                "excluded_same_table_metrics": ["gel fraction"],
                "source_point_counts": [len(series.points) for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})} for series in series_list
                ],
            },
        )

    if family == "tga_curve":
        processed_source = processed_dir / f"{source.stem}_tga_curve.csv"
        series_list = _scan_curve_series_source(
            source,
            x_aliases=("temperature", "temp"),
            y_aliases=("weight", "mass"),
            x_label="Temperature",
            y_label="Mass",
            default_x_unit="C",
            default_y_unit="%",
            sample_prefix=source.stem,
        )
        if not series_list:
            raise ValueError(f"No temperature/mass TGA curve found in {source}.")
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_tga_temperature_mass_curve",
            parameters={
                "series_order": [series.sample for series in series_list],
                "selected_axis_columns": {"x": "Temperature", "y": "Mass"},
                "source_point_counts": [len(series.points) for series in series_list],
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
            parameters={
                "series_order": [series.sample for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})} for series in series_list
                ],
            },
        )

    if family == "tensile_curve" and (source.is_dir() or source.suffix.lower() == ".csv"):
        processed_source = processed_dir / f"{source.stem}_tensile_curves.csv"
        series_list = _read_tensile_export_series_list(source)
        input_series_labels = [series.sample for series in series_list]
        summary_source = processed_source.with_name(f"{processed_source.stem}_summary.csv")
        _write_tensile_summary_table(series_list, summary_source)
        requested_replicate_mode = _normalized_replicate_mode(replicate_mode)
        representative_applied = False
        grouped_input = _has_intake_grouped_series(series_list)
        additional_outputs: tuple[Path, ...] = (summary_source,)
        if grouped_input:
            all_source = processed_source.with_name(f"{processed_source.stem}_all.csv")
            _write_curve_table(series_list, all_source)
            additional_outputs = (all_source, summary_source)
            if requested_replicate_mode != "individual":
                series_list = _representative_tensile_series(series_list)
                representative_applied = True
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_tensile_curves",
            parameters={
                "input_series_labels": input_series_labels,
                "output_series_labels": [series.sample for series in series_list],
                "requested_replicate_mode": requested_replicate_mode,
                "applied_curve_replicate_mode": ("representative" if representative_applied else "individual"),
                "representative_selection_applied": representative_applied,
                "representative_definition": (
                    "closest to group median tensile strength, then break strain, with deterministic sample order"
                    if representative_applied
                    else None
                ),
                "all_series_preserved_in_supporting_output": grouped_input,
                "summary_metric_source": str(summary_source),
                "summary_replicate_count": len(input_series_labels),
                "summary_metric_definitions": {
                    "strength_MPa": "instrument-reported maximum tensile stress, else curve maximum",
                    "strain_at_break_percent": "instrument-reported break strain, else curve terminal strain",
                    "modulus_MPa": (
                        "instrument-reported 0.05%-0.25% program-segment modulus, else curve fit with "
                        "percent strain converted to a fraction"
                    ),
                    "toughness_MJ_m3": "stress integral over engineering-strain fraction up to break",
                },
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
        event_selections = [
            {
                "sample": series.sample,
                **((series.diagnostics or {}).get("event_selection") or {}),
                "source_point_count": (series.diagnostics or {}).get("source_point_count"),
                "selected_point_count": (series.diagnostics or {}).get("selected_point_count"),
            }
            for series in series_list
        ]
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_torque_curves",
            parameters={
                "curation_path": str(Path(curation_path).expanduser()) if curation_path is not None else None,
                "curation_applied": curation is not None,
                "series_order": [series.sample for series in series_list],
                "automatic_event_selection_applied": curation is None,
                "event_selection_policy": (
                    "explicit_curation" if curation is not None else "last_confident_feed_peak_to_discharge_drop"
                ),
                "event_selections": event_selections,
                "needs_human_review": any(bool(item.get("needs_human_review")) for item in event_selections),
                "unconfirmed_events_preserve_full_curve": True,
            },
        )

    if family == "impact_metric" and (source.is_dir() or source.suffix.lower() in {".xlsx", ".xls", ".csv"}):
        impact = _read_impact_source(source)
        processed_source = processed_dir / f"{source.stem}_impact_replicates.csv"
        pd.DataFrame(impact.rows).to_csv(processed_source, header=False, index=False)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_impact_replicates",
            parameters={
                "group_count": len(impact.samples),
                "sample_order": list(impact.samples),
                "replicate_counts": dict(zip(impact.samples, impact.replicate_counts, strict=True)),
                "replicate_count_total": impact.total_replicates,
                "raw_values_preserved": True,
                "canonical_unit": impact.unit,
                "summary_statistic_default": "median_iqr",
                "minimum_box_replicates": 2,
            },
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
            "A required component or file is missing. Use assisted repair to check dependencies and file paths."
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
