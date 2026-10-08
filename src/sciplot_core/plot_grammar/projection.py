"""Lossless scientific/presentation projections for the existing document seals."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.errors import fail

from .validation import validate_figure_spec

_SCI_LAYER = ("id", "dataset_id", "mappings", "mapping_semantics", "x_scale", "y_scale", "role")
_PRES_LAYER = ("id", "label", "legend", "z_order", "style")


def _take(value: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: deepcopy(value[name]) for name in names if name in value}


def split_figure_spec(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Data anchors/scales/geometry semantics seal as science; layout/style seal separately."""
    spec = validate_figure_spec(value)
    science: dict[str, Any] = {"kind": "sciplot_figure_science", "schema_version": 2,
        "id": spec["id"], "scales": spec["scales"], "views": [], "data_annotations": []}
    presentation: dict[str, Any] = {"kind": "sciplot_figure_presentation", "schema_version": 2,
        **_take(spec, ("id", "composition", "layout", "theme", "guides", "rendering_contract", "composition_policy")), "views": [], "annotations": []}
    for view in spec["views"]:
        scientific_view: dict[str, Any] = {"id": view["id"], "layers": []}
        visual_view = {**_take(view, ("id", "panel_label", "style", "axes")), "layers": []}
        for layer in view["layers"]:
            scientific_layer = {**_take(layer, _SCI_LAYER), "marks": []}
            visual_layer = {**_take(layer, _PRES_LAYER), "marks": []}
            for mark in layer["marks"]:
                scientific_layer["marks"].append(_take(mark, ("id", "type", "baseline", "width_data", "orientation")))
                visual_layer["marks"].append(_take(mark, ("id", "style", "text")))
            scientific_view["layers"].append(scientific_layer)
            visual_view["layers"].append(visual_layer)
        science["views"].append(scientific_view)
        presentation["views"].append(visual_view)
    for annotation in spec["annotations"]:
        if annotation["space"] == "data":
            science["data_annotations"].append(_take(annotation, ("id", "space", "view_id", "x_scale", "y_scale", "x", "y")))
            presentation["annotations"].append(_take(annotation, ("id", "space", "text", "visible", "style")))
        else:
            presentation["annotations"].append(annotation)
    return science, presentation


def _index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in items}


def merge_figure_spec(science: Any, presentation: Any) -> dict[str, Any]:
    """Rejoin and prove the projections are exact, including unknown-field rejection."""
    try:
        if (science["kind"] != "sciplot_figure_science" or presentation["kind"] != "sciplot_figure_presentation"
                or science["schema_version"] != 2 or presentation["schema_version"] != 2 or science["id"] != presentation["id"]):
            raise ValueError("projection identity")
        result: dict[str, Any] = {"kind": "sciplot_figure_spec", "schema_version": 2,
            **_take(presentation, ("id", "composition", "layout", "theme", "guides", "rendering_contract", "composition_policy")),
            "scales": deepcopy(science["scales"]), "views": [], "annotations": []}
        scientific_views = _index(science["views"])
        for visual_view in presentation["views"]:
            scientific_view = scientific_views[visual_view["id"]]
            view = {**_take(visual_view, ("id", "panel_label", "style", "axes")), "layers": []}
            scientific_layers = _index(scientific_view["layers"])
            for visual_layer in visual_view["layers"]:
                scientific_layer = scientific_layers[visual_layer["id"]]
                layer = {**_take(scientific_layer, _SCI_LAYER), **_take(visual_layer, _PRES_LAYER), "marks": []}
                scientific_marks = _index(scientific_layer["marks"])
                for mark in visual_layer["marks"]:
                    layer["marks"].append({**deepcopy(scientific_marks[mark["id"]]), **deepcopy(mark)})
                view["layers"].append(layer)
            result["views"].append(view)
        anchors = _index(science["data_annotations"])
        for annotation in presentation["annotations"]:
            result["annotations"].append({**deepcopy(anchors.get(annotation["id"], {})), **deepcopy(annotation)})
        checked = validate_figure_spec(result)
        if split_figure_spec(checked) != (science, presentation):
            raise ValueError("projection fields or order")
        return checked
    except (KeyError, TypeError, ValueError) as exc:
        fail("figure_projection_invalid", "Scientific and presentation FigureSpec projections must reconstruct exactly.",
            "/figure_spec", "lossless_projection", detail=str(exc)[:160])
