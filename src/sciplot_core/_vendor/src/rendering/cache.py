from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from src.data_loader import (
    CurveSeries,
    HeatmapTable,
    ReplicateGroup,
    load_curve_table,
    load_curve_table_from_frame,
    load_heatmap_table,
    load_heatmap_table_from_frame,
    load_replicate_table,
    load_replicate_table_from_frame,
    read_raw_table,
)
from src.rendering.data_transforms import apply_data_transforms_to_frame
from src.rendering.raw_plot_intent import curve_series_from_raw_intent, detect_raw_plot_intent
from src.rheology_loader import (
    RheologySeries,
    load_frequency_sweep_metrics,
    load_stress_relaxation_metric,
    load_temperature_sweep_metrics,
)


def _path_cache_key(input_path: Path, sheet: str | int) -> tuple[str, int, str | int]:
    return (str(input_path.resolve()), input_path.stat().st_mtime_ns, sheet)


def clone_curve_series_list(series_list: list[CurveSeries] | tuple[CurveSeries, ...]) -> list[CurveSeries]:
    return [
        CurveSeries(
            sample=series.sample,
            x_label=series.x_label,
            y_label=series.y_label,
            x_unit=series.x_unit,
            y_unit=series.y_unit,
            data=series.data.copy(deep=True),
        )
        for series in series_list
    ]


def clone_replicate_groups(groups: list[ReplicateGroup] | tuple[ReplicateGroup, ...]) -> list[ReplicateGroup]:
    return [
        ReplicateGroup(
            group=group.group,
            value_label=group.value_label,
            value_unit=group.value_unit,
            data=group.data.copy(deep=True),
        )
        for group in groups
    ]


def clone_heatmap_table(table: HeatmapTable) -> HeatmapTable:
    return HeatmapTable(
        x_label=table.x_label,
        y_label=table.y_label,
        z_label=table.z_label,
        x_unit=table.x_unit,
        y_unit=table.y_unit,
        z_unit=table.z_unit,
        data=table.data.copy(deep=True),
    )


def clone_rheology_series_list(
    series_list: list[RheologySeries] | tuple[RheologySeries, ...],
) -> list[RheologySeries]:
    return [
        RheologySeries(
            sample=series.sample,
            x_label=series.x_label,
            y_label=series.y_label,
            x_unit=series.x_unit,
            y_unit=series.y_unit,
            data=series.data.copy(deep=True),
        )
        for series in series_list
    ]


@lru_cache(maxsize=48)
def _read_raw_table_cached(
    resolved_path: str,
    mtime_ns: int,
    sheet: str | int,
) -> pd.DataFrame:
    return read_raw_table(Path(resolved_path), sheet_name=sheet)


def read_raw_table_cached(input_path: Path, sheet: str | int = 0) -> pd.DataFrame:
    cache_key = _path_cache_key(input_path, sheet)
    return _read_raw_table_cached(*cache_key).copy(deep=True)


def _options_data_transforms(options: object) -> object:
    return getattr(options, "data_transforms", None)


def _options_data_variables(options: object) -> object:
    return getattr(options, "data_variables", None)


def read_raw_table_for_options(input_path: Path, sheet: str | int = 0, options: object = None) -> pd.DataFrame:
    raw = read_raw_table_cached(input_path, sheet)
    transforms = _options_data_transforms(options)
    if transforms is None:
        return raw
    return apply_data_transforms_to_frame(raw, transforms, variables=_options_data_variables(options))


@lru_cache(maxsize=48)
def _load_curve_table_cached(
    resolved_path: str,
    mtime_ns: int,
    sheet: str | int,
) -> tuple[CurveSeries, ...]:
    input_path = Path(resolved_path)
    try:
        return tuple(load_curve_table(input_path, sheet_name=sheet))
    except Exception:
        if input_path.suffix.lower() not in {".csv", ".txt", ".tsv"}:
            raise
        raw = read_raw_table(input_path, sheet_name=sheet)
        intent = detect_raw_plot_intent(raw, input_path)
        if intent is None or not intent.supports_curve_series:
            raise
        return tuple(curve_series_from_raw_intent(raw, intent, source_path=input_path))


def load_curve_table_cached(input_path: Path, sheet: str | int = 0) -> list[CurveSeries]:
    cache_key = _path_cache_key(input_path, sheet)
    return clone_curve_series_list(_load_curve_table_cached(*cache_key))


def load_curve_table_for_options(input_path: Path, sheet: str | int = 0, options: object = None) -> list[CurveSeries]:
    transforms = _options_data_transforms(options)
    if transforms is None:
        return load_curve_table_cached(input_path, sheet)
    raw = apply_data_transforms_to_frame(
        read_raw_table_cached(input_path, sheet),
        transforms,
        variables=_options_data_variables(options),
    )
    try:
        return load_curve_table_from_frame(raw)
    except Exception:
        intent = detect_raw_plot_intent(raw, input_path)
        if intent is None or not intent.supports_curve_series:
            raise
        return curve_series_from_raw_intent(raw, intent, source_path=input_path)


@lru_cache(maxsize=48)
def _load_replicate_table_cached(
    resolved_path: str,
    mtime_ns: int,
    sheet: str | int,
) -> tuple[ReplicateGroup, ...]:
    return tuple(load_replicate_table(Path(resolved_path), sheet_name=sheet))


def load_replicate_table_cached(input_path: Path, sheet: str | int = 0) -> list[ReplicateGroup]:
    cache_key = _path_cache_key(input_path, sheet)
    return clone_replicate_groups(_load_replicate_table_cached(*cache_key))


def load_replicate_table_for_options(
    input_path: Path,
    sheet: str | int = 0,
    options: object = None,
) -> list[ReplicateGroup]:
    transforms = _options_data_transforms(options)
    if transforms is None:
        return load_replicate_table_cached(input_path, sheet)
    raw = apply_data_transforms_to_frame(
        read_raw_table_cached(input_path, sheet),
        transforms,
        variables=_options_data_variables(options),
    )
    return load_replicate_table_from_frame(raw)


@lru_cache(maxsize=48)
def _load_heatmap_table_cached(
    resolved_path: str,
    mtime_ns: int,
    sheet: str | int,
) -> HeatmapTable:
    return load_heatmap_table(Path(resolved_path), sheet_name=sheet)


def load_heatmap_table_cached(input_path: Path, sheet: str | int = 0) -> HeatmapTable:
    cache_key = _path_cache_key(input_path, sheet)
    return clone_heatmap_table(_load_heatmap_table_cached(*cache_key))


def load_heatmap_table_for_options(input_path: Path, sheet: str | int = 0, options: object = None) -> HeatmapTable:
    transforms = _options_data_transforms(options)
    if transforms is None:
        return load_heatmap_table_cached(input_path, sheet)
    raw = apply_data_transforms_to_frame(
        read_raw_table_cached(input_path, sheet),
        transforms,
        variables=_options_data_variables(options),
    )
    return load_heatmap_table_from_frame(raw)


@lru_cache(maxsize=48)
def _load_frequency_sweep_metrics_cached(
    resolved_path: str,
    mtime_ns: int,
    sheet: str | int,
) -> dict[str, tuple[RheologySeries, ...]]:
    return {
        metric_name: tuple(series_list)
        for metric_name, series_list in load_frequency_sweep_metrics(
            Path(resolved_path),
            sheet_name=sheet,
        ).items()
    }


def load_frequency_sweep_metrics_cached(input_path: Path, sheet: str | int = 0) -> dict[str, list[RheologySeries]]:
    cache_key = _path_cache_key(input_path, sheet)
    cached = _load_frequency_sweep_metrics_cached(*cache_key)
    return {
        metric_name: clone_rheology_series_list(series_list)
        for metric_name, series_list in cached.items()
    }


@lru_cache(maxsize=48)
def _load_temperature_sweep_metrics_cached(
    resolved_path: str,
    mtime_ns: int,
    sheet: str | int,
) -> dict[str, tuple[RheologySeries, ...]]:
    return {
        metric_name: tuple(series_list)
        for metric_name, series_list in load_temperature_sweep_metrics(
            Path(resolved_path),
            sheet_name=sheet,
        ).items()
    }


def load_temperature_sweep_metrics_cached(input_path: Path, sheet: str | int = 0) -> dict[str, list[RheologySeries]]:
    cache_key = _path_cache_key(input_path, sheet)
    cached = _load_temperature_sweep_metrics_cached(*cache_key)
    return {
        metric_name: clone_rheology_series_list(series_list)
        for metric_name, series_list in cached.items()
    }


@lru_cache(maxsize=48)
def _load_stress_relaxation_metric_cached(
    resolved_path: str,
    mtime_ns: int,
    sheet: str | int,
    metric_name: str,
) -> tuple[RheologySeries, ...]:
    return tuple(
        load_stress_relaxation_metric(
            Path(resolved_path),
            metric_name=metric_name,
            sheet_name=sheet,
        )
    )


def load_stress_relaxation_metric_cached(
    input_path: Path,
    metric_name: str = "σ/σ₀",
    sheet: str | int = 0,
) -> list[RheologySeries]:
    resolved_path, mtime_ns, resolved_sheet = _path_cache_key(input_path, sheet)
    return clone_rheology_series_list(
        _load_stress_relaxation_metric_cached(
            resolved_path,
            mtime_ns,
            resolved_sheet,
            metric_name,
        )
    )


def clear_input_cache() -> None:
    _read_raw_table_cached.cache_clear()
    _load_curve_table_cached.cache_clear()
    _load_replicate_table_cached.cache_clear()
    _load_heatmap_table_cached.cache_clear()
    _load_frequency_sweep_metrics_cached.cache_clear()
    _load_temperature_sweep_metrics_cached.cache_clear()
    _load_stress_relaxation_metric_cached.cache_clear()
