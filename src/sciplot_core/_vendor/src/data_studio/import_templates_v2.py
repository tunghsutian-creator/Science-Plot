from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
from src.data_studio.builtin import tensile as tensile_builtin
from src.data_studio.io_utils import list_sheet_names
from src.data_studio.models import (
    DataStudioWorkbook,
    TemplateApplyPreview,
    TemplateDefinition,
    TemplateFieldBinding,
    TemplateMatch,
    TemplatePreviewSegment,
    TemplateSegmentSelector,
    TemplateSourceFormat,
    WorkbookMetricSummary,
    WorkbookSample,
)
from src.rendering.source_table_preview import SourceTableSegment, detect_source_segments, read_source_sheets
from src.text_normalization import canonicalize_token, normalize_label, normalize_unit, slugify_label

V2_PARSE_STRATEGY = "table_template_v2"
OUTPUT_CURVE_METRICS = "curve_metrics"
OUTPUT_METRIC_TABLE = "metric_table"
OUTPUT_MATRIX_HEATMAP = "matrix_heatmap"
SUPPORTED_OUTPUT_KINDS = {OUTPUT_CURVE_METRICS, OUTPUT_METRIC_TABLE, OUTPUT_MATRIX_HEATMAP}
RHEOLOGY_FREQUENCY_LAYOUT = "rheology_frequency_multi_sheet"
RHEOLOGY_FREQUENCY_PREFERRED_SHEET = "Storage_Loss_Modulus"
RHEOLOGY_FREQUENCY_METRIC_SHEETS: dict[str, str] = {
    "storage_modulus": "Storage_Modulus",
    "loss_modulus": "Loss_Modulus",
    "loss_factor": "Loss_Factor",
    "complex_viscosity": "Complex_Viscosity",
    "complex_modulus": "Complex_Modulus",
}


@dataclass(frozen=True)
class LoadedSourceSheet:
    sheet_name: str
    frame: pd.DataFrame
    segments: tuple[SourceTableSegment, ...]


@dataclass(frozen=True)
class ParsedCurve:
    sample: str
    x_label: str
    y_label: str
    x_unit: str
    y_unit: str
    data: pd.DataFrame
    segment_id: str
    segment_label: str


@dataclass(frozen=True)
class ParsedTemplateFile:
    path: Path
    curves: tuple[ParsedCurve, ...] = ()
    metrics: dict[str, float | None] | None = None
    matrix_rows: pd.DataFrame | None = None
    warnings: tuple[str, ...] = ()


def create_template_definition(
    *,
    label: str,
    description: str,
    template_id: str | None,
    output_kind: str,
    comparison_enabled: bool | None = None,
    source_format: TemplateSourceFormat,
    segment_policy: str,
    segment_selectors: tuple[TemplateSegmentSelector, ...],
    field_bindings: tuple[TemplateFieldBinding, ...],
    match_conditions=(),
    metadata: dict[str, object] | None = None,
) -> TemplateDefinition:
    if output_kind not in SUPPORTED_OUTPUT_KINDS:
        raise ValueError(f"Unsupported Data Studio output kind: {output_kind}")
    resolved_comparison_enabled = _resolved_comparison_enabled(
        output_kind=output_kind,
        comparison_enabled=comparison_enabled,
    )
    if (
        output_kind == OUTPUT_CURVE_METRICS
        and resolved_comparison_enabled
        and not any(binding.role == "metric" for binding in field_bindings)
    ):
        raise ValueError("Enable Comparison needs at least one metric column binding.")
    trimmed_label = label.strip() or "Untitled Import Template"
    resolved_id = template_id or f"user/{slugify_label(trimmed_label) or 'template'}"
    resolved_metadata = {"created_by": "data_studio_import_template_v2"}
    resolved_metadata.update(metadata or {})
    return TemplateDefinition(
        version=2,
        id=resolved_id,
        label=trimmed_label,
        family="table_import",
        builtin=False,
        description=description.strip(),
        file_types=("csv", "txt", "tsv", "xls", "xlsx", "xlsm"),
        parse_strategy=V2_PARSE_STRATEGY,
        match_conditions=tuple(match_conditions),
        field_bindings=field_bindings,
        workbook_metric_ids=tuple(binding.label for binding in field_bindings if binding.role == "metric"),
        default_group_name_strategy="common_prefix",
        preferred_sheet_name=(
            tensile_builtin.REPRESENTATIVE_CURVE_SHEET
            if resolved_comparison_enabled
            else tensile_builtin.ALL_CURVES_SHEET
        ),
        output_kind=output_kind,
        comparison_enabled=resolved_comparison_enabled,
        source_format=source_format,
        segment_policy=segment_policy,
        segment_selectors=segment_selectors,
        metadata=resolved_metadata,
    )


def preview_template_apply(source_path: str | Path, template: TemplateDefinition) -> TemplateApplyPreview:
    missing = _missing_required_roles(template)
    if missing:
        return TemplateApplyPreview(
            template_id=template.id,
            output_kind=template.output_kind,
            parsed_sample_count=0,
            failed_sample_count=1,
            series_count=0,
            metric_count=0,
            matrix_row_count=0,
            missing_roles=tuple(missing),
            errors=(f"Missing required role bindings: {', '.join(missing)}.",),
        )
    try:
        parsed = parse_file_with_template(source_path, template)
    except Exception as exc:
        return TemplateApplyPreview(
            template_id=template.id,
            output_kind=template.output_kind,
            parsed_sample_count=0,
            failed_sample_count=1,
            series_count=0,
            metric_count=0,
            matrix_row_count=0,
            errors=(str(exc),),
        )
    segments: dict[str, TemplatePreviewSegment] = {}
    for curve in parsed.curves:
        current = segments.get(curve.segment_id)
        segments[curve.segment_id] = TemplatePreviewSegment(
            id=curve.segment_id,
            label=curve.segment_label,
            curve_count=(current.curve_count if current else 0) + 1,
            metric_count=(current.metric_count if current else 0),
            row_count=max(current.row_count if current else 0, len(curve.data.index)),
        )
    metric_count = len(parsed.metrics or {})
    matrix_rows = 0 if parsed.matrix_rows is None else len(parsed.matrix_rows.index)
    return TemplateApplyPreview(
        template_id=template.id,
        output_kind=template.output_kind,
        parsed_sample_count=1,
        failed_sample_count=0,
        series_count=len(parsed.curves),
        metric_count=metric_count,
        matrix_row_count=matrix_rows,
        warnings=parsed.warnings,
        segments=tuple(segments.values()),
    )


def parse_file_with_template(path: str | Path, template: TemplateDefinition) -> ParsedTemplateFile:
    source_path = Path(path).expanduser()
    loaded = _load_source_sheet(source_path, template)
    selected_segments = _select_segments(loaded, template)
    if not selected_segments:
        raise ValueError(f"{source_path.name} did not contain any selected import segments.")
    if template.output_kind == OUTPUT_MATRIX_HEATMAP:
        return _parse_matrix_file(source_path, template, loaded, selected_segments)
    curves: list[ParsedCurve] = []
    metrics: dict[str, float | None] = {}
    for segment in selected_segments:
        if template.output_kind == OUTPUT_CURVE_METRICS:
            curves.extend(_parse_curve_segment(source_path, template, loaded.frame, segment))
        metrics.update(_parse_metric_segment(template, loaded.frame, segment))
    if template.output_kind == OUTPUT_CURVE_METRICS and not curves:
        raise ValueError(f"{source_path.name} did not produce any valid curves.")
    if template.output_kind == OUTPUT_METRIC_TABLE and not metrics:
        raise ValueError(f"{source_path.name} did not produce any metric values.")
    return ParsedTemplateFile(path=source_path, curves=tuple(curves), metrics=metrics)


def build_workbook_from_template(
    *,
    file_paths: list[str | Path],
    output_path: str | Path,
    template: TemplateDefinition,
    group_name: str | None = None,
) -> DataStudioWorkbook:
    if template.output_kind not in SUPPORTED_OUTPUT_KINDS:
        raise ValueError(f"Unsupported Data Studio output kind: {template.output_kind}")
    paths = [Path(path).expanduser() for path in file_paths]
    if not paths:
        raise ValueError("Select at least one source file.")
    parsed_files: list[ParsedTemplateFile] = []
    samples: list[WorkbookSample] = []
    warnings: list[str] = []
    for path in paths:
        try:
            parsed = parse_file_with_template(path, template)
            parsed_files.append(parsed)
            samples.append(
                WorkbookSample(
                    id=str(path),
                    source_path=path,
                    filename=path.name,
                    parsed=True,
                    metrics=parsed.metrics or {},
                    warnings=parsed.warnings,
                )
            )
        except Exception as exc:
            warning = f"Skipped {path.name}: {exc}"
            warnings.append(warning)
            samples.append(
                WorkbookSample(
                    id=str(path),
                    source_path=path,
                    filename=path.name,
                    parsed=False,
                    warnings=(warning,),
                    exclusions=(str(exc),),
                )
            )
    if not parsed_files:
        raise ValueError("No source files matched the selected Data Studio template.")

    workbook_path = Path(output_path).expanduser().with_suffix(".xlsx")
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    label = (group_name or _infer_group_name(paths)).strip() or "DataStudio_Group"
    metrics_df = _metrics_dataframe(parsed_files)
    metric_summaries = _metric_summaries(metrics_df)
    curves = [curve for parsed in parsed_files for curve in parsed.curves]
    comparison_enabled = _resolved_comparison_enabled(
        output_kind=template.output_kind,
        comparison_enabled=template.comparison_enabled,
    )
    rheology_frequency_layout = _is_rheology_frequency_multi_sheet_template(template)
    representative_curve = curves[0] if curves and comparison_enabled and not rheology_frequency_layout else None
    rheology_frequency_frames = (
        _rheology_frequency_sheet_dataframes(curves, template=template) if curves and rheology_frequency_layout else ()
    )

    with pd.ExcelWriter(workbook_path) as writer:
        if rheology_frequency_frames:
            for sheet_name, frame in rheology_frequency_frames:
                frame.to_excel(
                    writer,
                    sheet_name=sheet_name,
                    header=False,
                    index=False,
                )
        elif curves:
            _curve_table_dataframe(curves).to_excel(
                writer,
                sheet_name=tensile_builtin.ALL_CURVES_SHEET,
                header=False,
                index=False,
            )
        if representative_curve is not None:
            _curve_table_dataframe([representative_curve]).to_excel(
                writer,
                sheet_name=tensile_builtin.REPRESENTATIVE_CURVE_SHEET,
                header=False,
                index=False,
            )
        if comparison_enabled and metric_summaries:
            tensile_builtin.plain_table_dataframe(metrics_df).to_excel(
                writer,
                sheet_name=tensile_builtin.ALL_SPECIMENS_SHEET,
                header=False,
                index=False,
            )
            _summary_dataframe(
                metrics_df,
                representative_curve.sample if representative_curve else "",
                metric_summaries,
            ).to_excel(
                writer,
                sheet_name=tensile_builtin.SUMMARY_SHEET,
                header=False,
                index=False,
            )
            for metric in metric_summaries:
                column_name = f"{metric.label} ({metric.unit})" if metric.unit else metric.label
                values = pd.to_numeric(metrics_df.get(column_name, pd.Series(dtype=float)), errors="coerce").dropna()
                if not values.empty:
                    tensile_builtin.replicate_table_dataframe(
                        group_name=label,
                        value_label=metric.label,
                        value_unit=metric.unit,
                        values=values.tolist(),
                    ).to_excel(writer, sheet_name=f"{metric.label}_Replicates", header=False, index=False)
        if template.output_kind == OUTPUT_MATRIX_HEATMAP:
            matrix_frames = [parsed.matrix_rows for parsed in parsed_files if parsed.matrix_rows is not None]
            if matrix_frames:
                pd.concat(matrix_frames, ignore_index=True).to_excel(
                    writer,
                    sheet_name="Heatmap",
                    header=False,
                    index=False,
                )

    return DataStudioWorkbook(
        workbook_id=str(workbook_path),
        workbook_path=workbook_path,
        label=label,
        template_match=TemplateMatch(
            template_id=template.id,
            label=template.label,
            family=template.family,
            confidence=0.92,
            reasons=("Built with the selected Data Studio import template.",),
            auto_selected=True,
        ),
        source_files=tuple(paths),
        sheet_names=tuple(list_sheet_names(workbook_path)),
        preferred_sheet=_preferred_workbook_sheet(
            template=template,
            representative_curve=representative_curve,
            rheology_frequency_frames=rheology_frequency_frames,
        ),
        parsed_sample_count=len(parsed_files),
        failed_sample_count=len(paths) - len(parsed_files),
        representative_filename=representative_curve.sample if representative_curve is not None else "",
        metrics=tuple(metric_summaries),
        warnings=tuple(warnings),
        exclusions=tuple(sample.filename for sample in samples if not sample.parsed),
        samples=tuple(samples),
    )


def _load_source_sheet(source_path: Path, template: TemplateDefinition) -> LoadedSourceSheet:
    sheets, _encoding, _delimiter = read_source_sheets(
        source_path,
        encoding=template.source_format.encoding,
        delimiter=template.source_format.delimiter,
    )
    preferred_sheet = template.source_format.sheet_name
    if preferred_sheet:
        sheet = next((item for item in sheets if item[0] == preferred_sheet), None)
        if sheet is None:
            raise ValueError(f"{source_path.name} does not contain sheet {preferred_sheet!r}.")
    else:
        sheet = sheets[0]
    sheet_name, frame = sheet
    return LoadedSourceSheet(sheet_name=sheet_name, frame=frame, segments=detect_source_segments(sheet_name, frame))


def _select_segments(loaded: LoadedSourceSheet, template: TemplateDefinition) -> tuple[SourceTableSegment, ...]:
    if not loaded.segments:
        selector = template.segment_selectors[0] if template.segment_selectors else None
        fallback = SourceTableSegment(
            id=f"{loaded.sheet_name}::table",
            sheet_name=loaded.sheet_name,
            label=selector.label if selector is not None else loaded.sheet_name,
            result_label=None,
            interval_index=None,
            start_row=selector.start_row if selector is not None and selector.start_row is not None else 0,
            end_row=(
                selector.end_row
                if selector is not None and selector.end_row is not None
                else loaded.frame.shape[0] - 1
            ),
            header_row_index=(
                selector.header_row_index
                if selector is not None and selector.header_row_index is not None
                else 0
            ),
            unit_row_index=selector.unit_row_index if selector is not None else None,
            data_start_row_index=(
                selector.data_start_row_index
                if selector is not None and selector.data_start_row_index is not None
                else 1
            ),
            column_count=loaded.frame.shape[1],
            row_count=loaded.frame.shape[0],
        )
        return (fallback,)
    if not template.segment_selectors:
        return loaded.segments if template.segment_policy == "series_per_segment" else loaded.segments[:1]
    selected: list[SourceTableSegment] = []
    for selector in template.segment_selectors:
        match = _match_segment(loaded.segments, selector)
        if match is not None and match not in selected:
            selected.append(match)
    return tuple(selected)


def _match_segment(
    segments: tuple[SourceTableSegment, ...],
    selector: TemplateSegmentSelector,
) -> SourceTableSegment | None:
    for segment in segments:
        if selector.result_label and selector.interval_index is not None:
            if segment.result_label == selector.result_label and segment.interval_index == selector.interval_index:
                return segment
        if selector.result_label and selector.interval_index is None and segment.result_label == selector.result_label:
            return segment
        if segment.id == selector.id:
            return segment
    return None


def _missing_required_roles(template: TemplateDefinition) -> list[str]:
    roles = {binding.role for binding in template.field_bindings if not binding.optional}
    if template.output_kind == OUTPUT_CURVE_METRICS:
        required = ["curve_x", "curve_y"]
        if template.comparison_enabled:
            required.append("metric")
        return [role for role in required if role not in roles]
    if template.output_kind == OUTPUT_METRIC_TABLE:
        return ["metric"] if "metric" not in roles else []
    if template.output_kind == OUTPUT_MATRIX_HEATMAP:
        return [role for role in ("matrix_x", "matrix_y", "matrix_z") if role not in roles]
    return []


def _binding_columns(
    frame: pd.DataFrame,
    segment: SourceTableSegment,
    bindings: list[TemplateFieldBinding],
) -> dict[str, int]:
    header_row = _row_texts(frame, segment.header_row_index)
    resolved: dict[str, int] = {}
    for binding in bindings:
        column = _resolve_column(header_row, binding)
        if column is None:
            if binding.optional:
                continue
            raise ValueError(f"Binding {binding.label!r} could not be matched to a source column.")
        resolved[binding.id] = column
    return resolved


def _parse_curve_segment(
    source_path: Path,
    template: TemplateDefinition,
    frame: pd.DataFrame,
    segment: SourceTableSegment,
) -> list[ParsedCurve]:
    x_binding = _first_binding(template, "curve_x")
    y_bindings = [binding for binding in template.field_bindings if binding.role == "curve_y"]
    if x_binding is None or not y_bindings:
        raise ValueError("Template is missing curve X/Y bindings.")
    binding_columns = _binding_columns(frame, segment, [x_binding, *y_bindings])
    x_column = binding_columns[x_binding.id]
    data_start = segment.data_start_row_index or ((segment.header_row_index or segment.start_row) + 1)
    data_end = segment.end_row + 1
    curves: list[ParsedCurve] = []
    for y_binding in y_bindings:
        y_column = binding_columns[y_binding.id]
        pair = frame.iloc[data_start:data_end, [x_column, y_column]].copy()
        pair.columns = ["x", "y"]
        pair = pair.apply(pd.to_numeric, errors="coerce").dropna(subset=["x", "y"]).reset_index(drop=True)
        if pair.empty:
            if y_binding.optional:
                continue
            raise ValueError(f"Curve binding {y_binding.label!r} did not contain numeric X/Y data.")
        x_label = x_binding.label or _cell(frame, segment.header_row_index, x_column) or "X"
        y_label = y_binding.label or _cell(frame, segment.header_row_index, y_column) or "Y"
        sample = (y_binding.sample_name or "").strip() or source_path.stem
        curves.append(
            ParsedCurve(
                sample=sample,
                x_label=normalize_label(x_label) or "X",
                y_label=normalize_label(y_label) or "Y",
                x_unit=normalize_unit(x_binding.unit_hint or _cell(frame, segment.unit_row_index, x_column)),
                y_unit=normalize_unit(y_binding.unit_hint or _cell(frame, segment.unit_row_index, y_column)),
                data=pair,
                segment_id=segment.id,
                segment_label=segment.label,
            )
        )
    return curves


def _parse_metric_segment(
    template: TemplateDefinition,
    frame: pd.DataFrame,
    segment: SourceTableSegment,
) -> dict[str, float | None]:
    metric_bindings = [binding for binding in template.field_bindings if binding.role == "metric"]
    if not metric_bindings:
        return {}
    binding_columns = _binding_columns(frame, segment, metric_bindings)
    data_start = segment.data_start_row_index or ((segment.header_row_index or segment.start_row) + 1)
    data_end = segment.end_row + 1
    metrics: dict[str, float | None] = {}
    for binding in metric_bindings:
        column = binding_columns.get(binding.id)
        if column is None:
            metrics[binding.label] = None
            continue
        numeric = pd.to_numeric(frame.iloc[data_start:data_end, column], errors="coerce").dropna()
        metrics[binding.label] = float(numeric.iloc[-1]) if not numeric.empty else None
    return metrics


def _parse_matrix_file(
    source_path: Path,
    template: TemplateDefinition,
    loaded: LoadedSourceSheet,
    segments: tuple[SourceTableSegment, ...],
) -> ParsedTemplateFile:
    segment = segments[0]
    roles = {
        "matrix_x": _first_binding(template, "matrix_x"),
        "matrix_y": _first_binding(template, "matrix_y"),
        "matrix_z": _first_binding(template, "matrix_z"),
    }
    if any(binding is None for binding in roles.values()):
        raise ValueError("Template is missing matrix X/Y/Z bindings.")
    bindings = [binding for binding in roles.values() if binding is not None]
    binding_columns = _binding_columns(loaded.frame, segment, bindings)
    data_start = segment.data_start_row_index or ((segment.header_row_index or segment.start_row) + 1)
    data_end = segment.end_row + 1
    ordered = loaded.frame.iloc[
        data_start:data_end,
        [binding_columns[binding.id] for binding in bindings],
    ].copy()
    ordered.columns = ["x", "y", "z"]
    ordered["z"] = pd.to_numeric(ordered["z"], errors="coerce")
    ordered = ordered.dropna(subset=["z"]).reset_index(drop=True)
    if ordered.empty:
        raise ValueError(f"{source_path.name} did not contain any heatmap Z values.")
    rows = pd.concat(
        [
            pd.DataFrame([["x", "y", "z"], [bindings[0].label, bindings[1].label, bindings[2].label], [
                bindings[0].unit_hint or "",
                bindings[1].unit_hint or "",
                bindings[2].unit_hint or "",
            ]]),
            ordered,
        ],
        ignore_index=True,
    )
    return ParsedTemplateFile(path=source_path, matrix_rows=rows)


def _first_binding(template: TemplateDefinition, role: str) -> TemplateFieldBinding | None:
    return next((binding for binding in template.field_bindings if binding.role == role), None)


def _row_texts(frame: pd.DataFrame, row_index: int | None) -> list[str]:
    if row_index is None or row_index < 0 or row_index >= frame.shape[0]:
        return []
    return [_cell_text(value) for value in frame.iloc[row_index].tolist()]


def _cell(frame: pd.DataFrame, row_index: int | None, column_index: int) -> str:
    if row_index is None or row_index < 0 or row_index >= frame.shape[0] or column_index >= frame.shape[1]:
        return ""
    return _cell_text(frame.iloc[row_index, column_index])


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip().strip('"').strip("[]()")


def _resolve_column(header_row: list[str], binding: TemplateFieldBinding) -> int | None:
    if binding.column_index is not None and binding.column_index >= 0:
        return binding.column_index
    if binding.column_name:
        lowered = binding.column_name.lower()
        for index, header in enumerate(header_row):
            candidate = header.lower()
            if lowered == candidate or lowered in candidate:
                return index
    return None


def _metrics_dataframe(parsed_files: list[ParsedTemplateFile]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for parsed in parsed_files:
        row: dict[str, object] = {"Filename": parsed.path.name}
        for label, value in (parsed.metrics or {}).items():
            row[label] = value
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _metric_summaries(summary_df: pd.DataFrame) -> list[WorkbookMetricSummary]:
    metrics: list[WorkbookMetricSummary] = []
    for column in summary_df.columns:
        if column == "Filename":
            continue
        label, unit = _split_metric_column(column)
        series = pd.to_numeric(summary_df[column], errors="coerce").dropna()
        metrics.append(
            WorkbookMetricSummary(
                id=label,
                label=label,
                unit=unit,
                mean=float(series.mean()) if not series.empty else None,
                std=float(series.std(ddof=1)) if len(series.index) > 1 else None,
            )
        )
    return metrics


def _split_metric_column(column: str) -> tuple[str, str]:
    if "(" in column and column.endswith(")"):
        label, unit = column.rsplit("(", 1)
        return label.strip(), unit.rstrip(")").strip()
    return column.strip(), ""


def _curve_table_dataframe(curves: list[ParsedCurve]) -> pd.DataFrame:
    if not curves:
        return pd.DataFrame()
    axis_row: list[object] = []
    unit_row: list[object] = []
    sample_row: list[object] = []
    max_rows = max(len(curve.data.index) for curve in curves)
    for curve in curves:
        axis_row.extend([curve.x_label, curve.y_label])
        unit_row.extend([curve.x_unit, curve.y_unit])
        sample_row.extend([curve.sample, curve.sample])
    rows: list[list[object]] = [axis_row, unit_row, sample_row]
    for row_index in range(max_rows):
        row: list[object] = []
        for curve in curves:
            if row_index < len(curve.data.index):
                row.extend([float(curve.data.iloc[row_index]["x"]), float(curve.data.iloc[row_index]["y"])])
            else:
                row.extend(["", ""])
        rows.append(row)
    return pd.DataFrame(rows)


def _is_rheology_frequency_multi_sheet_template(template: TemplateDefinition) -> bool:
    return str(template.metadata.get("figure_layout") or "") == RHEOLOGY_FREQUENCY_LAYOUT


def _preferred_workbook_sheet(
    *,
    template: TemplateDefinition,
    representative_curve: ParsedCurve | None,
    rheology_frequency_frames: tuple[tuple[str, pd.DataFrame], ...],
) -> str:
    if template.output_kind == OUTPUT_MATRIX_HEATMAP:
        return "Heatmap"
    if rheology_frequency_frames:
        sheet_names = {sheet_name for sheet_name, _frame in rheology_frequency_frames}
        if RHEOLOGY_FREQUENCY_PREFERRED_SHEET in sheet_names:
            return RHEOLOGY_FREQUENCY_PREFERRED_SHEET
        return rheology_frequency_frames[0][0]
    if representative_curve is not None:
        return tensile_builtin.REPRESENTATIVE_CURVE_SHEET
    return tensile_builtin.ALL_CURVES_SHEET


def _rheology_frequency_sheet_dataframes(
    curves: list[ParsedCurve],
    *,
    template: TemplateDefinition,
) -> tuple[tuple[str, pd.DataFrame], ...]:
    grouped = _rheology_frequency_curves_by_sample(curves)
    if not grouped:
        return ()
    sample_order = _rheology_frequency_sample_order(grouped, template=template)
    frames: list[tuple[str, pd.DataFrame]] = []
    for metric_key, sheet_name in RHEOLOGY_FREQUENCY_METRIC_SHEETS.items():
        metric_curves = [grouped[sample][metric_key] for sample in sample_order if metric_key in grouped[sample]]
        if metric_curves:
            frames.append((sheet_name, _curve_table_dataframe(_sort_curve_points_by_x(metric_curves))))
    combined = _rheology_frequency_storage_loss_curves(grouped, sample_order)
    if combined:
        frames.append((RHEOLOGY_FREQUENCY_PREFERRED_SHEET, _curve_table_dataframe(combined)))
    return tuple(frames)


def _rheology_frequency_curves_by_sample(
    curves: list[ParsedCurve],
) -> dict[str, dict[str, ParsedCurve]]:
    grouped: dict[str, dict[str, ParsedCurve]] = {}
    for curve in curves:
        metric_key = _rheology_frequency_metric_key(curve)
        if metric_key is None:
            continue
        grouped.setdefault(curve.sample, {})[metric_key] = curve
    return grouped


def _rheology_frequency_metric_key(curve: ParsedCurve) -> str | None:
    label = canonicalize_token(curve.y_label)
    if label in {"storage modulus", "g'"}:
        return "storage_modulus"
    if label in {"loss modulus", 'g"'}:
        return "loss_modulus"
    if label in {"loss factor", "tanδ", "tand", "tan delta"}:
        return "loss_factor"
    if label in {"complex viscosity", "|η.|", "eta", "eta*"}:
        return "complex_viscosity"
    if label in {"complex modulus", "complex shear modulus", "|g*|", "g*"}:
        return "complex_modulus"
    return None


def _rheology_frequency_sample_order(
    grouped: dict[str, dict[str, ParsedCurve]],
    *,
    template: TemplateDefinition,
) -> list[str]:
    sort_config = template.metadata.get("sample_sort")
    sort_direction = "desc"
    if isinstance(sort_config, dict):
        sort_direction = str(sort_config.get("direction") or sort_direction).lower()
    storage_curves = {
        sample: metrics["storage_modulus"]
        for sample, metrics in grouped.items()
        if "storage_modulus" in metrics
    }
    reference_x = _rheology_frequency_reference_x(tuple(storage_curves.values()))

    def sort_key(sample: str) -> tuple[float, tuple[object, ...]]:
        curve = storage_curves.get(sample)
        y_value = _rheology_frequency_y_at_reference(curve, reference_x) if curve is not None else None
        if y_value is None:
            sortable = float("inf")
        else:
            sortable = -float(y_value) if sort_direction != "asc" else float(y_value)
        return sortable, _natural_sort_key(sample)

    return sorted(grouped, key=sort_key)


def _rheology_frequency_reference_x(curves: tuple[ParsedCurve, ...]) -> float | None:
    if not curves:
        return None
    common_values: set[float] | None = None
    for curve in curves:
        values = {
            round(float(value), 9)
            for value in pd.to_numeric(curve.data["x"], errors="coerce").dropna().tolist()
            if float(value) > 0
        }
        common_values = values if common_values is None else common_values & values
    if common_values:
        return max(common_values)
    maxima = [
        float(pd.to_numeric(curve.data["x"], errors="coerce").dropna().max())
        for curve in curves
        if not pd.to_numeric(curve.data["x"], errors="coerce").dropna().empty
    ]
    return max(maxima) if maxima else None


def _rheology_frequency_y_at_reference(curve: ParsedCurve | None, reference_x: float | None) -> float | None:
    if curve is None or curve.data.empty:
        return None
    data = curve.data.copy()
    data["x"] = pd.to_numeric(data["x"], errors="coerce")
    data["y"] = pd.to_numeric(data["y"], errors="coerce")
    data = data.dropna(subset=["x", "y"])
    if data.empty:
        return None
    if reference_x is None:
        row = data.loc[data["x"].idxmax()]
        return float(row["y"])
    nearest_index = (data["x"] - reference_x).abs().idxmin()
    return float(data.loc[nearest_index, "y"])


def _rheology_frequency_storage_loss_curves(
    grouped: dict[str, dict[str, ParsedCurve]],
    sample_order: list[str],
) -> list[ParsedCurve]:
    combined: list[ParsedCurve] = []
    for sample in sample_order:
        metrics = grouped[sample]
        storage = metrics.get("storage_modulus")
        loss = metrics.get("loss_modulus")
        if storage is not None:
            combined.append(replace(_sort_curve_points_by_x([storage])[0], sample=f"{sample} G'"))
        if loss is not None:
            combined.append(replace(_sort_curve_points_by_x([loss])[0], sample=f'{sample} G"'))
    return combined


def _sort_curve_points_by_x(curves: list[ParsedCurve]) -> list[ParsedCurve]:
    sorted_curves: list[ParsedCurve] = []
    for curve in curves:
        data = curve.data.copy()
        data["x"] = pd.to_numeric(data["x"], errors="coerce")
        data["y"] = pd.to_numeric(data["y"], errors="coerce")
        data = data.dropna(subset=["x", "y"]).sort_values("x", kind="mergesort").reset_index(drop=True)
        sorted_curves.append(replace(curve, data=data))
    return sorted_curves


def _natural_sort_key(value: str) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", value.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _summary_dataframe(
    summary_df: pd.DataFrame,
    representative_filename: str,
    metrics: list[WorkbookMetricSummary],
) -> pd.DataFrame:
    rows: list[list[object]] = [["Item", "Unit", "Mean", "Std", "Representative File"]]
    for index, metric in enumerate(metrics):
        rows.append([metric.label, metric.unit, metric.mean, metric.std, representative_filename if index == 0 else ""])
    rows.append([])
    rows.append(["Specimens", len(summary_df.index), "", "", ""])
    return pd.DataFrame(rows)


def _infer_group_name(paths: list[Path]) -> str:
    if not paths:
        return "DataStudio_Group"
    return tensile_builtin.infer_group_name(paths)


def _resolved_comparison_enabled(*, output_kind: str, comparison_enabled: bool | None) -> bool:
    if output_kind != OUTPUT_CURVE_METRICS:
        return True
    if comparison_enabled is None:
        return True
    return bool(comparison_enabled)
