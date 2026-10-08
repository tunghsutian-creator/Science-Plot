"""Closed FigureSpec v2 grammar. No backend object, artifact or coordinate paths."""
from typing import Any

from sciplot_core.plot_document.schema import IDENTIFIER, closed

from sciplot_core.rendering_contract import binding_schema
from .styles import COLOR, MARK_TYPES, NUMBER, POSITIVE, scope_schema, style_schema

def rendering_binding_schema(contract_id: str) -> dict[str, Any]:
    result = binding_schema()
    result["properties"]["contract_id"] = {"const": contract_id}
    return result


TEXT = {"type": "string", "maxLength": 4096}
BOOL = {"type": "boolean"}
PAIR = {"type": "array", "minItems": 2, "maxItems": 2, "items": NUMBER}


def scale_schema() -> dict[str, Any]:
    return closed({"id": IDENTIFIER, "dimension": {"enum": ["x", "y"]},
        "transform": {"enum": ["linear", "log", "symlog"]}, "domain": PAIR,
        "unit": TEXT, "quantity": {"type": "string", "minLength": 1, "maxLength": 128},
        "direction": {"enum": ["ascending", "descending"]}})


def mark_schema(*, resolved: bool = False) -> dict[str, Any]:
    branches = []
    for kind in MARK_TYPES:
        fields: dict[str, Any] = {"id": IDENTIFIER, "type": {"const": kind}, "style": style_schema(kind, resolved=resolved)}
        if kind == "bar":
            fields.update(baseline=NUMBER, width_data=POSITIVE)
        elif kind == "rule":
            fields["orientation"] = {"enum": ["vertical", "horizontal"]}
        elif kind == "text":
            fields["text"] = {"type": "string", "minLength": 1, "maxLength": 500}
        branches.append(closed(fields))
    return {"oneOf": branches}


def axis_schema(*, resolved: bool = False) -> dict[str, Any]:
    fields: dict[str, Any] = {"id": IDENTIFIER, "scale_id": IDENTIFIER,
        "side": {"enum": ["bottom", "top", "left", "right"]}, "label": TEXT,
        "visible": BOOL, "label_visible": BOOL, "ticks": {"type": "array", "items": NUMBER, "uniqueItems": True},
        "style": style_schema("axis", resolved=resolved),
        "tick_labels": {"type": "array", "minItems": 1, "items": TEXT},
        "label_runs": {"type": "array", "minItems": 1, "items": closed({
            "text": {"type": "string", "minLength": 1, "maxLength": 4096}, "italic": BOOL})}}
    if resolved:
        fields.update(view_id=IDENTIFIER, tick_labels={"type": "array", "items": TEXT},
            tick_positions_mm={"type": "array", "items": PAIR}, label_position_mm=PAIR,
            label_angle={"enum": [0, 90]}, tick_alignment={"enum": ["left", "center", "right"]}, decorations_visible=BOOL)
    if resolved:
        fields.update(text_layout={"enum": ["physical-anchors", "axis-metric-flow"]},
            minor_ticks={"type": "array", "items": NUMBER}, tick_notation={"enum": ["general", "power10", "labels"]})
    return closed(fields, [key for key in fields if key not in {"text_layout", "minor_ticks", "tick_notation", "tick_positions_mm", "label_position_mm", "label_angle", "tick_alignment", "tick_labels", "label_runs"}])


def layer_schema(*, resolved: bool = False) -> dict[str, Any]:
    fields = {"id": IDENTIFIER, "dataset_id": IDENTIFIER,
        "mappings": closed({name: IDENTIFIER for name in ("x", "y", "y_low", "y_high")}, ["x", "y"]),
        "mapping_semantics": closed({"x": TEXT, "y": TEXT}), "x_scale": IDENTIFIER, "y_scale": IDENTIFIER,
        "marks": {"type": "array", "minItems": 1, "items": mark_schema(resolved=resolved)},
        "role": {"type": "string", "minLength": 1}, "label": TEXT,
        "legend": closed({"visible": BOOL, "label": TEXT}), "z_order": {"type": "integer"}}
    if not resolved:
        fields["style"] = scope_schema(layer=True)
    return closed(fields)


def guide_schema(*, resolved: bool = False) -> dict[str, Any]:
    fields: dict[str, Any] = {"id": IDENTIFIER, "type": {"const": "legend"}, "scope": {"enum": ["figure", "view"]},
        "view_id": IDENTIFIER, "visible": BOOL, "location": {"enum": ["top-right", "top-left", "bottom-right", "bottom-left", "top", "bottom", "left", "right", "inside-best"]},
        "columns": {"type": "integer", "minimum": 1, "maximum": 32}, "style": style_schema("legend", resolved=resolved)}
    required = [key for key in fields if key != "view_id"]
    if not resolved:
        fields.update(layer_ids={"type": "array", "uniqueItems": True, "items": IDENTIFIER},
            order={"type": "array", "uniqueItems": True, "items": IDENTIFIER},
            labels={"type": "object", "propertyNames": IDENTIFIER, "additionalProperties": TEXT})
        required += ["layer_ids", "order", "labels"]
    else:
        rect = {"type": "array", "minItems": 4, "maxItems": 4, "items": NUMBER}
        fields.update(rect_mm=rect, entries={"type": "array", "items": closed({"layer_id": IDENTIFIER,
            "label": TEXT, "marks": {"type": "array", "minItems": 1, "items": mark_schema(resolved=True)},
            "symbol_mm": rect, "label_mm": PAIR}, ["layer_id", "label", "marks"])})
        required += ["entries"]
    if resolved:
        fields["text_layout"] = {"enum": ["physical-anchors", "legend-metric-flow"]}
        fields["position_fraction"] = PAIR
    return closed(fields, required)


def annotation_schema(*, resolved: bool = False) -> dict[str, Any]:
    common = {"id": IDENTIFIER, "x": NUMBER, "y": NUMBER, "text": {"type": "string", "minLength": 1, "maxLength": 500},
        "visible": BOOL, "style": style_schema("annotation", resolved=resolved)}
    if resolved:
        common["position_mm"] = PAIR
    branches = []
    for space in ("data", "view", "figure"):
        fields = {**common, "space": {"const": space}}
        if space in {"data", "view"}:
            fields["view_id"] = IDENTIFIER
        if space == "data":
            fields.update(x_scale=IDENTIFIER, y_scale=IDENTIFIER)
        branches.append(closed(fields))
    return {"oneOf": branches}


def composition_schema() -> dict[str, Any]:
    integer = {"type": "integer", "minimum": 1, "maximum": 16}
    resolve = closed({"id": IDENTIFIER, "views": {"type": "array", "minItems": 2, "uniqueItems": True, "items": IDENTIFIER},
        **{axis: {"enum": ["shared", "independent"]} for axis in ("x", "y", "legend")}})
    cell = closed({"view_id": IDENTIFIER, "row": {"type": "integer", "minimum": 0},
        "column": {"type": "integer", "minimum": 0}, "row_span": {"const": 1}, "column_span": {"const": 1}})
    return closed({"kind": {"enum": ["single", "hconcat", "vconcat", "grid"]}, "rows": integer, "columns": integer,
        "cells": {"type": "array", "minItems": 1, "items": cell},
        "column_weights": {"type": "array", "minItems": 1, "items": POSITIVE},
        "row_weights": {"type": "array", "minItems": 1, "items": POSITIVE},
        "resolve": {"type": "array", "items": resolve}})


def figure_layout_schema() -> dict[str, Any]:
    nonnegative = {"type": "number", "minimum": 0}
    return closed({"width_mm": POSITIVE, "height_mm": {"oneOf": [POSITIVE, {"const": "auto"}]},
        "gap_x_mm": nonnegative, "gap_y_mm": nonnegative,
        "outer_margins_mm": closed({name: nonnegative for name in ("left", "right", "top", "bottom")}),
        "panel_min_height_mm": POSITIVE, "panel_label_height_mm": nonnegative}, [])


def figure_spec_schema() -> dict[str, Any]:
    view = closed({"id": IDENTIFIER, "panel_label": {"type": ["string", "null"], "maxLength": 16},
        "style": scope_schema(), "axes": {"type": "array", "items": axis_schema()},
        "layers": {"type": "array", "minItems": 1, "items": layer_schema()}})
    theme = closed({"project": scope_schema(), "figure": scope_schema(), "background_color": COLOR}, ["project", "figure"])
    fields = {"kind": {"const": "sciplot_figure_spec"}, "schema_version": {"const": 2}, "id": IDENTIFIER,
        "scales": {"type": "array", "minItems": 2, "items": scale_schema()},
        "views": {"type": "array", "minItems": 1, "maxItems": 64, "items": view},
        "composition": composition_schema(), "layout": figure_layout_schema(), "theme": theme,
        "guides": {"type": "array", "items": guide_schema()}, "annotations": {"type": "array", "items": annotation_schema()},
        "rendering_contract": rendering_binding_schema("sciplot-house-style-v1"),
        "composition_policy": rendering_binding_schema("sciplot-figure-composition-v1")}
    return closed(fields, [key for key in fields if key not in {"rendering_contract", "composition_policy"}])
