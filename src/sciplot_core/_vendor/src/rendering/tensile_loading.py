from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_loader import load_curve_table, load_replicate_table, read_raw_table
from src.rendering.io import ensure_input_path, list_sheet_names
from src.rendering.tensile_models import (
    METRIC_NAMES,
    REQUIRED_TENSILE_WORKBOOK_SHEETS,
    LoadedTensileWorkbook,
    TensileWorkbookSummary,
)
from src.tensile_replicates import REPRESENTATIVE_CURVE_SHEET, SUMMARY_SHEET, TensileMetricSummary
from src.text_normalization import slugify_label


def inspect_tensile_workbook(workbook_path: str | Path) -> TensileWorkbookSummary:
    loaded = load_tensile_workbook(workbook_path)
    return TensileWorkbookSummary(
        workbook_path=loaded.workbook_path,
        label=loaded.base_label,
        preferred_sheet=REPRESENTATIVE_CURVE_SHEET,
        sheet_names=loaded.sheet_names,
        sample_count=loaded.sample_count,
        representative_filename=loaded.representative_filename,
        metrics=loaded.metrics,
        warnings=(),
    )


def load_tensile_workbook(workbook_path: str | Path) -> LoadedTensileWorkbook:
    path = ensure_input_path(str(Path(workbook_path).expanduser()))
    sheet_names = tuple(list_sheet_names(path))
    if not sheet_names:
        raise ValueError(f"{path.name} is not a valid Excel workbook.")
    missing_sheets = sorted(REQUIRED_TENSILE_WORKBOOK_SHEETS.difference(sheet_names))
    if missing_sheets:
        joined = ", ".join(missing_sheets)
        raise ValueError(f"{path.name} is missing required worksheet(s): {joined}")

    representative_curves = load_curve_table(path, sheet_name=REPRESENTATIVE_CURVE_SHEET)
    if len(representative_curves) != 1:
        raise ValueError(
            f"{path.name} must contain exactly 1 representative curve group "
            f"in {REPRESENTATIVE_CURVE_SHEET}."
        )

    sample_count, representative_filename = summary_fields(path)
    metrics: list[TensileMetricSummary] = []
    replicate_groups = {}
    for metric_name in METRIC_NAMES:
        try:
            groups = load_replicate_table(path, sheet_name=f"{metric_name}_Replicates")
        except Exception as exc:
            raise ValueError(f"{path.name} has an invalid replicate table in {metric_name}_Replicates: {exc}") from exc
        if len(groups) != 1:
            raise ValueError(f"{path.name} must contain exactly 1 replicate group in {metric_name}_Replicates.")
        group = groups[0]
        if group.data.empty:
            raise ValueError(f"{path.name} does not contain valid replicate values in {metric_name}_Replicates.")
        replicate_groups[metric_name] = group
        mean_value = group.data.mean()
        std_value = group.data.std(ddof=1)
        metrics.append(
            TensileMetricSummary(
                label=group.value_label or metric_name,
                unit=group.value_unit,
                mean=float(mean_value) if pd.notna(mean_value) else None,
                std=float(std_value) if pd.notna(std_value) else None,
            )
        )

    return LoadedTensileWorkbook(
        workbook_path=path,
        base_label=infer_workbook_label(path),
        sheet_names=sheet_names,
        sample_count=sample_count,
        representative_filename=representative_filename,
        representative_curve=representative_curves[0],
        metrics=tuple(metrics),
        replicate_groups=replicate_groups,
    )


def summary_fields(path: Path) -> tuple[int, str]:
    raw = read_raw_table(path, sheet_name=SUMMARY_SHEET).fillna("")
    representative_filename = ""
    sample_count: int | None = None
    for row_index in range(raw.shape[0]):
        first_cell = cell_text(raw.iloc[row_index, 0]) if raw.shape[1] > 0 else ""
        if raw.shape[1] > 4 and representative_filename == "":
            candidate = cell_text(raw.iloc[row_index, 4])
            if candidate and candidate != "Representative File":
                representative_filename = candidate
        if first_cell == "Specimens":
            parsed = parse_int(raw.iloc[row_index, 1] if raw.shape[1] > 1 else "")
            if parsed is not None:
                sample_count = parsed
    if sample_count is None:
        raise ValueError(f"{path.name} is missing the Specimens count in Summary.")
    if representative_filename == "":
        raise ValueError(f"{path.name} is missing the Representative File entry in Summary.")
    return sample_count, representative_filename


def validate_metric_units(loaded_sources: list[LoadedTensileWorkbook]) -> None:
    for metric_name in METRIC_NAMES:
        expected_label = loaded_sources[0].replicate_groups[metric_name].value_label
        expected_unit = loaded_sources[0].replicate_groups[metric_name].value_unit
        for source in loaded_sources[1:]:
            group = source.replicate_groups[metric_name]
            if group.value_label != expected_label or group.value_unit != expected_unit:
                raise ValueError(
                    f"The label or unit for {metric_name} does not match: "
                    f"{loaded_sources[0].workbook_path.name} and "
                    f"{source.workbook_path.name} cannot be compared directly."
                )


def validate_curve_axes(loaded_sources: list[LoadedTensileWorkbook]) -> None:
    first_curve = loaded_sources[0].representative_curve
    for source in loaded_sources[1:]:
        curve = source.representative_curve
        if (
            curve.x_label != first_curve.x_label
            or curve.y_label != first_curve.y_label
            or curve.x_unit != first_curve.x_unit
            or curve.y_unit != first_curve.y_unit
        ):
            raise ValueError(
                f"The representative curve axis labels or units in {source.workbook_path.name} do not match "
                f"{loaded_sources[0].workbook_path.name}."
            )


def infer_workbook_label(path: Path) -> str:
    stem = path.stem.strip()
    if stem:
        return stem
    name = path.name.strip()
    return name or "Tensile Workbook"


def dedupe_labels(labels: Any) -> list[str]:
    counts: dict[str, int] = {}
    deduped: list[str] = []
    for label in labels:
        text = str(label).strip() or "Tensile Workbook"
        counts[text] = counts.get(text, 0) + 1
        suffix = counts[text]
        deduped.append(text if suffix == 1 else f"{text} ({suffix})")
    return deduped


def bundle_dir_name(labels: list[str]) -> str:
    slug = "_vs_".join(slugify_label(label) for label in labels) or "tensile_compare"
    base = f"{slug}_tensile_compare"
    if len(base) <= 96:
        return base
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{base[:87].rstrip('_')}_{digest}"


def parse_int(value: object) -> int | None:
    try:
        return int(float(cell_text(value)))
    except ValueError:
        return None


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


__all__ = [
    "bundle_dir_name",
    "cell_text",
    "dedupe_labels",
    "infer_workbook_label",
    "inspect_tensile_workbook",
    "load_tensile_workbook",
    "parse_int",
    "summary_fields",
    "validate_curve_axes",
    "validate_metric_units",
]
