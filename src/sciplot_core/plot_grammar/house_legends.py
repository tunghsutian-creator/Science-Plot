"""Resolve the retained semantic inside-best policy before backend compilation."""
from typing import Any

from sciplot_core.plot_document.errors import fail
from .house import require_legacy_semantics


def resolve_house_legends(spec: dict[str, Any], guides: list[dict[str, Any]], datasets: dict[str, Any],
                          layout: dict[str, Any]) -> None:
    require_legacy_semantics(spec["rendering_contract"])
    from sciplot_core.studio_render.legend_placement import _auto_inside_legend_placement, manual_anchor_fraction
    from sciplot_core.studio_render.models import StudioSeries

    views = {view["id"]: view for view in spec["views"]}
    scales = {scale["id"]: scale for scale in spec["scales"]}
    for guide in guides:
        if guide["scope"] != "view":
            continue
        if guide["location"] == "inside-best":
            view = views[guide["view_id"]]
            layers = {layer["id"]: layer for layer in view["layers"]}
            selected = [layers[entry["layer_id"]] for entry in guide["entries"]]
            if not selected:
                guide["location"] = "bottom-right"
                continue
            if any((layer["x_scale"], layer["y_scale"]) != (selected[0]["x_scale"], selected[0]["y_scale"])
                   for layer in selected):
                fail("figure_legend_auto_scale_conflict", "Inside-best requires one scale pair; provide a corner for multiple scales.",
                     "/guides/location", "placement_scale_pair")
            options: dict[str, Any] = {"size": f"{layout['width_mm']:g}x{layout['height_mm']:g}"}
            for dimension in ("x", "y"):
                scale = scales[selected[0][dimension + "_scale"]]
                options.update({dimension + "_min": scale["domain"][0], dimension + "_max": scale["domain"][1],
                                dimension + "scale": scale["transform"], "reverse_" + dimension: scale["direction"] == "descending"})
            series = []
            for entry, layer in zip(guide["entries"], selected, strict=True):
                columns = datasets[layer["dataset_id"]]["columns"]
                pairs = [(x, y) for x, y in zip(columns[layer["mappings"]["x"]]["values"],
                    columns[layer["mappings"]["y"]]["values"], strict=True) if x is not None and y is not None]
                series.append(StudioSeries(entry["label"], "x", "y", tuple(x for x, _ in pairs), tuple(y for _, y in pairs), "#000000"))
            placement = _auto_inside_legend_placement(series, options, template_id="curve")
            guide["position_fraction"] = manual_anchor_fraction(placement)
            guide["location"] = {"upper_right": "top-right", "upper_left": "top-left",
                                 "lower_right": "bottom-right", "lower_left": "bottom-left"}[placement["position"]]
        if all(all(mark["type"] in {"line", "point"} for mark in entry["marks"])
               and len({mark["type"] for mark in entry["marks"]}) == len(entry["marks"])
               for entry in guide["entries"]):
            guide["text_layout"] = "legend-metric-flow"
