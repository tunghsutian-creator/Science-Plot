from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass, fields, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from src.data_loader import (
    CurveSeries,
    HeatmapTable,
    ReplicateGroup,
    load_curve_table,
    load_curve_table_from_frame,
    load_heatmap_table_from_frame,
    load_replicate_table_from_frame,
)
from src.rendering.cache import (
    load_curve_table_cached,
    load_frequency_sweep_metrics_cached,
    load_heatmap_table_cached,
    load_replicate_table_cached,
    load_stress_relaxation_metric_cached,
    load_temperature_sweep_metrics_cached,
    read_raw_table_cached,
    read_raw_table_for_options,
)
from src.rendering.common import looks_like_tensile_curve, summarize_replicate_distribution
from src.rendering.raw_plot_intent import detect_raw_plot_intent
from src.rheology_loader import RheologySeries
from src.text_normalization import canonicalize_token, normalize_label
from src.wide_nmr import wide_nmr_sidecar_path

DataShape = Literal[
    "curve_like",
    "replicate_table",
    "matrix",
    "distribution",
    "grouped",
    "scalar_field",
    "polar",
    "table",
]
RoleKey = str


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    header_preview: tuple[str | None, ...]
    inferred_type: str
    non_empty_count: int
    missing_count: int
    min_value: float | int | None = None
    max_value: float | int | None = None


@dataclass(frozen=True)
class CandidateRoles:
    x: tuple[str, ...] = ()
    y: tuple[str, ...] = ()
    z: tuple[str, ...] = ()
    group: tuple[str, ...] = ()
    sample: tuple[str, ...] = ()
    value: tuple[str, ...] = ()
    metric: tuple[str, ...] = ()
    label: tuple[str, ...] = ()
    series: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedDataset:
    dataset_id: str
    source_path: Path | None
    sheet: str | int | None
    raw_rows: int
    raw_cols: int
    column_profiles: tuple[ColumnProfile, ...]
    candidate_roles: CandidateRoles
    data_shapes: tuple[DataShape, ...]
    semantic_signals: tuple[str, ...]
    quality_flags: tuple[str, ...]
    model: str


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _clean_cell(value: object) -> object:
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        with suppress(Exception):
            value = value.item()
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    return value


def _string_or_none(value: object) -> str | None:
    cleaned = _clean_text(value)
    return cleaned or None


def _numeric_or_none(value: object) -> float | int | None:
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        with suppress(Exception):
            value = value.item()
    if isinstance(value, float):
        if pd.isna(value):
            return None
        return round(value, 6)
    if isinstance(value, int):
        return value
    if pd.isna(value):
        return None
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        return None
    return int(numeric) if numeric.is_integer() else round(numeric, 6)


def _summarize_raw_columns(raw: pd.DataFrame, *, limit: int = 24) -> list[ColumnProfile]:
    summaries: list[ColumnProfile] = []
    max_columns = min(raw.shape[1], limit)
    for index in range(max_columns):
        series = raw.iloc[:, index]
        numeric = pd.to_numeric(series, errors="coerce")
        non_empty = sum(_string_or_none(value) is not None for value in series.tolist())
        missing = len(series) - non_empty
        numeric_values = numeric.dropna()
        if numeric_values.empty:
            inferred_type = "text"
            min_value = None
            max_value = None
        elif numeric_values.shape[0] == non_empty:
            inferred_type = "numeric"
            min_value = _numeric_or_none(numeric_values.min())
            max_value = _numeric_or_none(numeric_values.max())
        else:
            inferred_type = "mixed"
            min_value = _numeric_or_none(numeric_values.min())
            max_value = _numeric_or_none(numeric_values.max())
        summaries.append(
            ColumnProfile(
                name=_column_name(raw, index),
                header_preview=tuple(
                    _string_or_none(raw.iloc[row_index, index])
                    for row_index in range(min(3, raw.shape[0]))
                ),
                inferred_type=inferred_type,
                non_empty_count=non_empty,
                missing_count=missing,
                min_value=min_value,
                max_value=max_value,
            )
        )
    return summaries


def _column_name(raw: pd.DataFrame, index: int) -> str:
    preview = [
        _string_or_none(raw.iloc[row_index, index])
        for row_index in range(min(3, raw.shape[0]))
    ]
    labels = [value for value in preview if value]
    return " | ".join(labels) if labels else f"Column {index + 1}"


def dataframe_sample_rows(frame: pd.DataFrame, *, limit: int = 8) -> list[list[object]]:
    rows: list[list[object]] = []
    for row in frame.head(limit).itertuples(index=False, name=None):
        rows.append([_clean_cell(value) for value in row])
    return rows


def _dataset_id(*, source_path: Path | None, sheet: str | int | None, model: str, raw_rows: int, raw_cols: int) -> str:
    payload = {
        "path": str(source_path.resolve()) if source_path is not None else None,
        "sheet": sheet,
        "model": model,
        "rows": raw_rows,
        "cols": raw_cols,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"dataset_{digest[:16]}"


def point_line_bundle_signals(bundle: str) -> tuple[str, ...]:
    if bundle == "frequency_sweep":
        return (
            "Detected a 5-column rheology export bundle.",
            "The first x-axis field is Angular Frequency / ω.",
            "Each bundle includes Storage/Loss Modulus, Loss Factor, and Complex Viscosity.",
        )
    if bundle == "temperature_sweep":
        return (
            "Detected a 5-column rheology export bundle.",
            "The first x-axis field is Temperature.",
            "Each bundle includes Storage/Loss Modulus, Loss Factor, and Complex Viscosity.",
        )
    if bundle == "stress_relaxation":
        return (
            "Detected a 4-column stress relaxation export bundle.",
            "The first x-axis field is Time.",
            "The bundle includes the σ/σ₀ metric.",
        )
    return ()


def frequency_metric_sheet_signals(series_list: list[CurveSeries] | None = None) -> tuple[str, ...]:
    metric_labels: tuple[str, ...] = ()
    if series_list:
        metric_labels = tuple(
            sorted({series.y_label for series in series_list if _is_frequency_metric_y_label(series.y_label)})
        )
    metric_summary = ", ".join(metric_labels) if metric_labels else "rheology metric columns"
    return (
        "Detected a Data Studio frequency-sweep metric sheet.",
        "The x-axis field is Angular Frequency / ω.",
        f"The y-axis compares {metric_summary} across samples.",
    )


def looks_like_frequency_metric_sheet(series_list: list[CurveSeries]) -> bool:
    if not series_list:
        return False
    x_labels = {canonicalize_token(series.x_label) for series in series_list}
    y_labels = {canonicalize_token(series.y_label) for series in series_list}
    samples = {series.sample for series in series_list}
    has_frequency_x = bool(x_labels & {"angular frequency", "frequency", "ω"})
    has_rheology_y = any(_is_frequency_metric_y_label(label) for label in y_labels)
    return has_frequency_x and has_rheology_y and len(samples) >= 1


def _is_frequency_metric_y_label(label: str) -> bool:
    token = canonicalize_token(label)
    return token in {
        "storage modulus",
        "loss modulus",
        "loss factor",
        "complex viscosity",
        "complex modulus",
        "complex shear modulus",
        "g'",
        'g"',
        "g*",
        "|g*|",
        "tanδ",
        "tand",
        "tan delta",
        "|η.|",
        "eta",
        "eta*",
    }


def detect_point_line_bundle(input_path: Path, sheet: str | int) -> str | None:
    if input_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return None
    try:
        raw = read_raw_table_cached(input_path, sheet).dropna(axis=1, how="all")
    except Exception:
        return None

    if raw.shape[0] < 3 or raw.shape[1] == 0:
        return None

    labels = [canonicalize_token(_clean_text(value)) for value in raw.iloc[0].tolist()]
    normalized_labels = [normalize_label(_clean_text(value)) for value in raw.iloc[0].tolist()]
    first_label = labels[0]

    metric_labels = set(labels)
    if (
        raw.shape[1] % 5 == 0
        and {"storage modulus", "loss modulus", "loss factor"}.issubset(metric_labels)
        and ({"complex viscosity", "complex modulus"} & metric_labels)
    ):
        if first_label == "temperature":
            return "temperature_sweep"
        if first_label in {"angular frequency", "frequency", "ω"}:
            return "frequency_sweep"

    if raw.shape[1] % 4 == 0 and first_label == "time":
        if r"$\sigma/\sigma_0$" in normalized_labels:
            return "stress_relaxation"

    return None


def _series_map_for_bundle(bundle: str, input_path: Path, sheet: str | int) -> dict[str, list[RheologySeries]]:
    if bundle == "frequency_sweep":
        return load_frequency_sweep_metrics_cached(input_path, sheet)
    if bundle == "temperature_sweep":
        return load_temperature_sweep_metrics_cached(input_path, sheet)
    if bundle == "stress_relaxation":
        return {
            "sigma_over_sigma0": load_stress_relaxation_metric_cached(
                input_path,
                "σ/σ₀",
                sheet,
            )
        }
    raise ValueError(f"Unsupported bundle type: {bundle}")


def looks_like_nmr_curve(series_list: list[CurveSeries]) -> bool:
    first = series_list[0]
    x_label = canonicalize_token(first.x_label)
    x_unit = _clean_text(first.x_unit).lower()
    return x_label == "chemical shift" or "ppm" in x_unit


def looks_like_ftir_curve(series_list: list[CurveSeries]) -> bool:
    first = series_list[0]
    x_label = canonicalize_token(first.x_label)
    x_unit = _clean_text(first.x_unit).lower()
    return x_label == "wavenumber" or ("cm" in x_unit and ("-1" in x_unit or "^{-1}" in x_unit))


def looks_like_xrd_curve(series_list: list[CurveSeries]) -> bool:
    first = series_list[0]
    x_label = canonicalize_token(first.x_label)
    y_label = canonicalize_token(first.y_label)
    y_unit = _clean_text(first.y_unit).lower()
    return x_label in {"2theta", "2θ"} or ("count" in y_unit) or (x_label == "2 theta" and y_label == "intensity")


def looks_like_dsc_curve(series_list: list[CurveSeries]) -> bool:
    first = series_list[0]
    y_label = canonicalize_token(first.y_label)
    return y_label == "heat flow"


def detect_input_model(input_path: Path, sheet: str | int = 0) -> str:
    bundle = detect_point_line_bundle(input_path, sheet)
    if bundle is not None:
        return bundle

    with suppress(Exception):
        series_list = load_curve_table(input_path, sheet_name=sheet)
        if looks_like_frequency_metric_sheet(series_list):
            return "frequency_metric_sheet"
        if wide_nmr_sidecar_path(input_path).exists():
            return "curve_table"
        if looks_like_nmr_curve(series_list):
            return "curve_table"
        if looks_like_ftir_curve(series_list):
            return "curve_table"
        if looks_like_dsc_curve(series_list):
            return "curve_table"
        if looks_like_xrd_curve(series_list):
            return "curve_table"
        if looks_like_tensile_curve(series_list):
            return "tensile_curve"
        return "curve_table"

    with suppress(Exception):
        load_heatmap_table_cached(input_path, sheet)
        return "heatmap_table"

    with suppress(Exception):
        raw = read_raw_table_cached(input_path, sheet).dropna(how="all").dropna(axis=1, how="all")
        intent = detect_raw_plot_intent(raw, input_path)
        if intent is not None:
            return intent.model

    with suppress(Exception):
        load_replicate_table_cached(input_path, sheet)
        return "replicate_table"

    with suppress(Exception):
        raw = read_raw_table_cached(input_path, sheet).dropna(how="all").dropna(axis=1, how="all")
        if _looks_like_small_table_figure(raw):
            return "table_summary"

    raise ValueError(
        "Could not recognize this file. Reformat it as a curve_table, replicate_table, "
        "heatmap xyz_long_table, small table figure, or one of the supported rheology export tables."
    )


def _detect_input_model_from_raw(input_path: Path, raw: pd.DataFrame) -> str:
    headers = tuple(_string_or_none(item) or "" for item in raw.iloc[0].tolist()) if not raw.empty else ()
    cleaned_headers = {canonicalize_token(item) for item in headers}
    if {"theta", "radius"}.issubset(cleaned_headers) or {"angle", "radius"}.issubset(cleaned_headers):
        return "curve_table"
    with suppress(Exception):
        series_list = load_curve_table_from_frame(raw)
        if looks_like_frequency_metric_sheet(series_list):
            return "frequency_metric_sheet"
        if looks_like_tensile_curve(series_list):
            return "tensile_curve"
        return "curve_table"
    with suppress(Exception):
        load_heatmap_table_from_frame(raw)
        return "heatmap_table"
    with suppress(Exception):
        intent = detect_raw_plot_intent(raw, input_path)
        if intent is not None:
            return intent.model
    with suppress(Exception):
        load_replicate_table_from_frame(raw)
        return "replicate_table"
    with suppress(Exception):
        compact = raw.dropna(how="all").dropna(axis=1, how="all")
        if _looks_like_small_table_figure(compact):
            return "table_summary"
    raise ValueError(
        f"Could not recognize transformed data from `{input_path.name}`. "
        "Adjust transforms so the result is a curve, replicate, scalar field, or compact table."
    )


def _candidate_roles_for_simple_curve_raw(raw: pd.DataFrame) -> CandidateRoles:
    headers = tuple(_string_or_none(item) or "" for item in raw.iloc[0].tolist()) if not raw.empty else ()
    polar_x = [value for value in headers if canonicalize_token(value) in {"theta", "angle", "azimuth"}]
    polar_y = [value for value in headers if canonicalize_token(value) in {"radius", "radial distance", "r"}]
    x_candidates = polar_x or [value for value in headers if canonicalize_token(value) == "x"]
    y_candidates = polar_y or [value for value in headers if canonicalize_token(value) == "y"]
    return CandidateRoles(
        x=tuple(x_candidates[:1]),
        y=tuple(y_candidates[:1]),
        series=tuple(value for value in headers if value),
    )


def _data_shapes_for_model(model: str) -> tuple[DataShape, ...]:
    if model in {
        "curve_table",
        "tensile_curve",
        "frequency_sweep",
        "frequency_metric_sheet",
        "temperature_sweep",
        "stress_relaxation",
    }:
        return ("curve_like",)
    if model == "replicate_table":
        return ("replicate_table", "distribution")
    if model == "heatmap_table":
        return ("matrix", "scalar_field")
    if model == "table_summary":
        return ("table",)
    return ()


def _looks_like_small_table_figure(raw: pd.DataFrame) -> bool:
    if raw.empty or raw.shape[0] > 12 or raw.shape[1] > 8:
        return False
    mapped = raw.map(_string_or_none) if hasattr(raw, "map") else raw.applymap(_string_or_none)
    non_empty_count = sum(value is not None for value in mapped.to_numpy().ravel())
    if non_empty_count < 4:
        return False
    numeric_count = 0
    for value in mapped.to_numpy().ravel():
        if value is None:
            continue
        if _numeric_or_none(value) is not None:
            numeric_count += 1
    return numeric_count > 0 and numeric_count < non_empty_count


def _quality_flags(raw: pd.DataFrame, *, working_raw: pd.DataFrame) -> tuple[str, ...]:
    flags: list[str] = []
    if working_raw.shape[1] != raw.shape[1]:
        flags.append("empty_columns_dropped")
    if any(profile.inferred_type == "mixed" for profile in _summarize_raw_columns(working_raw, limit=8)):
        flags.append("type_ambiguity")
    return tuple(flags)


def _candidate_roles_for_curve(series_list: list[CurveSeries]) -> CandidateRoles:
    first = series_list[0]
    return CandidateRoles(
        x=(first.x_label,),
        y=(first.y_label,),
        sample=tuple(series.sample for series in series_list),
        label=tuple(
            value
            for value in (first.x_label, first.y_label, first.x_unit, first.y_unit)
            if value
        ),
        series=tuple(series.sample for series in series_list),
    )


def _candidate_roles_for_replicates(groups: list[ReplicateGroup]) -> CandidateRoles:
    if not groups:
        return CandidateRoles()
    first = groups[0]
    return CandidateRoles(
        group=tuple(group.group for group in groups),
        value=(first.value_label,),
        label=(first.value_label,),
        series=tuple(group.group for group in groups),
    )


def _candidate_roles_for_heatmap(table: HeatmapTable) -> CandidateRoles:
    return CandidateRoles(
        x=(table.x_label,),
        y=(table.y_label,),
        z=(table.z_label,),
        label=tuple(
            value
            for value in (table.x_label, table.y_label, table.z_label, table.x_unit, table.y_unit, table.z_unit)
            if value
        ),
    )


def _candidate_roles_for_rheology(series_map: dict[str, list[RheologySeries]]) -> CandidateRoles:
    x_labels: set[str] = set()
    y_labels: set[str] = set()
    sample_names: list[str] = []
    metric_names = list(series_map.keys())
    for series_list in series_map.values():
        for series in series_list:
            x_labels.add(series.x_label)
            y_labels.add(series.y_label)
            sample_names.append(series.sample)
    return CandidateRoles(
        x=tuple(sorted(x_labels)),
        y=tuple(sorted(y_labels)),
        metric=tuple(metric_names),
        sample=tuple(sample_names),
        series=tuple(sample_names),
    )


def _normalized_dataset_cache_key(
    input_path: Path,
    sheet: str | int,
    model: str | None,
) -> tuple[str, int, str | int, str | None]:
    return (
        str(input_path.resolve()),
        input_path.stat().st_mtime_ns,
        sheet,
        model,
    )


@lru_cache(maxsize=64)
def _build_normalized_dataset_cached(
    resolved_path: str,
    _mtime_ns: int,
    sheet: str | int,
    model: str | None,
) -> NormalizedDataset:
    input_path = Path(resolved_path)
    raw = read_raw_table_cached(input_path, sheet)
    working_raw = raw.dropna(axis=1, how="all")
    raw_intent = detect_raw_plot_intent(working_raw, input_path)
    resolved_model = model or detect_input_model(input_path, sheet)
    if raw_intent is not None and raw_intent.model != resolved_model:
        raw_intent = None
    extra_quality_flags: list[str] = []
    if resolved_model in {"frequency_sweep", "temperature_sweep", "stress_relaxation"}:
        series_map = _series_map_for_bundle(resolved_model, input_path, sheet)
        candidate_roles = _candidate_roles_for_rheology(series_map)
        semantic_signals = point_line_bundle_signals(resolved_model)
    elif resolved_model == "frequency_metric_sheet":
        series_list = load_curve_table_cached(input_path, sheet)
        candidate_roles = _candidate_roles_for_curve(series_list)
        semantic_signals = (
            raw_intent.semantic_signals if raw_intent is not None else frequency_metric_sheet_signals(series_list)
        )
    elif resolved_model == "replicate_table":
        groups = load_replicate_table_cached(input_path, sheet)
        replicate_summary = summarize_replicate_distribution(groups)
        candidate_roles = _candidate_roles_for_replicates(groups)
        semantic_signals = raw_intent.semantic_signals if raw_intent is not None else (
            "Detected a statistical replicate table.",
            "Row 2 contains the group names and row 3 contains the units.",
            "Row 4 onward contains replicate measurements.",
        )
        if replicate_summary.total_points < 12 or replicate_summary.min_group_points < 4:
            extra_quality_flags.append("replicate_sparse_replicates")
        if replicate_summary.min_group_points < 2:
            extra_quality_flags.append("replicate_singleton_groups")
        if replicate_summary.total_points >= 8 and replicate_summary.pooled_unique_ratio <= 0.35:
            extra_quality_flags.append("replicate_highly_discrete")
    elif resolved_model == "heatmap_table":
        table = load_heatmap_table_cached(input_path, sheet)
        candidate_roles = _candidate_roles_for_heatmap(table)
        semantic_signals = (
            "Detected a scalar-field table.",
            "The data contains X, Y, and Z roles that can be rendered as a matrix or contour field.",
            "This input can be converted directly into heatmap or contour-style figures.",
        )
    elif resolved_model == "table_summary":
        headers = tuple(
            value
            for value in (_string_or_none(item) for item in raw.iloc[0].tolist())
            if value is not None
        )
        candidate_roles = CandidateRoles(
            label=headers,
            metric=raw_intent.metric_columns if raw_intent is not None else (),
        )
        semantic_signals = raw_intent.semantic_signals if raw_intent is not None else (
            "Detected a small table figure input.",
            "The table is compact enough to render as a figure output.",
            "This path is for presentation tables, not full workbook export.",
        )
    else:
        series_list = load_curve_table_cached(input_path, sheet)
        candidate_roles = _candidate_roles_for_curve(series_list)
        semantic_signals = raw_intent.semantic_signals if raw_intent is not None else (
            "Detected a standard paired curve table.",
            "The labels and units do not strongly match a spectrum or rheology export bundle.",
            "The default path is a standard curve plot.",
        )
        if raw_intent is None and looks_like_tensile_curve(series_list):
            semantic_signals = (
                "The x-axis label or unit matches strain / elongation / %.",
                "The y-axis label or unit matches stress / MPa.",
                "Tensile curves always stay on linear x/y axes by default.",
            )

    column_profiles = _summarize_raw_columns(working_raw)
    quality_flags = tuple(dict.fromkeys(_quality_flags(raw, working_raw=working_raw) + tuple(extra_quality_flags)))
    data_shapes = _data_shapes_for_model("curve_table" if resolved_model == "curve_table" else resolved_model)

    return NormalizedDataset(
        dataset_id=_dataset_id(
            source_path=input_path,
            sheet=sheet,
            model=resolved_model,
            raw_rows=int(raw.shape[0]),
            raw_cols=int(raw.shape[1]),
        ),
        source_path=input_path,
        sheet=sheet,
        raw_rows=int(raw.shape[0]),
        raw_cols=int(raw.shape[1]),
        column_profiles=tuple(column_profiles),
        candidate_roles=candidate_roles,
        data_shapes=data_shapes,
        semantic_signals=semantic_signals,
        quality_flags=quality_flags,
        model=resolved_model,
    )


def _build_normalized_dataset_from_raw(
    input_path: Path,
    sheet: str | int,
    raw: pd.DataFrame,
    *,
    model: str | None = None,
) -> NormalizedDataset:
    working_raw = raw.dropna(axis=1, how="all")
    raw_intent = detect_raw_plot_intent(working_raw, input_path)
    resolved_model = model or _detect_input_model_from_raw(input_path, working_raw)
    if raw_intent is not None and raw_intent.model != resolved_model:
        raw_intent = None
    extra_quality_flags: list[str] = []
    if resolved_model == "replicate_table":
        groups = load_replicate_table_from_frame(working_raw)
        replicate_summary = summarize_replicate_distribution(groups)
        candidate_roles = _candidate_roles_for_replicates(groups)
        semantic_signals = (
            "Detected a statistical replicate table.",
            "Rows contain grouped replicate measurements.",
            "The transformed input can be rendered as a distribution figure.",
        )
        if replicate_summary.total_points < 12 or replicate_summary.min_group_points < 4:
            extra_quality_flags.append("replicate_sparse_replicates")
        if replicate_summary.min_group_points < 2:
            extra_quality_flags.append("replicate_singleton_groups")
        if replicate_summary.total_points >= 8 and replicate_summary.pooled_unique_ratio <= 0.35:
            extra_quality_flags.append("replicate_highly_discrete")
    elif resolved_model == "heatmap_table":
        table = load_heatmap_table_from_frame(working_raw)
        candidate_roles = _candidate_roles_for_heatmap(table)
        semantic_signals = (
            "Detected a scalar-field table.",
            "The transformed data contains X, Y, and Z roles.",
            "This input can be rendered as heatmap or contour-style figures.",
        )
    elif resolved_model == "table_summary":
        headers = tuple(
            value
            for value in (_string_or_none(item) for item in raw.iloc[0].tolist())
            if value is not None
        )
        candidate_roles = CandidateRoles(
            label=headers,
            metric=raw_intent.metric_columns if raw_intent is not None else (),
        )
        semantic_signals = raw_intent.semantic_signals if raw_intent is not None else (
            "Detected a small table figure input.",
            "The transformed table is compact enough to render as a figure output.",
            "This path is for presentation tables, not full workbook export.",
        )
    else:
        try:
            series_list = load_curve_table_from_frame(working_raw)
            candidate_roles = _candidate_roles_for_curve(series_list)
        except Exception:
            if raw_intent is not None and raw_intent.supports_curve_series:
                from src.rendering.raw_plot_intent import curve_series_from_raw_intent

                series_list = curve_series_from_raw_intent(working_raw, raw_intent, source_path=input_path)
                candidate_roles = _candidate_roles_for_curve(series_list)
            else:
                series_list = []
                candidate_roles = _candidate_roles_for_simple_curve_raw(working_raw)
        semantic_signals = raw_intent.semantic_signals if raw_intent is not None else (
            "Detected a transformed paired curve table.",
            "The transformed data is entering the same recommendation path as imported source data.",
            "The default path is a standard curve plot.",
        )
        if raw_intent is None and series_list and looks_like_tensile_curve(series_list):
            semantic_signals = (
                "The x-axis label or unit matches strain / elongation / %.",
                "The y-axis label or unit matches stress / MPa.",
                "Tensile curves always stay on linear x/y axes by default.",
            )
    column_profiles = _summarize_raw_columns(working_raw)
    quality_flags = tuple(dict.fromkeys(_quality_flags(raw, working_raw=working_raw) + tuple(extra_quality_flags)))
    data_shapes = _data_shapes_for_model("curve_table" if resolved_model == "curve_table" else resolved_model)
    return NormalizedDataset(
        dataset_id=_dataset_id(
            source_path=input_path,
            sheet=sheet,
            model=resolved_model,
            raw_rows=int(raw.shape[0]),
            raw_cols=int(raw.shape[1]),
        ),
        source_path=input_path,
        sheet=sheet,
        raw_rows=int(raw.shape[0]),
        raw_cols=int(raw.shape[1]),
        column_profiles=tuple(column_profiles),
        candidate_roles=candidate_roles,
        data_shapes=data_shapes,
        semantic_signals=semantic_signals,
        quality_flags=quality_flags,
        model=resolved_model,
    )


def build_normalized_dataset(
    input_path: Path,
    sheet: str | int = 0,
    *,
    model: str | None = None,
    options: object = None,
) -> NormalizedDataset:
    if options is not None and getattr(options, "data_transforms", None) is not None:
        raw = read_raw_table_for_options(input_path, sheet, options)
        return _build_normalized_dataset_from_raw(input_path, sheet, raw, model=model)
    cache_key = _normalized_dataset_cache_key(
        input_path=input_path,
        sheet=sheet,
        model=model,
    )
    return _build_normalized_dataset_cached(*cache_key)


def clear_normalized_dataset_cache() -> None:
    _build_normalized_dataset_cached.cache_clear()


def normalized_dataset_payload(dataset: NormalizedDataset) -> dict[str, Any]:
    def _serialize(value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return {field.name: _serialize(getattr(value, field.name)) for field in fields(value)}
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {key: _serialize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_serialize(item) for item in value]
        return value

    return _serialize(dataset)


__all__ = [
    "CandidateRoles",
    "ColumnProfile",
    "DataShape",
    "NormalizedDataset",
    "RoleKey",
    "build_normalized_dataset",
    "clear_normalized_dataset_cache",
    "detect_input_model",
    "detect_point_line_bundle",
    "frequency_metric_sheet_signals",
    "looks_like_frequency_metric_sheet",
    "looks_like_dsc_curve",
    "looks_like_ftir_curve",
    "looks_like_nmr_curve",
    "looks_like_xrd_curve",
    "dataframe_sample_rows",
    "normalized_dataset_payload",
    "point_line_bundle_signals",
]
