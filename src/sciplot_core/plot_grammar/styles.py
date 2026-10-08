"""Explicit semantic defaults and scoped, deterministic style inheritance."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.schema import closed

NUMBER = {"type": "number"}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
NONNEGATIVE = {"type": "number", "minimum": 0}
COLOR = {"type": "string", "pattern": "^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{12})$"}
FONT = {"font_family": {"type": "string", "minLength": 1}, "font_size_pt": POSITIVE, "color": COLOR}
LINE = {"line_color": COLOR, "line_width_pt": POSITIVE, "line_style": {"enum": ["solid", "dash", "dot"]},
        "line_join": {"enum": ["bevel", "round"]}}
FILL = {"fill_color": COLOR, "fill_opacity": {"type": "number", "minimum": 0, "maximum": 1},
        "border_color": COLOR, "border_width_pt": NONNEGATIVE}
STYLE_FIELDS: dict[str, dict[str, Any]] = {
    "line": LINE,
    "point": {"marker": {"enum": ["circle", "square", "diamond", "triangle", "cross", "plus"]},
              "marker_size_pt": POSITIVE, "marker_color": COLOR, "marker_line_width_pt": NONNEGATIVE},
    "bar": FILL, "band": FILL,
    "errorbar": {"line_color": COLOR, "line_width_pt": POSITIVE, "cap_width_pt": NONNEGATIVE},
    "rule": {key: value for key, value in LINE.items() if key != "line_join"},
    "text": {**FONT, "align_h": {"enum": ["left", "center", "right"]},
             "align_v": {"enum": ["top", "center", "bottom"]}},
    "axis": {**FONT, "line_width_pt": POSITIVE, "tick_length_pt": NONNEGATIVE,
             "tick_direction": {"enum": ["in", "out"]}},
    "legend": FONT,
    "annotation": {**FONT, "align_h": {"enum": ["left", "center", "right"]},
                   "align_v": {"enum": ["top", "center", "bottom"]}},
}
_BASE_FONT = {"font_family": "Arial", "font_size_pt": 8.0, "color": "#000000"}
_BASE_LINE = {"line_color": "#000000", "line_width_pt": 0.7, "line_style": "solid", "line_join": "round"}
_BASE_FILL = {"fill_color": "#4477aa", "fill_opacity": 1.0, "border_color": "#000000", "border_width_pt": 0.7}
DEFAULTS: dict[str, dict[str, Any]] = {
    "line": _BASE_LINE,
    "point": {"marker": "circle", "marker_size_pt": 3.0, "marker_color": "#000000", "marker_line_width_pt": 0.5},
    "bar": _BASE_FILL, "band": {**_BASE_FILL, "fill_opacity": 0.25},
    "errorbar": {"line_color": "#000000", "line_width_pt": 0.7, "cap_width_pt": 4.0},
    "rule": {key: value for key, value in _BASE_LINE.items() if key != "line_join"},
    "text": {**_BASE_FONT, "align_h": "center", "align_v": "center"},
    "axis": {**_BASE_FONT, "line_width_pt": 0.7, "tick_length_pt": 3.0, "tick_direction": "out"},
    "legend": _BASE_FONT,
    "annotation": {**_BASE_FONT, "align_h": "left", "align_v": "center"},
}
MARK_TYPES = ("line", "point", "bar", "errorbar", "band", "rule", "text")


def style_schema(kind: str, *, resolved: bool = False) -> dict[str, Any]:
    # Historical IR keeps its exact schema interpretation; contract additions
    # are optional here and populated completely by the bound compiler.
    additions: dict[str, dict[str, Any]] = {
        "bar": {"baseline_border_visible": {"type": "boolean"}},
        "line": {"line_opacity": {"type": "number", "minimum": 0, "maximum": 1}},
        "point": {"marker_opacity": {"type": "number", "minimum": 0, "maximum": 1},
                  "marker_thin_factor": {"type": "integer", "minimum": 1}},
        "axis": {"major_tick_width_pt": POSITIVE, "minor_tick_width_pt": POSITIVE,
                 "tick_color": COLOR, "tick_notation": {"enum": ["general", "power10"]}, "grid_visible": {"type": "boolean"},
                 "minor_grid_visible": {"type": "boolean"}, "minor_ticks_visible": {"type": "boolean"},
                 "minor_tick_length_pt": NONNEGATIVE, "label_padding_pt": NONNEGATIVE,
                 "tick_label_padding_pt": NONNEGATIVE, "minor_tick_count": {"type": "integer", "minimum": 0}},
        "legend": {"key_length_mm": POSITIVE, "margin_size": NONNEGATIVE, "frame_visible": {"type": "boolean"}},
    }
    fields = {**STYLE_FIELDS[kind], **additions.get(kind, {})}
    if kind in {"axis", "legend", "annotation", "text"}:
        fields["font_weight"] = {"enum": ["normal", "bold"]}
    return closed(fields, list(STYLE_FIELDS[kind]) if resolved else [])


def scope_schema(*, layer: bool = False) -> dict[str, Any]:
    kinds = MARK_TYPES if layer else tuple(STYLE_FIELDS)
    fields = {kind: style_schema(kind) for kind in kinds}
    return closed(fields, [])


def resolve_style(kind: str, scopes: list[dict[str, Any]], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(DEFAULTS[kind])
    for scope in scopes:
        result.update(deepcopy(scope.get(kind, {})))
    result.update(deepcopy(override))
    for key, value in result.items():
        if "color" in key:
            result[key] = value.lower()
    return result
