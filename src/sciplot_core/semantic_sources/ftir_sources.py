"""Read, clean, identify, and order FTIR spectral sources."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    token as _token,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _scan_curve_series_source,
)

from sciplot_core.semantic_sources.series_labels import (
    _source_display_sample,
)


def _ftir_source_files(source: Path) -> list[Path]:
    suffixes = {".csv", ".tsv", ".txt"}
    if source.is_file() and source.suffix.lower() in suffixes:
        return [source]
    if not source.is_dir():
        return []
    return sorted(
        (
            path
            for path in source.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes
        ),
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
        return (
            candidate <= 5.0
            and neighbor > 20.0
            and local_median > 20.0
            and neighbor - candidate > 20.0
        )

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
        "boundary_sentinel_rule": (
            "isolated <=5 %T endpoint next to a >20 %T trace with local median >20 %T"
        ),
    }
    return tuple(cleaned), diagnostics


def _read_headerless_ftir_series(source: Path) -> CurveSeriesPayload:
    raw: pd.DataFrame | None = None
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            raw = pd.read_csv(
                source, header=None, sep=None, engine="python", encoding=encoding
            )
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
            for x_value, y_value in zip(
                numeric.iloc[:, x_index], numeric.iloc[:, y_index], strict=False
            )
            if pd.notna(x_value) and pd.notna(y_value)
        ]
        if len(points) > len(best_points):
            best_points = points
    if len(best_points) < 4:
        raise ValueError(f"No numeric two-column FTIR spectrum found in {source}.")
    x_values = [point[0] for point in best_points]
    if (
        min(x_values) < 50.0
        or max(x_values) > 10000.0
        or max(x_values) - min(x_values) < 100.0
    ):
        raise ValueError(f"FTIR wavenumber range is not plausible in {source}.")
    cleaned_points, diagnostics = _clean_ftir_boundary_artifacts(best_points)
    if len(cleaned_points) < 4:
        raise ValueError(
            f"FTIR spectrum has too few points after boundary cleanup in {source}."
        )
    return CurveSeriesPayload(
        sample=_source_display_sample(source),
        x_label="Wavenumber",
        x_unit="cm^-1",
        y_label="Transmittance",
        y_unit="%",
        points=cleaned_points,
        diagnostics={
            "source_file": str(source),
            "ftir_measurement_mode": "percent_transmittance",
            **diagnostics,
        },
    )


def _ftir_measurement_identity(
    series: CurveSeriesPayload,
) -> tuple[str, str, str]:
    diagnostics = series.diagnostics or {}
    header = str(diagnostics.get("source_y_header") or series.y_label)
    header_text = header.casefold()
    header_token = _token(header)
    if "absorbance" in header_text or header_token in {"abs", "absorbance"}:
        y_unit = series.y_unit
        if not y_unit or y_unit == "%":
            y_unit = "a.u."
        return "Absorbance", y_unit, "absorbance"
    if (
        "transmittance" in header_text
        or "%t" in header_text.replace(" ", "")
        or header_token in {"t", "percenttransmittance"}
    ):
        return "Transmittance", series.y_unit or "%", "percent_transmittance"
    return series.y_label, series.y_unit, "unclassified_structured_ftir_response"


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
        y_label, y_unit, measurement_mode = _ftir_measurement_identity(series)
        cleaned_points, diagnostics = _clean_ftir_boundary_artifacts(series.points)
        return [
            CurveSeriesPayload(
                sample=_source_display_sample(source),
                x_label=series.x_label,
                x_unit=series.x_unit,
                y_label=y_label,
                y_unit=y_unit,
                points=cleaned_points,
                diagnostics={
                    **(series.diagnostics or {}),
                    "source_file": str(source),
                    "ftir_measurement_mode": measurement_mode,
                    **diagnostics,
                },
            )
        ]
    if structured:
        cleaned: list[CurveSeriesPayload] = []
        for series in structured:
            y_label, y_unit, measurement_mode = _ftir_measurement_identity(series)
            cleaned_points, diagnostics = _clean_ftir_boundary_artifacts(series.points)
            cleaned.append(
                CurveSeriesPayload(
                    sample=series.sample,
                    x_label=series.x_label,
                    x_unit=series.x_unit,
                    y_label=y_label,
                    y_unit=y_unit,
                    points=cleaned_points,
                    diagnostics={
                        **(series.diagnostics or {}),
                        "source_file": str(source),
                        "ftir_measurement_mode": measurement_mode,
                        **diagnostics,
                    },
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
    if errors:
        detail = "; ".join(errors[:3])
        raise ValueError(
            "FTIR preparation rejected one or more in-scope source files; "
            f"silent partial datasets are not allowed ({detail})."
        )
    measurement_modes = {
        str((series.diagnostics or {}).get("ftir_measurement_mode") or "")
        for series in series_list
    }
    measurement_modes.discard("")
    measurement_modes.discard("unclassified_structured_ftir_response")
    if len(measurement_modes) > 1:
        raise ValueError(
            "FTIR transmittance and absorbance spectra cannot share one "
            "stacked-response axis. Prepare separate figures for each "
            f"measurement mode: {sorted(measurement_modes)}."
        )
    return series_list
