"""Resolve explicit display selectors into the existing semantic patch owner."""

from collections.abc import Callable
from typing import Any

from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure


def compile_series_edits(document: dict[str, Any], options: dict[str, Any],
                         set_value: Callable[[str, str, Any], None],
                         error_factory: Callable[..., EngineError]) -> None:
    if not set(options) & {"series_labels", "series_visibility"}:
        return
    if document.get("plot_type") == "ManagedPlot" and is_figure(document):
        candidates = [(layer["id"], {"label": layer["label"], "alias": layer["legend"]["label"],
                       "source_label": document["scientific"]["mappings"][layer["id"]].get("sample"),
                       "capabilities": {"series.display_label": {}, "series.visible": {}}})
                      for view in figure_spec(document)["views"] for layer in view["layers"]]
    else:
        candidates = [(target, {**obj, "alias": obj["properties"].get("series.display_label")})
                      for target, obj in document["presentation"]["objects"].items() if obj["kind"] == "series"]
    for field, prop in (("series_labels", "series.display_label"), ("series_visibility", "series.visible")):
        touched = set()
        for selector, value in options.get(field, {}).items():
            exact = [(target, obj) for target, obj in candidates if target == selector]
            matches = exact or [(target, obj) for target, obj in candidates if selector in {obj["label"], obj["alias"], obj.get("source_label")}]
            if len(matches) != 1 or prop not in matches[0][1]["capabilities"]:
                raise error_factory("Choose one advertised source series by exact semantic ID or unique label.", code="common_edit_unknown_target", selector=selector, property=prop)
            target = matches[0][0]
            if target in touched:
                raise error_factory("Multiple selectors identify the same series property.", target=target, property=prop)
            touched.add(target)
            set_value(target, prop, value)
