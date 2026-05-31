from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

import numpy as np
import pandas as pd

from src.data_studio.builtin import tensile as tensile_builtin
from src.data_studio.import_templates_v2 import V2_PARSE_STRATEGY, build_workbook_from_template
from src.data_studio.ingest import read_preview_source
from src.data_studio.models import (
    DataStudioWorkbook,
    TemplateDefinition,
    TemplateFieldBinding,
    TemplateMatch,
    WorkbookMetricSummary,
    WorkbookSample,
)
from src.data_studio.template_store import load_template
from src.data_studio.workbook_constants import GENERIC_TEMPLATE_PARSE_STRATEGY


class ParsedStructuredSample(TypedDict):
    filename: str
    curve: pd.DataFrame
    metrics: dict[str, float | None]
    x_label: str
    y_label: str
    x_unit: str | None
    y_unit: str | None


def build_workbook(
    *,
    file_paths: Iterable[str | Path],
    output_path: str | Path,
    template_id: str,
    group_name: str | None = None,
) -> DataStudioWorkbook:
    template = load_template(template_id)
    if template.parse_strategy == "builtin:tensile":
        return tensile_builtin.export_tensile_replicate_workbook(file_paths, output_path, group_name=group_name)
    if template.parse_strategy == V2_PARSE_STRATEGY:
        return build_workbook_from_template(
            file_paths=list(file_paths),
            output_path=output_path,
            template=template,
            group_name=group_name,
        )
    if template.parse_strategy != GENERIC_TEMPLATE_PARSE_STRATEGY:
        raise ValueError(f"Unsupported Data Studio parse strategy: {template.parse_strategy}")

    paths = [Path(path).expanduser() for path in file_paths]
    if not paths:
        raise ValueError("Select at least one source file.")

    parsed_samples: list[ParsedStructuredSample] = []
    workbook_samples: list[WorkbookSample] = []
    warnings: list[str] = []
    for path in paths:
        try:
            parsed = parse_structured_sample(path, template)
            parsed_samples.append(parsed)
            workbook_samples.append(
                WorkbookSample(
                    id=str(path),
                    source_path=path,
                    filename=path.name,
                    parsed=True,
                    metrics=dict(parsed["metrics"]),
                )
            )
        except Exception as exc:
            warning = f"Skipped {path.name}: {exc}"
            warnings.append(warning)
            workbook_samples.append(
                WorkbookSample(
                    id=str(path),
                    source_path=path,
                    filename=path.name,
                    parsed=False,
                    warnings=(warning,),
                    exclusions=(str(exc),),
                )
            )

    if not parsed_samples:
        raise ValueError("No source files matched the selected Data Studio template.")

    resolved_group_name = (group_name or infer_group_name(paths)).strip() or "DataStudio_Group"
    metrics_df = _metrics_dataframe(parsed_samples)
    representative_index = _representative_index(metrics_df)
    representative = parsed_samples[representative_index]
    workbook_path = Path(output_path).expanduser().with_suffix(".xlsx")
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    metric_summaries = _metric_summaries(metrics_df)
    with pd.ExcelWriter(workbook_path) as writer:
        _metadata_sheet_dataframe(
            label=resolved_group_name,
            template_id=template.id,
            source_files=paths,
            warnings=warnings,
            representative_filename=str(representative["filename"]),
            sample_count=len(parsed_samples),
            metric_ids=[metric.id for metric in metric_summaries],
        ).to_excel(writer, sheet_name=tensile_builtin.METADATA_SHEET, header=False, index=False)
        _curve_table_dataframe(
            ((f"{resolved_group_name} representative", representative["curve"]),)
        ).to_excel(writer, sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET, header=False, index=False)
        _curve_table_dataframe((str(item["filename"]), item["curve"]) for item in parsed_samples).to_excel(
            writer,
            sheet_name=tensile_builtin.ALL_CURVES_SHEET,
            header=False,
            index=False,
        )
        _plain_table_dataframe(metrics_df).to_excel(
            writer,
            sheet_name=tensile_builtin.ALL_SPECIMENS_SHEET,
            header=False,
            index=False,
        )
        _summary_sheet_dataframe(
            metrics_df,
            representative_filename=str(representative["filename"]),
            metrics=metric_summaries,
        ).to_excel(writer, sheet_name=tensile_builtin.SUMMARY_SHEET, header=False, index=False)
        for metric in metric_summaries:
            _replicate_table_dataframe(
                group_name=resolved_group_name,
                value_label=metric.label,
                value_unit=metric.unit,
                values=metrics_df[f"{metric.label} ({metric.unit})"].dropna().tolist(),
            ).to_excel(writer, sheet_name=f"{metric.label}_Replicates", header=False, index=False)

    return DataStudioWorkbook(
        workbook_id=str(workbook_path),
        workbook_path=workbook_path,
        label=resolved_group_name,
        template_match=TemplateMatch(
            template_id=template.id,
            label=template.label,
            family=template.family,
            confidence=0.92,
            reasons=("Built with the selected Data Studio template.",),
            auto_selected=True,
        ),
        source_files=tuple(paths),
        sheet_names=tuple(_list_sheet_names(workbook_path)),
        preferred_sheet=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
        parsed_sample_count=len(parsed_samples),
        failed_sample_count=len(paths) - len(parsed_samples),
        representative_filename=str(representative["filename"]),
        metrics=tuple(metric_summaries),
        warnings=tuple(warnings),
        exclusions=tuple(sample.filename for sample in workbook_samples if not sample.parsed),
        samples=tuple(workbook_samples),
    )


def parse_structured_sample(path: str | Path, template: TemplateDefinition) -> ParsedStructuredSample:
    source_path = Path(path).expanduser()
    sheets, _encoding, _delimiter = read_preview_source(source_path)
    sheet_name = str(template.metadata.get("sheet_name", "")) or sheets[0][0]
    frame = next((frame for current_sheet, frame in sheets if current_sheet == sheet_name), None)
    if frame is None:
        raise ValueError(f"{source_path.name} does not contain the expected sheet {sheet_name!r}.")

    header_row_index = int(template.metadata.get("header_row_index", 0) or 0)
    unit_row_index = (
        int(template.metadata["unit_row_index"]) if template.metadata.get("unit_row_index") is not None else None
    )
    data_start_row_index = (
        int(template.metadata["data_start_row_index"])
        if template.metadata.get("data_start_row_index") is not None
        else header_row_index + 1
    )
    header_row = [_cell_text(value) for value in frame.iloc[header_row_index].tolist()]
    unit_row = (
        [_cell_text(value) for value in frame.iloc[unit_row_index].tolist()]
        if unit_row_index is not None
        else []
    )

    x_binding = _binding_by_role(template.field_bindings, "curve_x")
    y_binding = _binding_by_role(template.field_bindings, "curve_y")
    if x_binding is None or y_binding is None:
        raise ValueError("Template is missing curve_x or curve_y bindings.")

    x_column_index = _resolve_column_index(header_row, x_binding)
    y_column_index = _resolve_column_index(header_row, y_binding)
    if x_column_index is None or y_column_index is None:
        raise ValueError("Template bindings could not be matched to file columns.")

    pair = frame.iloc[data_start_row_index:, [x_column_index, y_column_index]].copy()
    pair.columns = ["x", "y"]
    pair = pair.apply(pd.to_numeric, errors="coerce").dropna(subset=["x", "y"]).reset_index(drop=True)
    if pair.empty:
        raise ValueError("Selected curve columns did not contain numeric data.")

    metrics: dict[str, float | None] = {}
    for binding in [binding for binding in template.field_bindings if binding.role == "metric"]:
        metric_column_index = _resolve_column_index(header_row, binding)
        if metric_column_index is None:
            if binding.optional:
                metrics[binding.label] = None
                continue
            raise ValueError(f"Metric binding {binding.label!r} could not be matched.")
        metric_values = pd.to_numeric(frame.iloc[:, metric_column_index], errors="coerce").dropna()
        metrics[binding.label] = float(metric_values.iloc[-1]) if not metric_values.empty else None

    x_unit = _unit_for_column(unit_row, x_column_index)
    y_unit = _unit_for_column(unit_row, y_column_index)
    return {
        "filename": source_path.name,
        "curve": pair,
        "metrics": metrics,
        "x_label": x_binding.label,
        "y_label": y_binding.label,
        "x_unit": x_unit,
        "y_unit": y_unit,
    }


def infer_group_name(file_paths: Iterable[str | Path]) -> str:
    return tensile_builtin.infer_group_name(file_paths)


def _binding_by_role(bindings: Iterable[TemplateFieldBinding], role: str) -> TemplateFieldBinding | None:
    for binding in bindings:
        if binding.role == role:
            return binding
    return None


def _resolve_column_index(header_row: list[str], binding: TemplateFieldBinding) -> int | None:
    if binding.column_index is not None and 0 <= binding.column_index < len(header_row):
        return binding.column_index
    if binding.column_name:
        lowered = binding.column_name.lower()
        for index, header in enumerate(header_row):
            if lowered == header.lower() or lowered in header.lower():
                return index
    return None


def _metrics_dataframe(parsed_samples: list[ParsedStructuredSample]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    metric_units: dict[str, str] = {}
    for sample in parsed_samples:
        row: dict[str, object] = {"Filename": sample["filename"]}
        for label, value in sample["metrics"].items():
            unit = "%" if "elong" in label.lower() else "a.u."
            metric_units[label] = unit
            row[f"{label} ({unit})"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _representative_index(summary_df: pd.DataFrame) -> int:
    if summary_df.empty:
        return 0
    scores = _representative_scores(summary_df)
    return int(scores.idxmin())


def _representative_scores(summary_df: pd.DataFrame) -> pd.Series:
    numeric_columns = [column for column in summary_df.columns if column != "Filename"]
    if not numeric_columns:
        return pd.Series(0.0, index=summary_df.index, dtype=float)
    scores = pd.Series(0.0, index=summary_df.index, dtype=float)
    contributions = pd.Series(0, index=summary_df.index, dtype=int)
    for column in numeric_columns:
        series = pd.to_numeric(summary_df[column], errors="coerce")
        std_value = float(series.std(ddof=1)) if series.notna().sum() > 1 else 0.0
        if std_value <= 0:
            continue
        z_squared = ((series - float(series.mean())) / std_value) ** 2
        scores = scores.add(z_squared.fillna(0.0), fill_value=0.0)
        contributions = contributions.add(series.notna().astype(int), fill_value=0).astype(int)
    if not (contributions > 0).any():
        return pd.Series(0.0, index=summary_df.index, dtype=float)
    return scores.where(contributions > 0, other=np.inf)


def _metric_summaries(summary_df: pd.DataFrame) -> list[WorkbookMetricSummary]:
    metrics: list[WorkbookMetricSummary] = []
    for column in summary_df.columns:
        if column == "Filename" or "(" not in column or ")" not in column:
            continue
        label, unit = column.rsplit("(", 1)
        unit = unit.rstrip(")")
        series = pd.to_numeric(summary_df[column], errors="coerce").dropna()
        metrics.append(
            WorkbookMetricSummary(
                id=label.strip(),
                label=label.strip(),
                unit=unit.strip(),
                mean=float(series.mean()) if not series.empty else None,
                std=float(series.std(ddof=1)) if len(series.index) > 1 else None,
            )
        )
    return metrics


def _unit_for_column(unit_row: list[str], column_index: int) -> str:
    if 0 <= column_index < len(unit_row):
        return unit_row[column_index]
    return ""


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


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


def _list_sheet_names(workbook_path: Path) -> tuple[str, ...]:
    from src.data_studio.io_utils import list_sheet_names

    return tuple(list_sheet_names(workbook_path))


__all__ = [
    "ParsedStructuredSample",
    "build_workbook",
    "infer_group_name",
    "parse_structured_sample",
]
