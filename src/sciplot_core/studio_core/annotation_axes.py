"""Shared ordinary-curve scope and exact displayed annotation units."""

from __future__ import annotations

import re
from typing import Any

from sciplot_core.studio_core.annotation_schema import AnnotationOperationError


def require_scope(spec: dict[str, Any]) -> None:
    if spec.get("template") not in {"curve", "point_line", "stacked_curve"} or any(
        spec.get(key) is not None for key in ("scalar_field", "categorical", "performance_comparison")
    ):
        raise AnnotationOperationError("unsupported_annotation_scope", "Annotations currently require ordinary Cartesian curves.")


def axis_unit(spec: dict[str, Any], axis: str) -> str:
    label = str(spec["axes"][axis]["label"])
    match = re.search(r"\(([^()]*)\)\s*$", label)
    return match[1] if match else ""


