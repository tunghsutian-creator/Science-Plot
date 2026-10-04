"""Compile explicit rheology-analysis panels through shared Veusz contracts."""

from __future__ import annotations

import math
import re
from typing import Any

from sciplot_core.rheology_tts_style import (
    finalize_tts_encoding,
    prepare_tts_presentation,
    resolve_tts_series,
)
from sciplot_core.rheology_tts_errors import axis_extent_series, supplied_error_values
from sciplot_core.studio_core.veusz_spec_builder import _style_spec
from sciplot_core.studio_core.veusz_spec_series import build_veusz_series_specs
from sciplot_core.studio_render.axes_spec import _veusz_axes_spec
from sciplot_core.studio_render.axis_contract import _veusz_axis_contract
from sciplot_core.studio_render.models import StudioSeries
from sciplot_core.studio_render.style_contract import _veusz_style_contract


def _identifier(value: object) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text) is None:
        raise ValueError(f"Invalid native figure or panel identifier: {text!r}")
    return text


def _numbers(value: object, name: str) -> list[float]:
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError(f"{name} requires a nonempty numeric array.")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} contains nonfinite values; no rows were removed.")
    return result


def compile_tts_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate explicit presentation and retain its source/transform evidence."""
    if spec.get("version") != 1 or not isinstance(spec.get("source_binding"), dict):
        raise ValueError("A version-1 source-bound figure specification is required.")
    governed = "presentation_policy" in spec
    if governed:
        spec = prepare_tts_presentation(spec)
    figures = spec.get("figures")
    if not isinstance(figures, list) or not figures:
        raise ValueError("At least one figure is required.")
    compiled = []
    seen: set[str] = set()
    for figure in figures:
        identifier = _identifier(figure["id"])
        if identifier in seen:
            raise ValueError(f"Duplicate figure identifier: {identifier}")
        seen.add(identifier)
        width, height = _numbers([figure["width_mm"], figure["height_mm"]], "size")
        if min(width, height) <= 0:
            raise ValueError("Figure dimensions must be positive.")
        panels = figure.get("panels")
        if not isinstance(panels, list) or not panels:
            raise ValueError("Every figure requires panels.")
        panel_ids = [_identifier(panel["id"]) for panel in panels]
        if len(set(panel_ids)) != len(panel_ids):
            raise ValueError("Panel identifiers must be unique within each figure.")
        compiled.append(
            {
                "id": identifier,
                "width_mm": width,
                "height_mm": height,
                "panels": [
                    _compile_panel(panel, width, height, governed=governed)
                    for panel in panels
                ],
            }
        )
    result = {
        "kind": "sciplot_rheology_tts_native_suite",
        "version": 1,
        "source_binding": spec["source_binding"],
        "transform_ledger": spec.get("transform_ledger", {}),
        "figures": compiled,
    }
    if governed:
        result["presentation_policy"] = dict(spec["presentation_policy"])
    return result


def _compile_panel(
    panel: dict[str, Any], width: float, height: float, *, governed: bool = False
) -> dict[str, Any]:
    identifier = _identifier(panel["id"])
    rect = _numbers(panel["rect_mm"], "rect_mm")
    if len(rect) != 4:
        raise ValueError("rect_mm must be [left, top, width, height].")
    left, top, panel_width, panel_height = rect
    if min(left, top) < 0 or min(panel_width, panel_height) <= 0:
        raise ValueError(
            "Panel rectangles require positive size and nonnegative origins."
        )
    if left + panel_width > width + 1e-9 or top + panel_height > height + 1e-9:
        raise ValueError("Panel rectangle lies outside the native page.")
    options = {
        key: panel[key]
        for key in (
            "xscale",
            "yscale",
            "x_min",
            "x_max",
            "y_min",
            "y_max",
            "x_ticks",
            "y_ticks",
            "x_tick_format",
            "y_tick_format",
        )
        if key in panel
    }
    for axis in ("x", "y"):
        if options.get(f"{axis}scale", "linear") not in ("linear", "log"):
            raise ValueError("Axes must use linear or log scales.")
    style = _veusz_style_contract(options)
    typed = []
    raw_series = panel.get("series")
    if not isinstance(raw_series, list) or not raw_series:
        raise ValueError("Every panel requires explicit series.")
    for index, raw in enumerate(raw_series):
        x, y = _numbers(raw["x"], "x"), _numbers(raw["y"], "y")
        if len(x) != len(y):
            raise ValueError(
                "Paired curve lengths differ; no values were padded or truncated."
            )
        errors = supplied_error_values(raw, y, options.get("yscale", "linear"))
        for axis, values in (("x", x), ("y", y)):
            if options.get(f"{axis}scale") == "log" and min(values) <= 0:
                raise ValueError(
                    f"Nonpositive {axis} data cannot enter a logarithmic panel."
                )
        kind = raw.get("kind", "curve")
        if kind not in ("curve", "bar"):
            raise ValueError(f"Unsupported native analysis series kind: {kind}")
        line_style = str(raw.get("line_style", "solid"))
        line_style = {"dash": "dashed", "dot": "dotted"}.get(line_style, line_style)
        if line_style not in ("solid", "dashed", "dotted", "dash-dot", "none"):
            raise ValueError(f"Unsupported line style: {line_style}")
        for dimension in ("marker_size", "line_width"):
            if dimension in raw and (
                not math.isfinite(float(raw[dimension])) or float(raw[dimension]) <= 0
            ):
                raise ValueError(f"{dimension} must be finite and positive.")
        typed.append(
            StudioSeries(
                label=str(raw["series_id"] if governed else raw.get("label", "")),
                x_name=f"{identifier}_s{index}_x",
                y_name=f"{identifier}_s{index}_y",
                x_values=tuple(x),
                y_values=tuple(y),
                error_values=errors,
                color=str(raw["color"]),
                line_style="solid" if line_style == "none" else line_style,
                marker=None if governed else raw.get("marker", "none"),
                marker_fill_color=raw.get("marker_fill"),
                marker_size=raw.get("marker_size"),
                line_width=raw.get("line_width"),
            )
        )
    if governed:
        typed = resolve_tts_series(panel, typed)
    if any(raw.get("kind") == "bar" for raw in raw_series):
        if options.get("xscale") == "log" or options.get("yscale") == "log":
            raise ValueError(
                "Native summary bars require linear axes and a zero baseline."
            )
        options.setdefault(
            "y_min",
            min(
                0.0,
                min(
                    (
                        min(item.y_values)
                        for item in axis_extent_series(typed)
                        if item.error_values
                    ),
                    default=0.0,
                ),
            ),
        )
        extents = [
            (
                x - float(raw.get("bar_width", 0.65)) / 2,
                x + float(raw.get("bar_width", 0.65)) / 2,
            )
            for raw in raw_series
            for x in raw["x"]
        ]
        options.setdefault("x_min", min(pair[0] for pair in extents) - 0.15)
        options.setdefault("x_max", max(pair[1] for pair in extents) + 0.15)
    template_id = panel["template_id"] if governed else "curve"
    axes = _veusz_axis_contract(
        options,
        template_id=template_id,
        series=axis_extent_series(typed),
        explicit_render_options=options,
    )
    axis_specs = _veusz_axes_spec(
        render_options=options,
        axis_info={"x_label": str(panel["x_label"]), "y_label": str(panel["y_label"])},
        axis_contract=axes,
        categorical_contract=None,
        style=style,
    )
    series = build_veusz_series_specs(
        series=typed,
        template_id=template_id,
        render_options=options,
        categorical_contract=None,
        categorical_visual_style={},
        style=style,
    )
    for entry, raw in zip(series, raw_series, strict=True):
        entry["kind"] = raw.get("kind", "curve")
        entry["bar_width"] = float(raw.get("bar_width", 0.65))
        if entry["bar_width"] <= 0:
            raise ValueError("Bar width must be positive.")
        if raw.get("line_style") == "none":
            entry["encoding"]["line"]["visible"] = False
        if raw.get("marker_fill") == "none":
            entry["encoding"]["marker"]["fill_visible"] = False
        if raw.get("legend", True) is False:
            entry["legend_key"] = ""
        if governed:
            finalize_tts_encoding(entry, raw)
    ticks = panel.get("x_tick_labels", [])
    if ticks and len(ticks) != len(options.get("x_ticks", [])):
        raise ValueError(
            "Manual tick labels require the same number of explicit ticks."
        )
    result = {
        "id": identifier,
        "title": str(panel.get("title", "")),
        "rect_mm": rect,
        "standard_frame": bool(panel.get("standard_frame", False)),
        "style": _style_spec(style),
        "axes": axis_specs,
        "series": series,
        "legend": panel.get("legend", "upper_left"),
        "x_tick_labels": list(ticks),
        "reference_lines": list(panel.get("reference_lines", [])),
        "notes": list(panel.get("notes", [])),
    }
    if governed:
        result["template_id"] = template_id
    return result
