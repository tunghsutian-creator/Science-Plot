"""Closed source-bound metric choices and missing-unit user declarations."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sciplot_core.foundation.source_errors import SourceVersionMismatch
from typing import Any, NoReturn

from sciplot_core.performance_comparison.models import PerformanceComparisonError

SELECTION_KIND = "sciplot_performance_metric_selection"
_FIELDS = {
    "kind",
    "version",
    "source_sha256",
    "x_metric",
    "y_metric",
    "scatter_x_display",
    "unit_declarations",
}


def performance_selection_schema() -> dict[str, Any]:
    """Describe the complete external metadata payload; parsing owns cross-fields."""
    text = {"type": "string", "minLength": 1}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_FIELDS),
        "properties": {
            "kind": {"type": "string", "const": SELECTION_KIND},
            "version": {"type": "integer", "const": 1},
            "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "x_metric": dict(text),
            "y_metric": dict(text),
            "scatter_x_display": {
                "type": "string",
                "enum": ["preserve_original", "deterministic_jitter"],
            },
            "unit_declarations": {
                "type": "array",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["metric_id", "unit", "user_statement"],
                    "properties": {
                        field: dict(text)
                        for field in ("metric_id", "unit", "user_statement")
                    },
                },
            },
        },
    }


def _invalid(message: str) -> NoReturn:
    raise PerformanceComparisonError("performance_selection_invalid", message)


def _canonical_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        _invalid(f"Performance selection {field} must be non-empty canonical text.")
    return value


def parse_performance_selection(value: Any) -> dict[str, Any]:
    """Reject partial, unknown, inferred or unbound scientific selections."""
    if not isinstance(value, dict) or set(value) != _FIELDS:
        _invalid(
            "Performance selection requires exactly: " + ", ".join(sorted(_FIELDS))
        )
    if (
        value["kind"] != SELECTION_KIND
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        _invalid("Unknown performance metric selection kind or version.")
    digest = _canonical_text(value["source_sha256"], "source_sha256")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        _invalid("Performance selection source_sha256 must be a current SHA-256.")
    x_metric = _canonical_text(value["x_metric"], "x_metric")
    y_metric = _canonical_text(value["y_metric"], "y_metric")
    if x_metric == y_metric:
        _invalid("Performance scatter requires two distinct original Metric IDs.")
    if value["scatter_x_display"] not in ("preserve_original", "deterministic_jitter"):
        _invalid("scatter_x_display must be preserve_original or deterministic_jitter.")
    declarations = value["unit_declarations"]
    if not isinstance(declarations, list):
        _invalid("unit_declarations must be a list of per-Metric user statements.")
    confirmed: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in declarations:
        if not isinstance(item, dict) or set(item) != {
            "metric_id",
            "unit",
            "user_statement",
        }:
            _invalid(
                "Each unit declaration requires exactly metric_id, unit, user_statement."
            )
        declaration = {
            key: _canonical_text(item[key], key)
            for key in ("metric_id", "unit", "user_statement")
        }
        metric = declaration["metric_id"]
        if metric not in (x_metric, y_metric) or metric in seen:
            _invalid(
                "Unit declarations must uniquely name a selected original Metric ID."
            )
        seen.add(metric)
        confirmed.append(declaration)
    return {**value, "unit_declarations": confirmed}


def selection_template(
    source_sha256: str, metrics: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return an intentionally incomplete template for the original user to fill."""
    return {
        "kind": SELECTION_KIND,
        "version": 1,
        "source_sha256": source_sha256,
        "x_metric": "",
        "y_metric": "",
        "scatter_x_display": "preserve_original",
        "unit_declarations": [
            {"metric_id": item["metric_id"], "unit": "", "user_statement": ""}
            for item in metrics
            if item["missing_unit_count"]
        ],
    }


def performance_selection_from_request(
    request: dict[str, Any],
) -> dict[str, Any] | None:
    return (
        parse_performance_selection(request["performance_selection"])
        if "performance_selection" in request
        else None
    )



@contextmanager
def selected_performance_source_errors(request: dict[str, Any], *, base_dir: Path) -> Iterator[None]:
    """Translate only a proved mismatch of this selection's exact input version."""
    try:
        yield
    except SourceVersionMismatch as exc:
        source = request.get("input")
        selection = performance_selection_from_request(request)
        if isinstance(source, str) and source and selection is not None:
            literal = Path(source).expanduser()
            literal = literal if literal.is_absolute() else base_dir / literal
            if str(literal) == exc.literal and selection["source_sha256"] == exc.expected_sha256:
                raise PerformanceComparisonError("performance_selection_source_changed",
                    "Performance selection is bound to different original source bytes; inspect the current table again.") from exc
        raise
