"""Build assisted-cleanup intervention requests and actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.operation_modes import assisted_cleanup_mode_payload


def build_intervention_request(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    semantic: dict[str, Any],
    request: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    category = _classify_intervention(semantic, error)
    return {
        "kind": "sciplot_intervention_request",
        "input": str(Path(input_path).expanduser()),
        "output": str(Path(output_dir).expanduser()),
        "needs_ai_intervention": bool(semantic.get("needs_ai_intervention", True)),
        "category": category,
        "semantic": semantic,
        "request": request or {},
        "error": error,
        "recommended_action": _intervention_action(category),
        "operation_mode": assisted_cleanup_mode_payload(reason=category),
    }


def _classify_intervention(semantic: dict[str, Any], error: str | None) -> str:
    if semantic.get("needs_ai_intervention"):
        if (
            not semantic.get("semantic_family")
            or semantic.get("semantic_family") == "unknown"
        ):
            return "unrecognized_format"
        return "semantic_gap"
    if error and "Could not recognize" in str(error):
        return "format_mismatch"
    if error and "column" in str(error).casefold():
        return "column_missing"
    if error and ("parse" in str(error).casefold() or "read" in str(error).casefold()):
        return "parse_failure"
    if error and "not found" in str(error).casefold():
        return "missing_dependency"
    if error:
        return "render_failure"
    return "unknown"


def _intervention_action(category: str) -> str:
    actions = {
        "unrecognized_format": (
            "Use Codex-assisted cleanup to inspect this file, update semantic classification rules, "
            "add a new material rule or recipe preprocessor, create a simulated fixture, "
            "run tests, and rerun the plotting request."
        ),
        "semantic_gap": (
            "The semantic family is identified but no recipe can process it. "
            "Use assisted repair to add a new recipe module or extend an existing one with fixture data."
        ),
        "format_mismatch": (
            "The file format is recognized but columns don't match expectations. "
            "Use assisted cleanup to update column aliases in materials_rules or add a preprocessor."
        ),
        "column_missing": (
            "Expected columns are missing from the input. "
            "Use assisted cleanup to add column aliases or update the column detection logic."
        ),
        "parse_failure": (
            "The file could not be parsed. Use assisted cleanup to investigate encoding, delimiter, "
            "or file structure issues and add a fixture for this instrument export format."
        ),
        "render_failure": (
            "Rendering failed after successful preparation. Use assisted repair to inspect the "
            "render options, template compatibility, and vendor rendering path."
        ),
        "missing_dependency": (
            "A required component or file is missing. Use assisted repair to check dependencies and file paths."
        ),
    }
    return actions.get(category, actions["unrecognized_format"])
