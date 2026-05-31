from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.data_studio.builtin.tensile import (
    ALL_CURVES_SHEET,
    ALL_SPECIMENS_SHEET,
    METRIC_SPECS,
    REPRESENTATIVE_CURVE_SHEET,
    SUMMARY_SHEET,
    TensileMetricSummary,
    TensileRawSample,
    infer_group_name,
    parse_tensile_csv,
)
from src.data_studio.builtin.tensile import (
    export_tensile_replicate_workbook as _export_tensile_replicate_workbook,
)


@dataclass(frozen=True)
class TensileReplicateWorkbook:
    output_path: Path
    group_name: str
    preferred_sheet: str
    sheet_names: tuple[str, ...]
    sample_count: int
    representative_filename: str
    metrics: tuple[TensileMetricSummary, ...]
    warnings: tuple[str, ...]

def export_tensile_replicate_workbook(
    file_paths,
    output_path,
    *,
    group_name: str | None = None,
) -> TensileReplicateWorkbook:
    workbook = _export_tensile_replicate_workbook(file_paths, output_path, group_name=group_name)
    return TensileReplicateWorkbook(
        output_path=workbook.workbook_path,
        group_name=workbook.label,
        preferred_sheet=workbook.preferred_sheet,
        sheet_names=workbook.sheet_names,
        sample_count=workbook.parsed_sample_count,
        representative_filename=workbook.representative_filename,
        metrics=tuple(
            TensileMetricSummary(
                label=metric.label,
                unit=metric.unit,
                mean=metric.mean,
                std=metric.std,
            )
            for metric in workbook.metrics
        ),
        warnings=workbook.warnings,
    )


__all__ = [
    "ALL_CURVES_SHEET",
    "ALL_SPECIMENS_SHEET",
    "METRIC_SPECS",
    "REPRESENTATIVE_CURVE_SHEET",
    "SUMMARY_SHEET",
    "TensileMetricSummary",
    "TensileRawSample",
    "TensileReplicateWorkbook",
    "export_tensile_replicate_workbook",
    "infer_group_name",
    "parse_tensile_csv",
]
