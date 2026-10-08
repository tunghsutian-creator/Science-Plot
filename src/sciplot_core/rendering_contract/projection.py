"""Project pinned house values into backend-neutral grammar style names."""
from typing import Any

from .registry import load_contract, require_binding

STYLE_PROPERTIES: dict[str, dict[str, str]] = {
    "line": {"line_width_pt": "line.width_pt", "line_opacity": "line.opacity", "line_join": "line.join"},
    "point": {"marker_size_pt": "marker.size_pt", "marker_opacity": "marker.opacity",
              "marker_line_width_pt": "marker.line_width_pt", "marker_thin_factor": "marker.thin_factor"},
    "axis": {"line_width_pt": "axis.line_width_pt", "tick_length_pt": "axis.major_tick_length_pt",
             "major_tick_width_pt": "axis.major_tick_width_pt", "minor_tick_width_pt": "axis.minor_tick_width_pt",
             "minor_tick_length_pt": "axis.minor_tick_length_pt", "label_padding_pt": "axis.label_padding_pt",
             "tick_label_padding_pt": "axis.x_tick_label_padding_pt", "minor_tick_count": "axis.linear_minor_tick_count",
             "tick_color": "axis.tick_color", "grid_visible": "axis.grid_visible",
             "minor_grid_visible": "axis.minor_grid_visible", "minor_ticks_visible": "axis.minor_ticks_visible"},
    "legend": {"font_size_pt": "legend.font_size_pt", "color": "legend.color", "key_length_mm": "legend.key_length_mm",
               "margin_size": "legend.margin_font_fraction", "frame_visible": "legend.frame_visible"},
    "text": {"align_h": "text.align_h", "align_v": "text.align_v"},
    "annotation": {"align_h": "text.align_h", "align_v": "text.align_v"},
    "rule": {"line_width_pt": "line.width_pt"},
    "errorbar": {"line_width_pt": "line.width_pt", "cap_width_pt": "errorbar.adapter_cap_width_pt"},
    "bar": {"border_width_pt": "bar.border_width_pt"},
    "band": {key: "band." + key for key in ("fill_color", "fill_opacity", "border_color", "border_width_pt")},
}
_FONT = {"font_family": "font.family", "font_size_pt": "font.size_pt", "font_weight": "font.weight",
         "color": "foreground.color"}


def resolved_style_defaults(kind: str, series_index: int = 0, *,
                            binding: dict[str, Any] | None = None) -> dict[str, Any]:
    """Only extracted values; unspecified channels are never invented here."""
    return {key: item["value"] for key, item in style_provenance(kind, series_index, binding=binding).items()}


def style_provenance(kind: str, series_index: int = 0, *,
                     binding: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    if series_index < 0:
        raise ValueError("Series style ordinal cannot be negative.")
    contract = require_binding(binding) if binding is not None else load_contract()
    properties = contract["properties"]
    keys = {**(_FONT if kind in {"axis", "legend", "text", "annotation"} else {}), **STYLE_PROPERTIES[kind]}
    result = {key: {**properties[path], "contract_property": path, "contract_id": contract["contract_id"],
                    "content_hash": contract["content_hash"]} for key, path in keys.items()}

    def select(field: str, path: str, *, index: int | None = None, translate: dict[Any, Any] | None = None) -> None:
        entry = properties[path]
        value = entry["value"]
        if index is not None:
            value = value[index % len(value)]
        if translate:
            value = translate[value]
        result[field] = {**entry, "value": value, "contract_property": path,
                         "contract_id": contract["contract_id"], "content_hash": contract["content_hash"]}

    if kind in {"line", "rule", "errorbar"}:
        select("line_color", "palette.colors", index=series_index)
    if kind in {"line", "rule"}:
        select("line_style", "line.style_sequence", index=series_index)
    if kind == "point":
        select("marker_color", "palette.colors", index=series_index)
        select("marker", "marker.sequence", index=series_index)
    if kind == "bar":
        color = properties["palette.colors"]["value"][series_index % len(properties["palette.colors"]["value"])]
        select("fill_color", "bar.fill_colors")
        result["fill_color"]["value"] = result["fill_color"]["value"][color]
        select("border_color", "bar.border_colors")
        result["border_color"]["value"] = result["border_color"]["value"][color]
        select("fill_opacity", "bar.fill_transparency")
        result["fill_opacity"]["value"] = (100 - result["fill_opacity"]["value"]) / 100
    if kind == "axis":
        select("tick_direction", "axis.outer_ticks", translate={True: "out", False: "in"})
        if properties["axis.x_tick_label_padding_pt"]["value"] != properties["axis.y_tick_label_padding_pt"]["value"]:
            raise ValueError("Axis-specific padding must be represented explicitly before this contract can compile.")
    return result


resolved_style_provenance = style_provenance
