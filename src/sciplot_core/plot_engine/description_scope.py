"""Closed, optional read projections for a managed plot description."""

import re
from typing import Any

from .errors import EngineError

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def selector_issues(value: Any, *, path: str = "/description") -> list[dict[str, Any]]:
    """Return wire-style issues without assuming a particular transport."""
    if not isinstance(value, dict):
        return [{"path": path, "constraint": "object"}]
    scope = value.get("scope")
    if scope not in ("summary", "edit"):
        return [{"path": path + "/scope", "constraint": "enum", "allowed": ["summary", "edit"]}]
    allowed = {"scope"} if scope == "summary" else {"scope", "target", "property"}
    issues: list[dict[str, Any]] = []
    if allowed - value.keys():
        issues.append({"path": path, "constraint": "required", "missing": sorted(allowed - value.keys())})
    if value.keys() - allowed:
        issues.append({"path": path, "constraint": "additionalProperties", "allowed": sorted(allowed)})
    if scope == "edit":
        if "target" in value and (not isinstance(value["target"], str) or
                                  _IDENTIFIER.fullmatch(value["target"]) is None):
            issues.append({"path": path + "/target", "constraint": "stable_target_id"})
        if "property" in value and (not isinstance(value["property"], str) or
                                    not 0 < len(value["property"]) <= 128 or not value["property"].strip()):
            issues.append({"path": path + "/property", "constraint": "nonempty_property_name"})
    return issues


def require_selector(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    issues = selector_issues(value)
    if issues:
        error = EngineError("invalid_description_selector", "Use description scope summary, or edit with an exact target and property.",
                            action="correct_description_selector")
        error.issues = issues
        raise error
    return value
