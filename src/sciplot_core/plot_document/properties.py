"""Semantic property registry; callers cannot downgrade scientific risk."""

import re
from typing import Any

from sciplot_core.style_values import normalize_physical_size

from .errors import fail


# type, minimum risk, object kinds; native paths never enter this registry.
PROPERTY_RULES: dict[str, tuple[str, str, set[str]]] = {
    "style.line.width": ("physical_size", "presentation", {"series"}),
    "style.line.color": ("color", "presentation", {"series"}),
    "font.size": ("physical_size", "presentation", {"title", "axis", "legend", "annotation", "figure"}),
    "title.visible": ("boolean", "presentation", {"title"}),
    "title.text": ("string", "review", {"title"}),
    "axis.limits": ("number_pair", "review", {"axis"}),
    "legend.visible": ("boolean", "presentation", {"legend"}),
    "legend.position": ("number_pair", "review", {"legend"}),
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
        size = normalize_physical_size(value)
        match = re.fullmatch(r"([0-9.]+)(pt|mm|cm|in|inch)", size)
        assert match is not None
        points = float(match[1]) * {"pt": 1, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72, "inch": 72}[match[2]]
        low, high = (0.1, 10) if prop == "style.line.width" else (4, 72)
        if not low <= points <= high:
            risk = maximum_risk(risk, "review")
    return risk
