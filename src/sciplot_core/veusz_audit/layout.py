"""Collect graph, grid, auxiliary, and axis geometry from painted widgets."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_audit.measurements import _distance_pt, _rounded


def _setting_value(
    settings: dict[str, Any],
    name: str,
    default: object = None,
) -> object:
    setting = settings.get(name)
    return setting.val if setting is not None else default


def collect_layout_inventory(
    ordered_widgets: list[tuple[str, Any]],
    state_by_path: dict[str, dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    graphs: list[dict[str, Any]] = []

    grids: list[dict[str, Any]] = []

    auxiliaries: list[dict[str, Any]] = []

    axes: list[dict[str, Any]] = []

    for widget_path, widget in ordered_widgets:
        state = state_by_path.get(widget_path)
        if state is None:
            continue
        helper = state["helper"]
        widget_type = str(getattr(widget, "typename", ""))
        if widget_type == "graph":
            margins = {}
            for side in ("left", "right", "top", "bottom"):
                setting = widget.settings.setdict.get(f"{side}Margin")
                points = _distance_pt(setting, helper) if setting is not None else None
                margins[side] = (
                    _rounded(points * 25.4 / 72.0) if points is not None else None
                )
            plot_bounds = state["bounds_mm"]
            slot_bounds = None
            if plot_bounds is not None and all(
                value is not None for value in margins.values()
            ):
                slot_bounds = [
                    _rounded(plot_bounds[0] - float(margins["left"])),
                    _rounded(plot_bounds[1] - float(margins["top"])),
                    _rounded(plot_bounds[2] + float(margins["right"])),
                    _rounded(plot_bounds[3] + float(margins["bottom"])),
                ]
            graphs.append(
                {
                    "path": widget_path,
                    "page": state["page"],
                    "parent_path": str(widget.parent.path)
                    if widget.parent is not None
                    else None,
                    "parent_type": str(getattr(widget.parent, "typename", ""))
                    if widget.parent is not None
                    else None,
                    "plot_bounds_mm": plot_bounds,
                    "slot_bounds_mm": slot_bounds,
                    "margins_mm": margins,
                    "aspect": (
                        widget.settings.setdict.get("aspect").val
                        if "aspect" in widget.settings.setdict
                        else None
                    ),
                }
            )
        elif widget_type == "grid":
            margins = {}
            for side in ("left", "right", "top", "bottom"):
                setting = widget.settings.setdict.get(f"{side}Margin")
                points = _distance_pt(setting, helper) if setting is not None else None
                margins[side] = (
                    _rounded(points * 25.4 / 72.0) if points is not None else None
                )
            internal = widget.settings.setdict.get("internalMargin")
            internal_pt = (
                _distance_pt(internal, helper) if internal is not None else None
            )
            grids.append(
                {
                    "path": widget_path,
                    "page": state["page"],
                    "parent_path": str(widget.parent.path)
                    if widget.parent is not None
                    else None,
                    "bounds_mm": state["bounds_mm"],
                    "margins_mm": margins,
                    "internal_margin_mm": _rounded(internal_pt * 25.4 / 72.0)
                    if internal_pt is not None
                    else None,
                    "rows": int(widget.settings.rows),
                    "columns": int(widget.settings.columns),
                    "scale_rows": [
                        _rounded(value) for value in widget.settings.scaleRows
                    ],
                    "scale_columns": [
                        _rounded(value) for value in widget.settings.scaleCols
                    ],
                }
            )
        elif widget_type == "colorbar":
            parent_path = str(widget.parent.path) if widget.parent is not None else None
            auxiliaries.append(
                {
                    "path": widget_path,
                    "type": widget_type,
                    "page": state["page"],
                    "parent_path": parent_path,
                    "bounds_mm": state["bounds_mm"],
                }
            )
        elif widget_type == "axis":
            settings = widget.settings.setdict

            axes.append(
                {
                    "path": widget_path,
                    "name": str(widget.name),
                    "page": state["page"],
                    "graph_path": (
                        str(widget.parent.path) if widget.parent is not None else None
                    ),
                    "label": str(_setting_value(settings, "label", "") or "").strip(),
                    "scale": (
                        "log"
                        if bool(_setting_value(settings, "log", False))
                        else "linear"
                    ),
                    "min": _setting_value(settings, "min", "Auto"),
                    "max": _setting_value(settings, "max", "Auto"),
                    "direction": str(_setting_value(settings, "direction", "") or ""),
                    "mode": str(_setting_value(settings, "mode", "") or ""),
                    "hidden": bool(_setting_value(settings, "hide", False)),
                }
            )
    return graphs, grids, auxiliaries, axes
