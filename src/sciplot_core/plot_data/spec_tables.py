"""Convert saved Veusz specifications into user-facing plotted-data tables."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pandas as pd

from sciplot_core.materials_rules import format_unit_label
from sciplot_core.plot_data.source_tables import sample_hint


UNIT_SUFFIXES = (
    "MPa",
    "kPa",
    "Pa",
    "mN",
    "Nm",
    "N",
    "mm",
    "um",
    "μm",
    "µm",
    "cm",
    "m",
    "°C",
    "C",
    "K",
    "s",
    "h",
    "%",
    "1",
)


def spec_paths(manifest: dict[str, Any]) -> list[Path]:
    result: dict[str, Any] = cast(dict[str, Any], manifest.get("result")) if isinstance(manifest.get("result"), dict) else {}
    values: list[object] = []
    values.extend(
        manifest.get("veusz_specs", [])
        if isinstance(manifest.get("veusz_specs"), list)
        else []
    )
    values.extend([manifest.get("veusz_spec"), result.get("veusz_spec")])
    for owner in (manifest, result):
        documents = owner.get("veusz_documents")
        if not isinstance(documents, list):
            continue
        for value in documents:
            if not isinstance(value, str) or not value.strip():
                continue
            document = Path(value).expanduser().resolve()
            values.append(
                str(document.with_name("spec.json"))
                if document.name == "document.vsz"
                else str(document.with_suffix(".spec.json"))
            )
    paths: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser().resolve()
        if path in seen or not path.is_file():
            continue
        paths.append(path)
        seen.add(path)
    return paths


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def spec_to_table(
    spec: dict[str, Any],
    *,
    manifest: dict[str, Any],
    spec_path: Path,
) -> pd.DataFrame | None:
    series = spec.get("series") if isinstance(spec.get("series"), list) else []
    if series:
        x_name, x_unit = axis_descriptor(spec, manifest=manifest, axis="x")
        y_name, y_unit = axis_descriptor(spec, manifest=manifest, axis="y")
        values: list[tuple[list[Any], list[Any], str]] = []
        for item in series:
            if not isinstance(item, dict):
                continue
            x_values = (
                item.get("x_values") if isinstance(item.get("x_values"), list) else []
            )
            y_values = (
                item.get("y_values") if isinstance(item.get("y_values"), list) else []
            )
            if not x_values or not y_values:
                continue
            label = str(item.get("label") or item.get("name") or "").strip()
            values.append((x_values, y_values, label))
        if not values:
            return None
        rows: list[list[Any]] = [
            [x_name, y_name] * len(values),
            [x_unit, y_unit] * len(values),
        ]
        rows.append([label for _x, _y, label in values for _ in (0, 1)])
        for row_index in range(max(max(len(x), len(y)) for x, y, _label in values)):
            row: list[Any] = []
            for x_values, y_values, _label in values:
                row.extend(
                    [
                        x_values[row_index] if row_index < len(x_values) else "",
                        y_values[row_index] if row_index < len(y_values) else "",
                    ]
                )
            rows.append(row)
        return pd.DataFrame(rows)

    scalar = (
        cast(dict[str, Any], spec.get("scalar_field")) if isinstance(spec.get("scalar_field"), dict) else {}
    )
    x_values = (
        scalar.get("x_values") if isinstance(scalar.get("x_values"), list) else []
    )
    y_values = (
        scalar.get("y_values") if isinstance(scalar.get("y_values"), list) else []
    )
    z_values = (
        scalar.get("z_values") if isinstance(scalar.get("z_values"), list) else []
    )
    if not x_values or not y_values or not z_values:
        return None
    x_name, x_unit = variable_descriptor(scalar.get("x_column"), fallback="x")
    y_name, y_unit = variable_descriptor(scalar.get("y_column"), fallback="y")
    z_name, z_unit = variable_descriptor(scalar.get("z_column"), fallback="z")
    sample = sample_hint(manifest, spec_path.parent)
    scalar_rows: list[list[Any]] = [
        [x_name, y_name, z_name],
        [x_unit, y_unit, z_unit],
        [sample, sample, sample],
    ]
    for y_index, y_value in enumerate(y_values):
        row_values = (
            z_values[y_index]
            if y_index < len(z_values) and isinstance(z_values[y_index], list)
            else []
        )
        for x_index, x_value in enumerate(x_values):
            z_value = row_values[x_index] if x_index < len(row_values) else ""
            scalar_rows.append([x_value, y_value, z_value])
    return pd.DataFrame(scalar_rows)


def axis_descriptor(
    spec: dict[str, Any],
    *,
    manifest: dict[str, Any],
    axis: str,
) -> tuple[str, str]:
    axes: dict[str, Any] = cast(dict[str, Any], spec.get("axes")) if isinstance(spec.get("axes"), dict) else {}
    axis_spec: dict[str, Any] = cast(dict[str, Any], axes.get(axis)) if isinstance(axes.get(axis), dict) else {}
    if str(axis_spec.get("label") or "").strip():
        return split_label_unit(axis_spec["label"], fallback=axis)
    semantic = (
        cast(dict[str, Any], manifest.get("semantic")) if isinstance(manifest.get("semantic"), dict) else {}
    )
    axis_plan = (
        cast(dict[str, Any], semantic.get("axis_plan")) if isinstance(semantic.get("axis_plan"), dict) else {}
    )
    axis_payload: dict[str, Any] = cast(dict[str, Any], axis_plan.get(axis)) if isinstance(axis_plan.get(axis), dict) else {}
    unit_plan = (
        cast(dict[str, Any], semantic.get("unit_plan")) if isinstance(semantic.get("unit_plan"), dict) else {}
    )
    canonical_name = str(axis_payload.get("canonical_label") or "").strip()
    canonical_unit = str(
        unit_plan.get(axis) or axis_payload.get("canonical_unit") or ""
    ).strip()
    if canonical_name:
        return canonical_name, display_unit(canonical_unit)
    return split_label_unit(axis_spec.get("label"), fallback=axis)


def variable_descriptor(value: object, *, fallback: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return fallback, ""
    return split_label_unit(text.replace("_", " "), fallback=fallback)


def split_label_unit(value: object, *, fallback: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return fallback, ""
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", text)
    if match:
        return match.group(1).strip() or fallback, display_unit(match.group(2).strip())
    for unit in UNIT_SUFFIXES:
        if text.endswith(f"_{unit}") or text.endswith(f" {unit}"):
            return (
                text[: -(len(unit) + 1)].replace("_", " ").strip() or fallback,
                display_unit(unit),
            )
    return text.replace("_", " "), ""


def unit_from_label(value: object) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", text)
    return display_unit(match.group(2).strip()) if match else ""


def display_unit(value: object) -> str:
    return format_unit_label(str(value or "").strip())


def replicate_summary_table(spec: dict[str, Any], *, spec_sha256: str) -> pd.DataFrame | None:
    """Project audited rendered means/SD/n; never recompute statistics for export."""
    import math

    request = spec.get("source_request", {})
    if not isinstance(request, dict):
        return None
    from sciplot_core.source_coverage.replicate_disclosure import verify_replicate_summary_request

    audit = verify_replicate_summary_request(request)
    if audit is None:
        return None
    disclosure = request.get("replicate_summary_disclosure")
    categorical = spec.get("categorical", {})
    if (not isinstance(disclosure, dict) or disclosure.get("version") != 1
            or disclosure.get("missing_values") not in {"exclude", "none_present"}
            or not isinstance(disclosure.get("groups"), list)
            or not isinstance(categorical, dict)
            or categorical.get("presentation_kind") not in {"bar_error", "grouped_bar_error"}
            or categorical.get("summary_statistic") != "arithmetic_mean"
            or categorical.get("bar_error_statistic") != "sd"):
        raise ValueError("Delivered mean/sample SD/n requires its audited bar contract and source disclosure.")
    task = request.get("resolved_figure_task", {})
    conditions = task.get("conditions", []) if isinstance(task, dict) else []
    evidence = disclosure["groups"]
    if conditions:
        evidence = [group for group in evidence if group["condition"] in conditions]
    groups = categorical.get("groups")
    if not isinstance(groups, list) or len(groups) != len(evidence):
        raise ValueError("Summary groups do not match the original source-bound n disclosure.")
    rows: list[list[Any]] = [["sample", "condition", "metric", "unit", "mean", "sample_sd", "valid_n",
                            "missing_policy", "excluded_missing_count", "source_sha256", "spec_sha256"]]
    for actual, original in zip(groups, evidence, strict=True):
        count = actual.get("replicate_count")
        condition = actual.get("condition_label") or (conditions[0] if len(conditions) == 1 else "")
        if (actual.get("sample_label") != original["sample"] or condition != original["condition"]
                or type(count) is not int or count < 2 or count != original["valid_n"]
                or actual.get("bar_error_statistic") != "sd"
                or type(original.get("missing_count")) is not int or original["missing_count"] < 0
                or (original["missing_count"] and disclosure["missing_values"] != "exclude")):
            raise ValueError("Audited mean/SD/n group identity, valid count or missing policy differs from source disclosure.")
        numbers = [actual.get("bar_mean"), actual.get("bar_error")]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in numbers) or numbers[1] < 0:
            raise ValueError("Audited bar mean and sample SD must be finite; undefined SD cannot be delivered.")
        rows.append([original["sample"], original["condition"], original["metric"], original["unit"],
                     *[format(value, ".17g") for value in numbers], count, disclosure["missing_values"],
                     original["missing_count"], disclosure["source_sha256"], spec_sha256])
    return pd.DataFrame(rows)
