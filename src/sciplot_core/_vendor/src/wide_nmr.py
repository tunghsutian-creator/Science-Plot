from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from src.plot_contract import load_plot_contract

_CONTRACT = load_plot_contract()
_WIDE_NMR_LAYOUT = _CONTRACT.special_layouts["wide_nmr"]

WIDE_NMR_WIDTH_MM = float(_WIDE_NMR_LAYOUT["width_mm"])
WIDE_NMR_TOTAL_HEIGHT_MM = float(_WIDE_NMR_LAYOUT["total_height_mm"])
WIDE_NMR_STRUCTURE_RESERVED_MM = float(_WIDE_NMR_LAYOUT["structure_reserved_mm"])
WIDE_NMR_SPECTRUM_HEIGHT_MM = float(_WIDE_NMR_LAYOUT["spectrum_height_mm"])


@dataclass(frozen=True)
class WideNMRSegment:
    x_min: float
    x_max: float
    width_ratio: float | None = None


@dataclass(frozen=True)
class WideNMRHighlightRegion:
    x_min: float
    x_max: float
    label: str
    color: str
    alpha: float = 0.18
    series: tuple[str, ...] = ()
    label_position: str = "top"


@dataclass(frozen=True)
class WideNMRConfig:
    segments: tuple[WideNMRSegment, ...]
    highlight_regions: tuple[WideNMRHighlightRegion, ...] = ()
    series_order: tuple[str, ...] = ()
    series_labels: dict[str, str] = field(default_factory=dict)
    label_side: str = "auto"
    panel_label: str | None = None
    segment_gap: float = 0.03
    stack_floor_fraction: float = 0.24
    stack_gap_fraction: float = 0.26
    label_inset_fraction: float = 0.035
    label_offset_pt: float = 3.5


def wide_nmr_sidecar_path(data_path: str | Path) -> Path:
    path = Path(data_path)
    return path.with_suffix(".wide_nmr.toml")


def _require_float(mapping: dict, key: str) -> float:
    if key not in mapping:
        raise ValueError(f"Missing required key {key!r} in wide NMR config.")
    return float(mapping[key])


def load_wide_nmr_config(data_path: str | Path) -> WideNMRConfig:
    sidecar_path = wide_nmr_sidecar_path(data_path)
    if not sidecar_path.exists():
        raise FileNotFoundError(f"Missing wide NMR sidecar config: {sidecar_path}")

    with sidecar_path.open("rb") as handle:
        raw = tomllib.load(handle)

    layout = raw.get("layout", {})
    segment_rows = raw.get("segments", [])
    if not segment_rows:
        raise ValueError("wide_nmr config must define at least one [[segments]] entry.")

    segments = tuple(
        WideNMRSegment(
            x_min=_require_float(segment, "x_min"),
            x_max=_require_float(segment, "x_max"),
            width_ratio=float(segment["width_ratio"]) if "width_ratio" in segment else None,
        )
        for segment in segment_rows
    )

    highlight_regions = tuple(
        WideNMRHighlightRegion(
            x_min=_require_float(region, "x_min"),
            x_max=_require_float(region, "x_max"),
            label=str(region.get("label", "")).strip(),
            color=str(region.get("color", "#9fbfe8")).strip() or "#9fbfe8",
            alpha=float(region.get("alpha", 0.18)),
            series=tuple(str(item).strip() for item in region.get("series", [])),
            label_position=str(region.get("label_position", "top")).strip().lower() or "top",
        )
        for region in raw.get("highlight_regions", [])
    )

    series_order = tuple(str(item).strip() for item in raw.get("series_order", []) if str(item).strip())
    series_labels = {
        str(key).strip(): str(value).strip()
        for key, value in raw.get("series_labels", {}).items()
        if str(key).strip()
    }

    return WideNMRConfig(
        segments=segments,
        highlight_regions=highlight_regions,
        series_order=series_order,
        series_labels=series_labels,
        label_side=str(layout.get("label_side", "auto")).strip().lower() or "auto",
        panel_label=str(layout.get("panel_label")).strip() if layout.get("panel_label") is not None else None,
        segment_gap=float(layout.get("segment_gap", 0.03)),
        stack_floor_fraction=float(layout.get("stack_floor_fraction", 0.24)),
        stack_gap_fraction=float(layout.get("stack_gap_fraction", 0.26)),
        label_inset_fraction=float(layout.get("label_inset_fraction", 0.035)),
        label_offset_pt=float(layout.get("label_offset_pt", 3.5)),
    )
