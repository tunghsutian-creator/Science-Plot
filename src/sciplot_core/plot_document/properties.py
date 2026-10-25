"""Semantic property registry; callers cannot downgrade scientific risk."""

from typing import Any

from sciplot_core.style_values import normalize_physical_size, physical_size_points
from sciplot_core.policy.frame_export import DEFAULT_LINE_STYLE_SEQUENCE

from .errors import fail


# type, minimum risk, object kinds; native paths never enter this registry.
PROPERTY_RULES: dict[str, tuple[str, str, set[str]]] = {
    "series.display_label": ("string", "review", {"series"}),
    "series.visible": ("boolean", "review", {"series"}),
    "style.line.width": ("physical_size", "presentation", {"series"}),
    "style.line.color": ("color", "presentation", {"series"}),
    "style.line.pattern": ("enum", "presentation", {"series"}),
    "font.size": ("physical_size", "presentation", {"title", "axis", "legend", "annotation", "figure"}),
    "title.visible": ("boolean", "presentation", {"title"}),
    "title.text": ("string", "review", {"title"}),
    "axis.limits": ("number_pair", "review", {"axis"}),
    "legend.visible": ("boolean", "presentation", {"legend"}),
    "legend.columns": ("number", "presentation", {"legend"}),
    "legend.position": ("number_pair", "review", {"legend"}),
    "legend.sample_length": ("physical_size", "presentation", {"legend"}),
    "annotation.position": ("number_pair", "review", {"annotation"}),
    "annotation.visible": ("boolean", "review", {"annotation"}),
    "annotation.text": ("string", "review", {"annotation"}),
}
RISK_ORDER = {"presentation": 0, "review": 1, "scientific": 2}


def maximum_risk(*risks: str) -> str:
    return max(risks, key=lambda risk: RISK_ORDER[risk])


def validate_capability(obj: dict[str, Any], prop: str, capability: dict[str, Any], path: str) -> None:
    if prop not in PROPERTY_RULES:
        fail("document_unsupported_property", "This semantic property has no registered executor.",
             path, "registered_property", allowed=sorted(PROPERTY_RULES))
    value_type, minimum_risk, kinds = PROPERTY_RULES[prop]
    if obj["kind"] not in kinds or capability["type"] != value_type:
        fail("document_invalid_capability", "The capability disagrees with the semantic property registry.",
             path, "property_binding", expected_type=value_type, allowed_kinds=sorted(kinds))
    if RISK_ORDER[capability["risk"]] < RISK_ORDER[minimum_risk]:
        fail("document_invalid_capability", "A property capability cannot lower its registered risk.",
             path + "/risk", "minimum_risk", minimum=minimum_risk)
    if prop == "style.line.pattern" and (
        not capability.get("enum")
        or any(value not in DEFAULT_LINE_STYLE_SEQUENCE for value in capability["enum"])
    ):
        fail("document_invalid_capability", "Line patterns must use the bounded visible pattern contract.",
             path, "visible_line_pattern", allowed=list(DEFAULT_LINE_STYLE_SEQUENCE))
    if prop == "legend.columns" and (not capability.get("enum") or any(type(value) is not int or not 1 <= value <= 32 for value in capability["enum"])):
        fail("document_invalid_capability", "Legend columns use integer values from 1 to 32.", path, "legend_columns")
    if set(capability) & {"min_length", "max_length", "non_blank"} and (
            value_type != "string" or capability.get("min_length", 0) > capability.get("max_length", 4096)):
        fail("document_invalid_capability", "String bounds must match the property type and be ordered.",
             path, "string_bounds")
    if "direction" in capability and prop != "axis.limits":
        fail("document_invalid_capability", "Axis direction belongs only to an axis-limits capability.",
             path, "axis_direction")
    if set(capability) & {"coordinate_mode", "units"}:
        mode = capability.get("coordinate_mode", "relative")
        if (prop not in {"annotation.position", "legend.position"}
                or prop == "legend.position" and mode != "relative"
                or mode == "axes" and "units" not in capability
                or mode == "relative" and "units" in capability):
            fail("document_invalid_capability", "Coordinate mode and explicit units must match the imported position binding.",
                 path, "coordinate_binding")


def validate_value(prop: str, value: Any, capability: dict[str, Any], path: str) -> None:
    if value is None and capability.get("nullable", False):
        return
    kind = capability["type"]
    valid = False
    if kind == "physical_size" and isinstance(value, str):
        try:
            normalize_physical_size(value)
            valid = True
        except ValueError:
            pass
    elif kind == "boolean":
        valid = type(value) is bool
    elif kind in {"color", "string"}:
        valid = isinstance(value, str) and len(value) <= (128 if kind == "color" else 4096)
        if kind == "color":
            valid = valid and bool(value.strip()) and not any(ord(char) < 32 for char in value)
        elif valid:
            valid = (capability.get("min_length", 0) <= len(value) <= capability.get("max_length", 4096)
                     and (not capability.get("non_blank", False) or bool(value.strip())))
    elif kind == "number":
        valid = type(value) in {float, int}
    elif kind == "number_pair":
        valid = isinstance(value, list) and len(value) == 2 and all(type(item) in {int, float} for item in value)
        if valid and prop == "axis.limits":
            valid = value[0] > value[1] if capability.get("direction") == "descending" else value[0] < value[1]
        elif valid and prop.endswith(".position"):
            valid = capability.get("coordinate_mode") == "axes" or all(0 <= item <= 1 for item in value)
    elif kind == "enum":
        valid = value in capability.get("enum", [])
    if valid and "enum" in capability:
        valid = any(type(value) is type(item) and value == item for item in capability["enum"])
    if not valid:
        fail("document_invalid_value", "Use the property's advertised value type and constraints.",
             path, "property_value", property=prop, expected_type=kind,
             **({"allowed": capability["enum"]} if "enum" in capability else {}),
             **{key: capability[key] for key in ("min_length", "max_length", "non_blank", "direction",
                                                 "coordinate_mode", "units") if key in capability})


def effective_risk(obj: dict[str, Any], prop: str, value: Any) -> str:
    capability = obj["capabilities"][prop]
    risk = maximum_risk(PROPERTY_RULES[prop][1], capability["risk"])
    if obj.get("scientific_role") and prop == "style.line.color":
        return "scientific"
    if obj.get("scientific_role") and prop in {"title.visible", "annotation.visible"}:
        risk = maximum_risk(risk, "review")
    if capability["type"] == "physical_size" and isinstance(value, str):
        points = physical_size_points(value)
        low, high = (0.1, 10) if prop == "style.line.width" else (4, 72)
        if not low <= points <= high:
            risk = maximum_risk(risk, "review")
    return risk
