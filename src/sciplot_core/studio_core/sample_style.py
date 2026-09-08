"""Resolve exact ordinary sample labels into advertised native style changes."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.document_edit_policy import (
    SAMPLE_STYLE_FIELDS, ordinary_curve_paths,
)


def sample_style_targets(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose source-bound labels, including ambiguity, without loading Qt."""
    allowed = ordinary_curve_paths(spec)
    labels: dict[str, list[str]] = {}
    for series in spec.get("series") or []:
        if not isinstance(series, dict):
            continue
        label = series.get("label")
        path = f"/page1/graph1/{series.get('name')}"
        if path in allowed and isinstance(label, str) and label.strip():
            labels.setdefault(label, []).append(path)
    return [{"sample": label, "object_paths": paths, "unique": len(paths) == 1}
            for label, paths in labels.items()]


def expand_sample_styles(
    spec: dict[str, Any], objects: dict[str, Any], operations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bind shorthand to inspected current values; the existing transaction audits it."""
    targets = {item["sample"]: item for item in sample_style_targets(spec)}
    expanded: list[dict[str, Any]] = []
    for operation in operations:
        if operation.get("op") != "set_sample_style":
            expanded.append(operation)
            continue
        samples, style = operation.get("samples"), operation.get("style")
        if (
            set(operation) != {"op", "samples", "style"}
            or not isinstance(samples, list) or not 1 <= len(samples) <= 100
            or not all(isinstance(sample, str) and sample.strip() for sample in samples)
            or len(set(samples)) != len(samples)
            or not isinstance(style, dict) or not style or set(style) - SAMPLE_STYLE_FIELDS.keys()
        ):
            raise AnnotationOperationError(
                "invalid_sample_style", "Provide unique exact sample labels and color and/or width.",
            )
        for sample in samples:
            target = targets.get(sample)
            if target is None:
                raise AnnotationOperationError(
                    "unknown_sample_style_target",
                    f"No ordinary curve with exact sample label {sample!r}. Inspect sample_styles for supported labels.",
                )
            if not target["unique"]:
                raise AnnotationOperationError(
                    "ambiguous_sample_style_target",
                    f"Sample label {sample!r} names multiple curves; inspect and use explicit set_style object paths.",
                )
            path = target["object_paths"][0]
            fields = {field["setting_path"]: field
                      for field in objects.get(path, {}).get("editable_fields", [])}
            for name, value in style.items():
                setting = f"{path}/{SAMPLE_STYLE_FIELDS[name]}"
                if setting not in fields:
                    raise AnnotationOperationError(
                        "unsupported_sample_style", f"The current curve does not advertise {setting}.",
                    )
                expanded.append({"op": "set_style", "object_path": path,
                                 "setting_path": setting,
                                 "expected_value": fields[setting]["current_value"], "value": value})
    if len(expanded) > 100:
        raise AnnotationOperationError("invalid_operations", "The expanded batch exceeds 100 native operations.")
    return expanded
