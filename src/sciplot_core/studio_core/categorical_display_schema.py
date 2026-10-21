"""Closed presentation deltas over original ordinary categorical identities."""
from typing import Any

from sciplot_core.plot_document.schema import closed


def style_schema() -> dict[str, Any]:
    return closed({"color": {"type": "string", "pattern": "^#[a-fA-F0-9]{6}$"},
                   "marker": {"enum": ["circle", "square", "diamond", "triangle", "none"]},
                   "marker_fill_mode": {"enum": ["open", "filled"]}}, [])


def legend_schema() -> dict[str, Any]:
    return closed({"position": {"enum": ["upper_left", "upper_right", "lower_left", "lower_right"]},
                   "columns": {"type": "integer", "minimum": 1, "maximum": 12}})


def operation_schemas() -> list[dict[str, Any]]:
    text = {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "\\S"}
    style = style_schema()
    delta = {**style, "minProperties": 1}
    label = closed({"category_id": text, "expected_label": text, "label": text})
    item = closed({"series_id": text, "expected_style": style, "style": delta})
    legend = legend_schema()
    expected = closed({"columns": {"type": "integer", "minimum": 1, "maximum": 12},
                       "horzPosn": {"enum": ["left", "right", "centre", "manual"]},
                       "vertPosn": {"enum": ["top", "bottom", "centre", "manual"]}})
    scope = "Only ordinary rule_id=null categorical_binding given_values point_line or mean_sample_sd/mean_sample_sd_n bar; use current edit-context selectors."
    return [{**closed({"op": {"const": "set_category_display_labels"},
                    "changes": {"type": "array", "minItems": 1, "maxItems": 256, "items": label}}), "description": scope},
            {**closed({"op": {"const": "set_categorical_display_style"},
                       "changes": {"type": "array", "minItems": 1, "maxItems": 256, "items": item},
                       "legend": closed({**legend["properties"], "expected": expected})}, ["op"]),
             "anyOf": [{"required": ["changes"]}, {"required": ["legend"]}],
             "description": scope + " Bar supports color only; given point_line supports color/marker/fill and an existing native key corner/columns. Custom segmented legends have no layout edit here."}]


def overlay_schema() -> dict[str, Any]:
    return closed({"version": {"const": 1}, "aliases": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "\\S"}},
                   "styles": {"type": "object", "additionalProperties": style_schema()},
                   "legend": {"oneOf": [closed({}), legend_schema()]}})
