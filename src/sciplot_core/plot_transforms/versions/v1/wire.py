"""Strict finite JSON and bounded JSON-pointer validation diagnostics."""

import math
from typing import Any
from copy import deepcopy

from jsonschema import Draft202012Validator

from sciplot_core.plot_document.errors import DocumentError, fail


def pointer_part(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def finite_json(value: Any, path: str = "") -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for index, item in enumerate(value):
            finite_json(item, f"{path}/{index}")
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for key, item in value.items():
            finite_json(item, f"{path}/{pointer_part(key)}")
        return
    fail("document_invalid_json", "Use finite JSON values without implicit coercion.", path or "/", "finite_json")


def validate_wire(value: Any, schema: dict[str, Any], *, code: str) -> None:
    finite_json(value)
    issues: list[dict[str, Any]] = []
    for error in Draft202012Validator(schema).iter_errors(value):
        issue: dict[str, Any] = {
            "path": "/" + "/".join(pointer_part(part) for part in error.absolute_path),
            "constraint": error.validator,
        }
        if error.validator == "required":
            issue["missing"] = [key for key in error.validator_value if key not in error.instance]
        elif error.validator == "additionalProperties" and isinstance(error.instance, dict):
            allowed = error.schema.get("properties", {})
            issue.update(unsupported=sorted(set(error.instance) - set(allowed)), allowed=sorted(allowed))
        elif error.validator in {"type", "const", "enum", "pattern", "minimum", "minItems", "maxItems"}:
            issue["expected"] = error.validator_value
        issues.append(issue)
        if len(issues) == 8:
            break
    if issues:
        raise DocumentError(code, "The document contract rejected these fields.", issues=issues)


def closed(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": deepcopy(properties),
            "required": list(properties) if required is None else list(required),
            "additionalProperties": False}


IDENTIFIER = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"}
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
