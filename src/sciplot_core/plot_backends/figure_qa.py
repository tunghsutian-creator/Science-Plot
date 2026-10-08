"""Publication QA from the actual native text renderer, with no global residue."""

from importlib import import_module
from typing import Any

from sciplot_core.plot_backends.figure_plan import drawing_plan
from sciplot_core.plot_backends.figure_marks import fraction, coordinates


def native_publication_qa(ir: dict[str, Any], loaded: Any) -> dict[str, Any]:
    from sciplot_core.plot_layout import native_publication_qa as check

    nodes = drawing_plan(ir)
    metadata = {node["path"]: node for node in nodes if "semantic_id" in node}
    observations: list[dict[str, Any]] = []
    utils: Any = import_module("veusz.utils")
    original = utils.Renderer
    dpi = 150

    def factory(*args: Any, **kwargs: Any) -> Any:
        renderer = original(*args, **kwargs)
        painter = args[0]
        widget = getattr(painter, "widget", None)
        path = widget.path if widget is not None else ""
        meta = metadata.get(path)
        render = renderer.render

        def measured() -> Any:
            result = render()
            if meta is not None:
                bounds = renderer.getBounds()
                factor = 25.4 / dpi
                record: dict[str, Any] = {key: meta[key] for key in ("semantic_id", "role", "view_id", "allowed_bounds_mm") if key in meta}
                record["bounds_mm"] = [float(bounds[0]) * factor, float(bounds[1]) * factor,
                                       float(bounds[2] - bounds[0]) * factor, float(bounds[3] - bounds[1]) * factor]
                observations.append(record)
            return result
        renderer.render = measured
        return renderer

    try:
        utils.Renderer = factory
        helper = import_module("veusz.document").PaintHelper(loaded, loaded.pageSize(0, dpi=(dpi, dpi), integer=False), dpi=(dpi, dpi))
        loaded.paintTo(helper, 0)
    finally:
        utils.Renderer = original
    expected_ids = sorted({node["semantic_id"] for node in nodes if node["type"] in {"label", "axis", "key"} and "semantic_id" in node})
    scales = {scale["id"]: scale for scale in ir["scales"]}
    points = []
    for view in ir["views"]:
        panel = next(p for p in ir["layout"]["panels"] if p["view_id"] == view["id"])
        x0, y0, width, height = panel["plot_mm"]
        for layer in view["layers"]:
            data = coordinates(ir, layer)
            for x, y in zip(data["x"], data["y"], strict=True):
                if x is not None and y is not None:
                    points.append({"view_id": view["id"], "x_mm": x0 + fraction(x, scales[layer["x_scale"]]) * width,
                                   "y_mm": y0 + (1 - fraction(y, scales[layer["y_scale"]])) * height})
    result: dict[str, Any] = check(ir["layout"], observations, expected_text_ids=expected_ids, data_points=points)
    result["observations"] = observations
    result["renderer"] = "veusz.native-text-bounds"
    result["dpi"] = dpi
    return result
