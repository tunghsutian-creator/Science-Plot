"""Resolve the retained semantic inside-best policy before backend compilation."""
from typing import Any

from sciplot_core.plot_document.errors import fail
from .house import StyleResolver, require_legacy_semantics


def resolve_house_legends(spec: dict[str, Any], guides: list[dict[str, Any]], datasets: dict[str, Any],
                          layout: dict[str, Any], resolver: StyleResolver) -> None:
    if not resolver.current:
        require_legacy_semantics(spec["rendering_contract"])

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
            curves = []
            for entry, layer in zip(guide["entries"], selected, strict=True):
                if "y" in layer["mappings"]:
                    columns = datasets[layer["dataset_id"]]["columns"]
                    pairs = [(x, y) for x, y in zip(columns[layer["mappings"]["x"]]["values"],
                        columns[layer["mappings"]["y"]]["values"], strict=True) if x is not None and y is not None]
                else:
                    from .mark_geometry import layer_geometry

                    pairs = [point for mark in layer_geometry(layer, datasets) for point in mark.points]
                curves.append((entry["label"], pairs))
            placement, anchor = _placement(curves, options, resolver)
            guide["position_fraction"] = anchor
            guide["location"] = {"upper_right": "top-right", "upper_left": "top-left",
                                 "lower_right": "bottom-right", "lower_left": "bottom-left"}[placement["position"]]
        if all(all(mark["type"] in {"line", "point"} for mark in entry["marks"])
               and len({mark["type"] for mark in entry["marks"]}) == len(entry["marks"])
               for entry in guide["entries"]):
            guide["text_layout"] = "legend-metric-flow"

def _placement(curves: list[tuple[str, list[tuple[float, float]]]], options: dict[str, Any],
               resolver: StyleResolver) -> tuple[dict[str, Any], list[float]]:
    if resolver.current:
        from sciplot_core.rendering_contract import contract_value
        from sciplot_core.rendering_contract.current_inside_best import (
            anchor_fraction, inside_best_geometry, score_inside_best,
        )

        binding = resolver.binding
        geometry = inside_best_geometry(curves, options,
            margins_mm={side: float(contract_value("frame." + side + "_mm", binding))
                        for side in ("left", "right", "top", "bottom")},
            font_size_pt=float(contract_value("legend.font_size_pt", binding)),
            key_length_mm=float(contract_value("legend.key_length_mm", binding)),
            frame_visible=bool(contract_value("legend.frame_visible", binding)))
        if geometry is not None:
            samples, footprint = geometry
            placement = score_inside_best(samples, footprint,
                edge_padding_mm=float(contract_value("legend.edge_padding_mm", binding)),
                clearance_mm=float(contract_value("legend.curve_clearance_mm", binding)))
            resolver.trace["rendering:inside_best_binding"] = {
                "algorithm_id": contract_value("legend.inside_best_algorithm", binding),
                "rendering_contract": binding,
            }
            return placement, anchor_fraction(placement)
        if "rendering:legacy_legend_binding" not in resolver.trace:
            from sciplot_core.rendering_contract import contract_binding

            resolver.trace["rendering:legacy_legend_binding"] = require_legacy_semantics(contract_binding())

    from sciplot_core.rendering_contract.legacy_algorithms import StudioSeries, auto_inside_legend_placement, manual_anchor_fraction

    series = [StudioSeries(label, "x", "y", tuple(x for x, _ in pairs), tuple(y for _, y in pairs), "#000000")
              for label, pairs in curves]
    placement = auto_inside_legend_placement(series, options, template_id="curve")
    return placement, manual_anchor_fraction(placement)
