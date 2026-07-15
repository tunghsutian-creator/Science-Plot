from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rounded(value: object, digits: int = 6) -> float:
    return round(float(value), digits)


def _bounds_mm(bounds: object, *, dpi: float = 72.0) -> list[float] | None:
    if not isinstance(bounds, tuple | list) or len(bounds) != 4:
        return None
    return [_rounded(float(value) / dpi * 25.4) for value in bounds]


def _owner_widget(path: str, widgets_by_path: dict[str, Any]) -> tuple[str, Any] | None:
    matches = [
        widget_path
        for widget_path in widgets_by_path
        if path == widget_path or path.startswith(widget_path + "/")
    ]
    if not matches:
        return None
    owner_path = max(matches, key=len)
    return owner_path, widgets_by_path[owner_path]


def _setting_hidden(settings: Any) -> bool:
    hide = settings.setdict.get("hide")
    transparency = settings.setdict.get("transparency")
    return bool(hide is not None and hide.val) or bool(
        transparency is not None and float(transparency.val) >= 100.0
    )


def _distance_pt(setting: Any, helper: Any) -> float | None:
    try:
        from veusz.setting import Distance

        if not isinstance(setting, Distance):
            return None
        points = Distance.convertDistance(helper, str(setting.val)) / float(helper.pixperpt)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return _rounded(points)


def _distance_value_pt(value: object, helper: Any) -> float | None:
    try:
        from veusz.setting import Distance

        points = Distance.convertDistance(helper, str(value)) / float(helper.pixperpt)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return _rounded(points)


def _resolved_rgb(document: Any, value: object, *, widget: Any, helper: Any) -> dict[str, Any] | None:
    name = str(value or "").strip()
    if not name:
        return None
    if name.casefold() == "auto":
        try:
            index = int(helper.autoColorIndex((widget, 0))) + 1
            name = str(document.evaluate.colors.getIndex(index))
        except Exception:
            return None
    try:
        color = document.evaluate.colors.get(name)
    except Exception:
        return None
    if color is None or not color.isValid():
        return None
    rgb = [_rounded(color.redF()), _rounded(color.greenF()), _rounded(color.blueF())]
    return {
        "source": str(value),
        "resolved_name": name,
        "hex": color.name().upper(),
        "rgb": rgb,
        "alpha": _rounded(color.alphaF()),
    }


def _group_color(document: Any, group: Any, *, widget: Any, helper: Any) -> dict[str, Any] | None:
    setting = group.setdict.get("color") if group is not None else None
    return (
        _resolved_rgb(document, setting.val, widget=widget, helper=helper)
        if setting is not None
        else None
    )


def _line_group_item(
    *,
    path: str,
    node: Any,
    owner_path: str,
    owner: Any,
    helper: Any,
    document: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    width = node.setdict.get("width")
    color = node.setdict.get("color")
    if width is None or color is None:
        return None, None
    active = not _setting_hidden(node)
    if node.name == "MarkerLine":
        marker = owner.settings.setdict.get("marker")
        active = active and marker is not None and str(marker.val).casefold() not in {"", "none"}
    width_pt = _distance_pt(width, helper)
    item = {
        "path": path,
        "owner_path": owner_path,
        "owner_type": str(getattr(owner, "typename", owner.__class__.__name__)),
        "setting_type": node.__class__.__name__,
        "source_kind": "line_group",
        "active": active,
        "width_source": str(width.val),
        "width_pt": width_pt,
        "style": str(node.setdict["style"].val) if "style" in node.setdict else None,
        "color": _resolved_rgb(document, color.val, widget=owner, helper=helper),
    }
    if active and width_pt is None:
        return item, {
            "path": path,
            "reason": "active_line_width_is_not_a_resolvable_physical_distance",
            "value": str(width.val),
            "setting_type": width.__class__.__name__,
        }
    return item, None


def _iter_widgets(document: Any) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    widgets_by_path: dict[str, Any] = {}
    ordered: list[tuple[str, Any]] = []

    def collect(path: str, node: Any) -> None:
        widgets_by_path[path] = node
        ordered.append((path, node))

    document.walkNodes(collect, nodetypes=("widget",))
    return widgets_by_path, ordered


def _audit_document(path: Path) -> dict[str, Any]:
    from veusz import dataimport, document, widgets
    from veusz.document.painthelper import PaintHelper

    _ = dataimport, widgets
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Veusz document not found: {resolved}")

    doc = document.Document()
    doc.load(str(resolved))
    widgets_by_path, ordered_widgets = _iter_widgets(doc)
    state_by_path: dict[str, dict[str, Any]] = {}
    pages: list[dict[str, Any]] = []
    helpers_by_page: dict[int, Any] = {}
    for page_index in doc.getVisiblePages():
        size = doc.pageSize(page_index, dpi=(72.0, 72.0), integer=False)
        helper = PaintHelper(doc, size, dpi=(72.0, 72.0))
        doc.paintTo(helper, page_index)
        helpers_by_page[page_index] = helper
        page_widget = doc.getPage(page_index)
        page_path = str(page_widget.path)
        for (widget, layer), state in helper.states.items():
            if layer != 0:
                continue
            state_by_path[str(widget.path)] = {
                "page": page_index + 1,
                "bounds_mm": _bounds_mm(state.bounds),
                "helper": helper,
            }
        pages.append(
            {
                "page": page_index + 1,
                "path": page_path,
                "size_mm": [_rounded(float(size[0]) / 72.0 * 25.4), _rounded(float(size[1]) / 72.0 * 25.4)],
                "bounds_mm": [0.0, 0.0, _rounded(float(size[0]) / 72.0 * 25.4), _rounded(float(size[1]) / 72.0 * 25.4)],
            }
        )

    graphs: list[dict[str, Any]] = []
    grids: list[dict[str, Any]] = []
    auxiliaries: list[dict[str, Any]] = []
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
                margins[side] = _rounded(points * 25.4 / 72.0) if points is not None else None
            plot_bounds = state["bounds_mm"]
            slot_bounds = None
            if plot_bounds is not None and all(value is not None for value in margins.values()):
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
                    "parent_path": str(widget.parent.path) if widget.parent is not None else None,
                    "parent_type": str(getattr(widget.parent, "typename", "")) if widget.parent is not None else None,
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
                margins[side] = _rounded(points * 25.4 / 72.0) if points is not None else None
            internal = widget.settings.setdict.get("internalMargin")
            internal_pt = _distance_pt(internal, helper) if internal is not None else None
            grids.append(
                {
                    "path": widget_path,
                    "page": state["page"],
                    "parent_path": str(widget.parent.path) if widget.parent is not None else None,
                    "bounds_mm": state["bounds_mm"],
                    "margins_mm": margins,
                    "internal_margin_mm": _rounded(internal_pt * 25.4 / 72.0) if internal_pt is not None else None,
                    "rows": int(widget.settings.rows),
                    "columns": int(widget.settings.columns),
                    "scale_rows": [_rounded(value) for value in widget.settings.scaleRows],
                    "scale_columns": [_rounded(value) for value in widget.settings.scaleCols],
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

    categorical_graphs: list[dict[str, Any]] = []
    for graph in graphs:
        graph_path = str(graph["path"])
        children = [
            (widget_path, widget)
            for widget_path, widget in ordered_widgets
            if widget.parent is not None and str(widget.parent.path) == graph_path
        ]
        x_axis = next(
            (
                widget
                for _, widget in children
                if str(getattr(widget, "typename", "")) == "axis" and str(widget.name) == "x"
            ),
            None,
        )
        label_provider = next(
            (
                (widget_path, widget)
                for widget_path, widget in children
                if str(getattr(widget, "typename", "")) == "xy"
                and str(widget.name) == "category_axis_label_provider"
            ),
            None,
        )
        axis_mode = (
            str(x_axis.settings.setdict["mode"].val)
            if x_axis is not None and "mode" in x_axis.settings.setdict
            else ""
        )
        label_dataset = (
            str(label_provider[1].settings.setdict["labels"].val)
            if label_provider is not None and "labels" in label_provider[1].settings.setdict
            else ""
        )
        if axis_mode.casefold() != "labels" or not label_dataset:
            continue
        boxplot_path = next(
            (
                widget_path
                for widget_path, widget in children
                if str(getattr(widget, "typename", "")) == "boxplot"
            ),
            None,
        )
        categorical_graphs.append(
            {
                "graph_path": graph_path,
                "page": graph["page"],
                "axis_mode": axis_mode,
                "category_label_provider_path": label_provider[0],
                "category_label_dataset": label_dataset,
                "boxplot_path": boxplot_path,
                "spatial_identity_explicit": True,
            }
        )

    semantic_labels: list[dict[str, Any]] = []
    direct_label_texts_by_parent: dict[str, set[str]] = {}
    visible_keys_by_parent: dict[str, list[Any]] = {}
    for widget_path, widget in ordered_widgets:
        if widget_path not in state_by_path:
            continue
        widget_type = str(getattr(widget, "typename", ""))
        if widget_type in {"axis", "colorbar"}:
            label = str(widget.settings.setdict.get("label").val if "label" in widget.settings.setdict else "").strip()
            label_group = widget.settings.setdict.get("Label")
            if label and (label_group is None or not _setting_hidden(label_group)):
                semantic_labels.append({"path": widget_path, "role": "axis_label", "text": label})
        elif widget_type == "label":
            label = str(widget.settings.setdict.get("label").val if "label" in widget.settings.setdict else "").strip()
            text_group = widget.settings.setdict.get("Text")
            if label and (text_group is None or not _setting_hidden(text_group)):
                semantic_labels.append({"path": widget_path, "role": "free_label", "text": label})
                parent_path = str(widget.parent.path) if widget.parent is not None else ""
                direct_label_texts_by_parent.setdefault(parent_path, set()).add(label)
        elif widget_type == "key":
            if _setting_hidden(widget.settings):
                continue
            parent_path = str(widget.parent.path) if widget.parent is not None else ""
            visible_keys_by_parent.setdefault(parent_path, []).append(widget)
            title = str(widget.settings.setdict.get("title").val if "title" in widget.settings.setdict else "").strip()
            if title:
                semantic_labels.append({"path": widget_path, "role": "key_title", "text": title})

    series: list[dict[str, Any]] = []
    color_scales: list[dict[str, Any]] = []
    for widget_path, widget in ordered_widgets:
        state = state_by_path.get(widget_path)
        if state is None:
            continue
        if str(getattr(widget, "typename", "")) == "image" and "colorMap" in widget.settings.setdict:
            color_map = str(widget.settings.setdict["colorMap"].val)
            inverted = (
                bool(widget.settings.setdict.get("colorInvert").val)
                if "colorInvert" in widget.settings.setdict
                else False
            )
            entries = doc.evaluate.getColormap(color_map, inverted)
            control_colors = []
            for entry in entries:
                if len(entry) < 4 or float(entry[0]) < 0:
                    continue
                blue, green, red, alpha = (float(value) for value in entry[:4])
                control_colors.append(
                    {
                        "rgb": [_rounded(red / 255.0), _rounded(green / 255.0), _rounded(blue / 255.0)],
                        "alpha": _rounded(alpha / 255.0),
                    }
                )
            color_scales.append(
                {
                    "path": widget_path,
                    "page": state["page"],
                    "graph_path": str(widget.parent.path) if widget.parent is not None else "",
                    "name": color_map,
                    "inverted": inverted,
                    "control_colors": control_colors,
                }
            )
        if "PlotLine" not in widget.settings.setdict:
            continue
        helper = state["helper"]
        plot_line = widget.settings.setdict["PlotLine"]
        marker_setting = widget.settings.setdict.get("marker")
        marker = str(marker_setting.val if marker_setting is not None else "none")
        marker_fill = widget.settings.setdict.get("MarkerFill")
        marker_line = widget.settings.setdict.get("MarkerLine")
        plot_visible = not _setting_hidden(plot_line)
        marker_selected = marker.casefold() not in {"", "none"}
        marker_fill_visible = marker_selected and marker_fill is not None and not _setting_hidden(marker_fill)
        marker_line_visible = marker_selected and marker_line is not None and not _setting_hidden(marker_line)
        marker_visible = marker_fill_visible or marker_line_visible

        plot_color = _group_color(doc, plot_line, widget=widget, helper=helper)
        marker_fill_color = _group_color(doc, marker_fill, widget=widget, helper=helper)
        marker_line_color = _group_color(doc, marker_line, widget=widget, helper=helper)
        rendered_colors: list[dict[str, Any]] = []
        if plot_visible:
            rendered_colors.append({"role": "plot_line", "color": plot_color})
        if marker_fill_visible:
            rendered_colors.append({"role": "marker_fill", "color": marker_fill_color})
        if marker_line_visible:
            rendered_colors.append({"role": "marker_line", "color": marker_line_color})
        color = (
            plot_color
            if plot_visible
            else marker_fill_color
            if marker_fill_visible
            else marker_line_color
        )
        label = str(widget.settings.setdict.get("key").val if "key" in widget.settings.setdict else "").strip()
        parent_path = str(widget.parent.path) if widget.parent is not None else ""
        direct_labelled = bool(label) and label in direct_label_texts_by_parent.get(parent_path, set())
        series.append(
            {
                "path": widget_path,
                "page": state["page"],
                "graph_path": parent_path,
                "widget_type": str(getattr(widget, "typename", widget.__class__.__name__)),
                "label": label or str(widget.name),
                "color": color,
                "rendered_colors": rendered_colors,
                "plot_line_visible": plot_visible,
                "line_style": str(plot_line.setdict.get("style").val) if "style" in plot_line.setdict else None,
                "marker_visible": marker_visible,
                "marker_fill_visible": marker_fill_visible,
                "marker_line_visible": marker_line_visible,
                "marker": marker,
                "direct_labelled": direct_labelled,
            }
        )
        if label and visible_keys_by_parent.get(parent_path):
            semantic_labels.append({"path": widget_path, "role": "series_key", "text": label})

    stroke_items: list[dict[str, Any]] = []
    unsupported_strokes: list[dict[str, Any]] = []

    def collect_stroke_group(node_path: str, node: Any) -> None:
        if node_path.startswith("/StyleSheet"):
            return
        owner_info = _owner_widget(node_path, widgets_by_path)
        if owner_info is None:
            return
        owner_path, owner = owner_info
        state = state_by_path.get(owner_path)
        if state is None:
            return
        if "width" in node.setdict and "color" in node.setdict:
            item, unsupported = _line_group_item(
                path=node_path,
                node=node,
                owner_path=owner_path,
                owner=owner,
                helper=state["helper"],
                document=doc,
            )
            if item is not None:
                stroke_items.append(item)
            if unsupported is not None:
                unsupported_strokes.append(unsupported)
        if {"linewidth", "linestyle", "style", "hide"} <= set(node.setdict):
            active = not _setting_hidden(node) and str(node.setdict["style"].val).casefold() != "solid"
            width = node.setdict["linewidth"]
            width_pt = _distance_pt(width, state["helper"])
            item = {
                "path": node_path + "/linewidth",
                "owner_path": owner_path,
                "owner_type": str(getattr(owner, "typename", owner.__class__.__name__)),
                "setting_type": node.__class__.__name__,
                "source_kind": "fill_pattern_line",
                "active": active,
                "width_source": str(width.val),
                "width_pt": width_pt,
                "style": str(node.setdict["linestyle"].val),
                "color": _resolved_rgb(doc, node.setdict["color"].val, widget=owner, helper=state["helper"]),
            }
            stroke_items.append(item)
            if active and width_pt is None:
                unsupported_strokes.append(
                    {
                        "path": item["path"],
                        "reason": "active_fill_pattern_width_is_not_a_resolvable_physical_distance",
                        "value": str(width.val),
                    }
                )

    doc.walkNodes(collect_stroke_group, nodetypes=("settings",))

    def collect_multi_stroke(node_path: str, node: Any) -> None:
        if node_path.startswith("/StyleSheet") or str(getattr(node, "typename", "")) not in {
            "line-multi",
            "fill-multi",
        }:
            return
        owner_info = _owner_widget(node_path, widgets_by_path)
        if owner_info is None:
            return
        owner_path, owner = owner_info
        state = state_by_path.get(owner_path)
        if state is None:
            return
        if node.typename == "line-multi":
            for index, entry in enumerate(node.val):
                style, width, color, hide = entry
                active = not bool(hide)
                width_pt = _distance_value_pt(width, state["helper"])
                item = {
                    "path": f"{node_path}[{index}]",
                    "owner_path": owner_path,
                    "owner_type": str(getattr(owner, "typename", owner.__class__.__name__)),
                    "setting_type": node.__class__.__name__,
                    "source_kind": "line_multi",
                    "active": active,
                    "width_source": str(width),
                    "width_pt": width_pt,
                    "style": str(style),
                    "color": _resolved_rgb(doc, color, widget=owner, helper=state["helper"]),
                }
                stroke_items.append(item)
                if active and width_pt is None:
                    unsupported_strokes.append(
                        {
                            "path": item["path"],
                            "reason": "active_line_set_width_is_not_a_resolvable_physical_distance",
                            "value": str(width),
                        }
                    )
        else:
            for index, entry in enumerate(node.val):
                if len(entry) != 10 or bool(entry[2]) or str(entry[0]).casefold() == "solid":
                    continue
                width = entry[4]
                width_pt = _distance_value_pt(width, state["helper"])
                item = {
                    "path": f"{node_path}[{index}]",
                    "owner_path": owner_path,
                    "owner_type": str(getattr(owner, "typename", owner.__class__.__name__)),
                    "setting_type": node.__class__.__name__,
                    "source_kind": "fill_multi_pattern_line",
                    "active": True,
                    "width_source": str(width),
                    "width_pt": width_pt,
                    "style": str(entry[5]),
                    "color": _resolved_rgb(doc, entry[1], widget=owner, helper=state["helper"]),
                }
                stroke_items.append(item)
                if width_pt is None:
                    unsupported_strokes.append(
                        {
                            "path": item["path"],
                            "reason": "active_fill_set_width_is_not_a_resolvable_physical_distance",
                            "value": str(width),
                        }
                    )

    doc.walkNodes(collect_multi_stroke, nodetypes=("setting",))
    active_strokes = [item for item in stroke_items if item["active"]]
    return {
        "kind": "sciplot_veusz_document_audit",
        "version": 1,
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "page_count": len(pages),
        "pages": pages,
        "grids": grids,
        "graphs": graphs,
        "categorical_graphs": categorical_graphs,
        "auxiliaries": auxiliaries,
        "semantic_labels": semantic_labels,
        "series": series,
        "color_scales": color_scales,
        "stroke_inventory": {
            "coverage_complete": not unsupported_strokes,
            "active_count": len(active_strokes),
            "items": stroke_items,
            "unsupported": unsupported_strokes,
        },
    }


def audit_veusz_documents(paths: list[Path]) -> dict[str, Any]:
    """Load and audit exact VSZ documents through Veusz's own layout engine."""

    audits = [_audit_document(path) for path in paths]
    return {
        "kind": "sciplot_veusz_document_audit_set",
        "version": 1,
        "documents": audits,
        "coverage_complete": bool(audits)
        and all(bool(item["stroke_inventory"]["coverage_complete"]) for item in audits),
    }


__all__ = ["audit_veusz_documents"]
