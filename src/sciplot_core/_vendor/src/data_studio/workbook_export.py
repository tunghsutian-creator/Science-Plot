from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from src.data_studio.builtin import tensile as tensile_builtin
from src.data_studio.models import DataStudioWorkbook, WorkbookMetricSummary
from src.data_studio.workbook_constants import (
    FILTERED_WORKBOOK_CURVE_DECIMAL_PLACES,
    FILTERED_WORKBOOK_DECIMAL_PLACES,
)

if TYPE_CHECKING:
    from src.data_studio.workbook_previewing import FilteredWorkbookContext, LoadedWorkbookSpecimen


def export_filtered_workbook_from_context(
    filtered: FilteredWorkbookContext,
    output_path: str | Path,
    *,
    label: str | None = None,
    source_workbook_path: str | Path | None = None,
    decimal_places: int = FILTERED_WORKBOOK_DECIMAL_PLACES,
    curve_decimal_places: int = FILTERED_WORKBOOK_CURVE_DECIMAL_PLACES,
) -> DataStudioWorkbook:
    if not filtered.included_specimens:
        raise ValueError(f"{filtered.workbook.workbook_path.name} needs at least one included specimen.")
    if filtered.representative_curve is None or filtered.representative_filename is None:
        raise ValueError(
            f"{filtered.workbook.workbook_path.name} needs at least one included specimen with a representative curve."
        )

    workbook_path = Path(output_path).expanduser()
    if workbook_path.suffix.lower() != ".xlsx":
        workbook_path = workbook_path.with_suffix(".xlsx")
    workbook_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_label = (label or filtered.workbook.label).strip() or filtered.workbook.label or workbook_path.stem
    summary_df = _summary_dataframe_for_specimens(filtered.workbook, filtered.included_specimens)
    export_warnings = _filtered_workbook_export_warnings(filtered)
    metadata_sheet = _filtered_metadata_sheet_dataframe(
        filtered,
        label=resolved_label,
        source_workbook_path=Path(source_workbook_path).expanduser()
        if source_workbook_path is not None
        else filtered.workbook.workbook_path,
        warnings=export_warnings,
    )

    representative_sheet = _formatted_export_dataframe(
        _curve_table_dataframe(((f"{resolved_label} representative", filtered.representative_curve.data),)),
        decimal_places=curve_decimal_places,
    )
    all_curves_sheet = _formatted_export_dataframe(
        _curve_table_dataframe(
            (Path(specimen.filename).stem or specimen.label, specimen.curve.data)
            for specimen in filtered.included_specimens
            if specimen.curve is not None
        ),
        decimal_places=curve_decimal_places,
    )
    all_specimens_sheet = _formatted_export_dataframe(
        _plain_table_dataframe(summary_df),
        decimal_places=decimal_places,
    )
    summary_sheet = _formatted_export_dataframe(
        _summary_sheet_dataframe(
            summary_df,
            representative_filename=filtered.representative_filename,
            metrics=list(filtered.metric_summaries),
        ),
        decimal_places=decimal_places,
    )

    with pd.ExcelWriter(workbook_path) as writer:
        metadata_sheet.to_excel(writer, sheet_name=tensile_builtin.METADATA_SHEET, header=False, index=False)
        representative_sheet.to_excel(
            writer,
            sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
            header=False,
            index=False,
        )
        all_curves_sheet.to_excel(
            writer,
            sheet_name=tensile_builtin.ALL_CURVES_SHEET,
            header=False,
            index=False,
        )
        all_specimens_sheet.to_excel(
            writer,
            sheet_name=tensile_builtin.ALL_SPECIMENS_SHEET,
            header=False,
            index=False,
        )
        summary_sheet.to_excel(
            writer,
            sheet_name=tensile_builtin.SUMMARY_SHEET,
            header=False,
            index=False,
        )
        for metric in filtered.workbook.metrics:
            group = filtered.replicate_groups.get(metric.label)
            replicate_values = group.data.dropna().tolist() if group is not None else []
            replicate_sheet = _formatted_export_dataframe(
                _replicate_table_dataframe(
                    group_name=resolved_label,
                    value_label=metric.label,
                    value_unit=metric.unit,
                    values=replicate_values,
                ),
                decimal_places=decimal_places,
            )
            replicate_sheet.to_excel(
                writer,
                sheet_name=f"{metric.label}_Replicates",
                header=False,
                index=False,
            )

    from src.data_studio.workbooks import import_workbook

    return import_workbook(workbook_path)


def _summary_dataframe_for_specimens(
    workbook,
    specimens: Iterable[LoadedWorkbookSpecimen],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for specimen in specimens:
        row: dict[str, object] = {"Filename": specimen.filename}
        for metric in workbook.metrics:
            row[f"{metric.label} ({metric.unit})"] = specimen.metrics.get(metric.label)
        rows.append(row)
    return pd.DataFrame(rows)


def _filtered_workbook_export_warnings(filtered: FilteredWorkbookContext) -> tuple[str, ...]:
    warnings = list(filtered.workbook.warnings)
    missing_curve_filenames = sorted(
        specimen.filename
        for specimen in filtered.included_specimens
        if specimen.curve is None
    )
    if missing_curve_filenames:
        warnings.append(
            "Skipped curve export for specimens without matched All_Curves data: "
            + ", ".join(missing_curve_filenames)
        )
    return tuple(warnings)


def _filtered_source_files(filtered: FilteredWorkbookContext) -> tuple[Path, ...]:
    paths: list[Path] = []
    seen: set[str] = set()
    for specimen in filtered.included_specimens:
        if specimen.source_path is None:
            continue
        resolved = str(specimen.source_path)
        if resolved in seen:
            continue
        paths.append(specimen.source_path)
        seen.add(resolved)
    if paths:
        return tuple(paths)
    fallback: list[Path] = []
    for source_path in filtered.workbook.source_files:
        resolved = str(source_path)
        if resolved in seen:
            continue
        fallback.append(source_path)
        seen.add(resolved)
    return tuple(fallback)


def _filtered_metadata_sheet_dataframe(
    filtered: FilteredWorkbookContext,
    *,
    label: str,
    source_workbook_path: Path,
    warnings: Iterable[str],
) -> pd.DataFrame:
    base = _metadata_sheet_dataframe(
        label=label,
        template_id=filtered.workbook.template_match.template_id,
        source_files=_filtered_source_files(filtered),
        warnings=warnings,
        representative_filename=filtered.representative_filename or "",
        sample_count=len(filtered.included_specimens),
        metric_ids=(metric.id for metric in filtered.metric_summaries),
    )
    extra = pd.DataFrame(
        [
            ["filtered_from_workbook_path", str(source_workbook_path)],
            ["export_mode", "filtered"],
            ["representative_specimen_id", filtered.representative_specimen_id or ""],
            [
                "included_specimen_ids",
                " | ".join(specimen.specimen_id for specimen in filtered.included_specimens),
            ],
        ]
    )
    return pd.concat([base, extra], ignore_index=True)


def _formatted_export_dataframe(dataframe: pd.DataFrame, *, decimal_places: int) -> pd.DataFrame:
    rows: list[list[object]] = []
    for row in dataframe.values.tolist():
        rows.append([_format_numeric_export_cell(value, decimal_places=decimal_places) for value in row])
    return pd.DataFrame(rows)


def _format_numeric_export_cell(value: object, *, decimal_places: int) -> object:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, (float, int, np.floating, np.integer)):
        if pd.isna(value):
            return ""
        numeric = float(value)
        if abs(numeric) < 0.5 * (10 ** (-decimal_places)):
            numeric = 0.0
        return f"{numeric:.{decimal_places}f}"
    return value


def _metadata_sheet_dataframe(
    *,
    label: str,
    template_id: str,
    source_files: Iterable[Path],
    warnings: Iterable[str],
    representative_filename: str,
    sample_count: int,
    metric_ids: Iterable[str],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["label", label],
            ["template_id", template_id],
            ["source_files", " | ".join(str(path) for path in source_files)],
            ["warnings", " | ".join(warnings)],
            ["representative_filename", representative_filename],
            ["sample_count", sample_count],
            ["metric_ids", " | ".join(metric_ids)],
        ]
    )


def _curve_table_dataframe(series_pairs: Iterable[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    return tensile_builtin.curve_table_dataframe(series_pairs)


def _replicate_table_dataframe(
    *,
    group_name: str,
    value_label: str,
    value_unit: str,
    values: Iterable[float],
) -> pd.DataFrame:
    return tensile_builtin.replicate_table_dataframe(
        group_name=group_name,
        value_label=value_label,
        value_unit=value_unit,
        values=values,
    )


def _summary_sheet_dataframe(
    summary_df: pd.DataFrame,
    representative_filename: str,
    metrics: list[WorkbookMetricSummary],
) -> pd.DataFrame:
    converted = [
        tensile_builtin.TensileMetricSummary(
            label=metric.label,
            unit=metric.unit,
            mean=metric.mean,
            std=metric.std,
        )
        for metric in metrics
    ]
    return tensile_builtin.summary_sheet_dataframe(summary_df, representative_filename, tuple(converted))


def _plain_table_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    return tensile_builtin.plain_table_dataframe(dataframe)


__all__ = ["export_filtered_workbook_from_context"]
