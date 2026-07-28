"""Normalize export formats, names, and split-series labels."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    normalize_export_formats,
)
from sciplot_core.render.series_selection import (
    filter_curve_series,
    reorder_curve_series,
    unknown_series_order_labels,
)
from sciplot_core.source_tables import load_curve_table


_EXPORT_FORMATS = {
    "pdf": ("pdf", None, ""),
    "svg": ("svg", None, ""),
    "png_300": ("png", 300, "_300dpi"),
    "png_600": ("png", 600, "_600dpi"),
    "tiff_300": ("tiff", 300, "_300dpi"),
}


DEFAULT_EXPORT_FORMATS = DEFAULT_EXPORT_FORMATS_POLICY


DEFAULT_RENDER_ENGINE = "veusz"


def _normalize_export_formats(
    export_formats: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    return normalize_export_formats(export_formats, default=DEFAULT_EXPORT_FORMATS)


def _export_path(filename: str, output_dir: Path, export_format: str) -> Path:
    target_format, _dpi, suffix = _EXPORT_FORMATS[export_format]
    base = Path(filename).with_suffix("").name
    if target_format == "pdf":
        return output_dir / f"{base}.pdf"
    extension = "tiff" if target_format == "tiff" else target_format
    return output_dir / f"{base}{suffix}.{extension}"


def _series_labels_for_split(
    source: Path, sheet: str | int, options: dict[str, Any]
) -> list[str]:
    series_list = load_curve_table(source, sheet_name=sheet)
    available = [series.sample for series in series_list]
    series_include = options.get("series_include")
    unknown_include = unknown_series_order_labels(available, series_include)
    if unknown_include:
        raise ValueError(
            "series_include contains unknown series labels: "
            + ", ".join(unknown_include)
        )
    selected = filter_curve_series(series_list, series_include)
    if not selected and series_include:
        raise ValueError("series_include did not match any series.")
    selected_labels = [series.sample for series in selected]
    series_order = options.get("series_order")
    unknown_order = unknown_series_order_labels(selected_labels, series_order)
    if unknown_order:
        raise ValueError(
            "series_order contains unknown series labels: " + ", ".join(unknown_order)
        )
    ordered = reorder_curve_series(selected, series_order)
    return [series.sample for series in ordered]
