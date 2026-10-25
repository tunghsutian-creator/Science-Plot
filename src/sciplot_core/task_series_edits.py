"""Resolve explicit display selectors into the existing semantic patch owner."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure


def series_candidates(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Project source identities and current display aliases in document order."""
    if document.get("plot_type") == "ManagedPlot" and is_figure(document):
        return [(layer["id"], {"label": layer["label"], "alias": layer["legend"]["label"],
                       "source_label": document["scientific"]["mappings"][layer["id"]].get("sample"),
                       "capabilities": {"series.display_label": {}, "series.visible": {}}})
                      for view in figure_spec(document)["views"] for layer in view["layers"]]
    return [(target, {**deepcopy(obj), "alias": obj["properties"].get("series.display_label")})
            for target, obj in document["presentation"]["objects"].items() if obj["kind"] == "series"]


def resolve_series_targets(document: dict[str, Any], selectors: list[str] | None,
                           error_factory: Callable[..., EngineError]) -> list[tuple[str, dict[str, Any]]]:
    """Stable IDs take precedence; labels must identify exactly one source series."""
    candidates = series_candidates(document)
    if selectors is None:
        return candidates
    selected = []
    touched = set()
    for selector in selectors:
        exact = [(target, obj) for target, obj in candidates if target == selector]
        matches = exact or [(target, obj) for target, obj in candidates
                           if selector in {obj["label"], obj["alias"], obj.get("source_label")}]
        if len(matches) != 1:
            raise error_factory("Choose one source series by exact semantic ID or unique label.",
                                failure="ambiguous", selector=selector, allowed=[target for target, _ in candidates][:32])
        target, obj = matches[0]
        if target in touched:
            raise error_factory("Multiple selectors identify the same source series.",
                                failure="duplicate", selector=selector, target=target)
        touched.add(target)
        selected.append((target, obj))
    return selected


def compile_series_edits(document: dict[str, Any], options: dict[str, Any],
                         set_value: Callable[[str, str, Any], None],
                         error_factory: Callable[..., EngineError]) -> None:
    for field, prop in (("series_labels", "series.display_label"), ("series_visibility", "series.visible")):
        values = options.get(field, {})
        if not values:
            continue

        def invalid(message: str, *, failure: str, selector: str,
                    property_name: str = prop, **details: Any) -> EngineError:
            if failure == "duplicate":
                return error_factory(message, target=details["target"], property=property_name)
            return error_factory(message, code="common_edit_unknown_target", selector=selector, property=property_name)

        selected = resolve_series_targets(document, list(values), invalid)
        for (selector, value), (target, obj) in zip(values.items(), selected, strict=True):
            if prop not in obj["capabilities"]:
                raise error_factory("The selected source series does not advertise this property.",
                                    code="common_edit_unknown_target", selector=selector, property=prop)
            set_value(target, prop, value)


def compile_series_style(document: dict[str, Any], *, samples: list[str] | None,
                         all_samples: bool, style: dict[str, str]) -> list[dict[str, Any]]:
    """Lower the existing width/color shortcut into one versioned semantic patch."""
    def invalid(message: str, **details: Any) -> EngineError:
        details.pop("failure", None)
        if "selector" in details:
            details["label"] = details.pop("selector")
        return EngineError("document_ambiguous_style_target", message, action="correct_style_target", **details)

    if all_samples == (samples is not None) or not style or set(style) - {"width", "color"}:
        raise invalid("Choose explicit samples or all samples, and width and/or color.")
    selected = resolve_series_targets(document, None if all_samples else samples, invalid)
    if not selected:
        raise EngineError("document_unknown_target", "The document has no selected editable series.")
    if not (document.get("plot_type") == "ManagedPlot" and is_figure(document)):
        for _, obj in selected:
            if any("style.line." + key not in obj["capabilities"] for key in style):
                raise invalid("Every selected series must advertise the requested style property.")
            if "color" in style and obj.get("scientific_role"):
                raise invalid("Scientific color encoding requires the explicit scientific edit contract.")
        return [{"op": "set", "target": [target for target, _ in selected],
                 "property": "style.line." + key, "value": value} for key, value in style.items()]

    from sciplot_core.plot_document.validation import validate_wire
    from sciplot_core.plot_grammar.styles import COLOR, style_schema
    from sciplot_core.style_values import managed_color, physical_size_points

    color = style.get("color")
    if color is not None:
        color = color.lower() if color.startswith("#") else managed_color(color)
        validate_wire(color, COLOR, code="figure_edit_invalid_value")
    width = physical_size_points(style["width"]) if "width" in style else None
    layers = {layer["id"]: layer for view in figure_spec(document)["views"] for layer in view["layers"]}
    changes = []
    for target, _ in selected:
        layer = layers[target]
        marks = layer["marks"]
        if (layer["role"] != "measurement" or not marks
                or any(mark["type"] not in {"line", "point"} for mark in marks)
                or width is not None and not any(mark["type"] == "line" for mark in marks)):
            raise invalid("Style shortcuts require ordinary measurement line/point layers; line width requires a line mark.", target=target)
        for mark in marks:
            value = deepcopy(mark["style"])
            if color is not None:
                value["line_color" if mark["type"] == "line" else "marker_color"] = color
            if width is not None and mark["type"] == "line":
                value["line_width_pt"] = width
            validate_wire(value, style_schema(mark["type"]), code="figure_edit_invalid_value")
            if value != mark["style"]:
                changes.append({"op": "set", "target": [mark["id"]], "property": "style", "value": value})
    # Keep a legal patch for an explicit no-op; the existing service owns its result.
    if not changes:
        mark = layers[selected[0][0]]["marks"][0]
        changes.append({"op": "set", "target": [mark["id"]], "property": "style", "value": deepcopy(mark["style"])})
    return changes
