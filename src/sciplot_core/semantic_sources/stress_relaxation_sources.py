"""Read, crop, normalize, and order stress-relaxation source series."""

from __future__ import annotations

import math
from pathlib import Path
import pandas as pd


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
    _StressRelaxationHoldError,
)

from sciplot_core.semantic_sources.table_scanning import (
    _rheology_test_sections,
    _read_raw_table_normalized,
    _scan_curve_series_source,
)

from sciplot_core.semantic_sources.series_labels import (
    _source_display_sample,
    _with_series_sample,
)

from sciplot_core.semantic_sources.rheology_interval import (
    _read_rheology_interval_series,
)

from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _sweep_source_files,
)

from sciplot_core.semantic_sources.stress_relaxation_hold import (
    _normalize_strain_controlled_hold,
)

from sciplot_core.semantic_sources.series_normalization import (
    _normalize_series,
)


def _read_wide_stress_relaxation_series(source: Path) -> list[CurveSeriesPayload]:
    series_list = _scan_curve_series_source(
        source,
        x_aliases=("time", "时间"),
        y_aliases=(
            "normalized stress",
            "normalised stress",
            "shear stress",
            "shearstress",
            "stress",
            "应力",
        ),
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


def _read_strain_controlled_stress_relaxation_series(
    source: Path,
    *,
    raw: pd.DataFrame | None = None,
) -> CurveSeriesPayload:
    response = _read_rheology_interval_series(
        source,
        y_candidates=("shearstress", "stress", "应力"),
        y_label="Shear stress",
        y_unit="Pa",
        preferred_result_tokens=("stress relaxation", "relaxation"),
        raw=raw,
    )
    control = _read_rheology_interval_series(
        source,
        y_candidates=("shearstrain", "strain", "应变"),
        y_label="Shear strain",
        y_unit="%",
        preferred_result_tokens=("stress relaxation", "relaxation"),
        raw=raw,
    )
    return _normalize_strain_controlled_hold(response, control)


def _retain_positive_stress_relaxation_time(
    series: CurveSeriesPayload,
) -> CurveSeriesPayload:
    retained = tuple(
        (time_value, response_value)
        for time_value, response_value in series.points
        if (
            math.isfinite(time_value)
            and math.isfinite(response_value)
            and time_value > 0.0
        )
    )
    excluded_nonpositive_time = sum(
        math.isfinite(time_value) and time_value <= 0.0
        for time_value, _response_value in series.points
    )
    excluded_nonfinite_points = sum(
        not (math.isfinite(time_value) and math.isfinite(response_value))
        for time_value, response_value in series.points
    )
    if len(retained) < 2:
        raise ValueError(
            "Stress-relaxation logarithmic time rendering needs at least two "
            "finite points with time > 0."
        )
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=retained,
        diagnostics={
            **(series.diagnostics or {}),
            "log_domain_source_point_count": len(series.points),
            "excluded_nonpositive_time_count": excluded_nonpositive_time,
            "excluded_nonfinite_log_domain_point_count": excluded_nonfinite_points,
            "log_domain_selected_point_count": len(retained),
            "time_log_domain_policy": (
                "retain only finite time > 0 for logarithmic time rendering"
            ),
        },
    )


def _read_stress_relaxation_source_series(source: Path) -> list[CurveSeriesPayload]:
    fallback = _source_display_sample(source)
    raw = _read_raw_table_normalized(source).dropna(axis=1, how="all")
    sections = _rheology_test_sections(raw, fallback=fallback)
    parsed: list[CurveSeriesPayload] = []
    section_errors: list[str] = []
    for sample, block in sections:
        try:
            normalized = _read_strain_controlled_stress_relaxation_series(
                source,
                raw=block,
            )
            normalized = _retain_positive_stress_relaxation_time(normalized)
            parsed.append(
                _with_series_sample(
                    CurveSeriesPayload(
                        sample=normalized.sample,
                        x_label=normalized.x_label,
                        x_unit=normalized.x_unit,
                        y_label=normalized.y_label,
                        y_unit=normalized.y_unit,
                        points=normalized.points,
                        diagnostics={
                            **(normalized.diagnostics or {}),
                            "source_file": str(source),
                            "source_test_label": sample,
                        },
                    ),
                    sample,
                )
            )
        except _StressRelaxationHoldError:
            raise
        except ValueError as exc:
            section_errors.append(f"{sample}: {exc}")
    if parsed:
        if section_errors:
            raise ValueError(
                "Stress-relaxation preparation rejected one or more test "
                f"sections ({'; '.join(section_errors[:3])})."
            )
        return parsed

    try:
        series_list = _read_wide_stress_relaxation_series(source)
    except ValueError as exc:
        raise ValueError(
            "The stress-relaxation contract requires shear stress, "
            "normalized stress, or a strain-controlled stress response. "
            "Relaxation modulus G(t) needs a separate G/G0 axis and metric "
            "contract and is not relabeled as sigma/sigma0."
        ) from exc
    series_list = [
        _retain_positive_stress_relaxation_time(series) for series in series_list
    ]
    if len(series_list) == 1:
        return [_with_series_sample(series_list[0], fallback)]
    return series_list


def _read_stress_relaxation_series_list(source: Path) -> list[CurveSeriesPayload]:
    if not source.is_dir():
        return _read_stress_relaxation_source_series(source)
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for candidate in _sweep_source_files(source):
        try:
            series_list.extend(_read_stress_relaxation_source_series(candidate))
        except _StressRelaxationHoldError as exc:
            raise ValueError(f"{candidate.name}: {exc}") from exc
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(
            f"No stress-relaxation exports found under {source}. {detail}".strip()
        )
    if errors:
        detail = "; ".join(errors[:3])
        raise ValueError(
            "Stress-relaxation preparation rejected one or more in-scope "
            f"source files; silent partial datasets are not allowed ({detail})."
        )
    unique: dict[
        tuple[str, str, str, tuple[tuple[float, float], ...]],
        CurveSeriesPayload,
    ] = {}
    duplicate_sources: dict[
        tuple[str, str, str, tuple[tuple[float, float], ...]],
        list[str],
    ] = {}
    for series in series_list:
        key = (series.sample, series.x_unit, series.y_unit, series.points)
        source_file = str((series.diagnostics or {}).get("source_file") or "")
        if key not in unique:
            unique[key] = series
            duplicate_sources[key] = [source_file] if source_file else []
        elif source_file and source_file not in duplicate_sources[key]:
            duplicate_sources[key].append(source_file)
    deduplicated: list[CurveSeriesPayload] = []
    for key, series in unique.items():
        sources = duplicate_sources[key]
        diagnostics = dict(series.diagnostics or {})
        diagnostics["equivalent_source_files"] = sources
        diagnostics["equivalent_source_file_count"] = len(sources)
        diagnostics["deduplication_policy"] = (
            "same internal test label, units, and exact normalized points"
        )
        deduplicated.append(
            CurveSeriesPayload(
                sample=series.sample,
                x_label=series.x_label,
                x_unit=series.x_unit,
                y_label=series.y_label,
                y_unit=series.y_unit,
                points=series.points,
                diagnostics=diagnostics,
            )
        )
    return deduplicated
