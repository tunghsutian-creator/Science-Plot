"""Collect resolvable physical stroke widths from Veusz settings."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_audit.colors import _resolved_rgb
from sciplot_core.veusz_audit.measurements import (
    _distance_pt,
    _distance_value_pt,
    _setting_hidden,
)
from sciplot_core.veusz_audit.widget_tree import _owner_widget


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
        active = (
            active
            and marker is not None
            and str(marker.val).casefold() not in {"", "none"}
        )
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


def collect_stroke_inventory(
    doc: Any,
    widgets_by_path: dict[str, Any],
    state_by_path: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
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
            active = (
                not _setting_hidden(node)
                and str(node.setdict["style"].val).casefold() != "solid"
            )
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
                "color": _resolved_rgb(
                    doc, node.setdict["color"].val, widget=owner, helper=state["helper"]
                ),
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
        if node_path.startswith("/StyleSheet") or str(
            getattr(node, "typename", "")
        ) not in {
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
                    "owner_type": str(
                        getattr(owner, "typename", owner.__class__.__name__)
                    ),
                    "setting_type": node.__class__.__name__,
                    "source_kind": "line_multi",
                    "active": active,
                    "width_source": str(width),
                    "width_pt": width_pt,
                    "style": str(style),
                    "color": _resolved_rgb(
                        doc, color, widget=owner, helper=state["helper"]
                    ),
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
                if (
                    len(entry) != 10
                    or bool(entry[2])
                    or str(entry[0]).casefold() == "solid"
                ):
                    continue
                width = entry[4]
                width_pt = _distance_value_pt(width, state["helper"])
                item = {
                    "path": f"{node_path}[{index}]",
                    "owner_path": owner_path,
                    "owner_type": str(
                        getattr(owner, "typename", owner.__class__.__name__)
                    ),
                    "setting_type": node.__class__.__name__,
                    "source_kind": "fill_multi_pattern_line",
                    "active": True,
                    "width_source": str(width),
                    "width_pt": width_pt,
                    "style": str(entry[5]),
                    "color": _resolved_rgb(
                        doc, entry[1], widget=owner, helper=state["helper"]
                    ),
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
    return stroke_items, unsupported_strokes, active_strokes
