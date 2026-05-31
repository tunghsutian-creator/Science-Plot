from __future__ import annotations

import csv
import hashlib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import plot_style
from src.data_loader import CurveSeries, ReplicateGroup, load_curve_table, load_replicate_table, read_raw_table
from src.data_studio.io_utils import ensure_input_path, list_sheet_names
from src.data_studio.models import (
    ComparisonRecipe,
    DataStudioFigureOutput,
    DataStudioWorkbook,
    TemplateMatch,
    WorkbookMetricSummary,
    WorkbookSample,
)
from src.plot_style import save_pdf
from src.plotting_families.curve_family import plot_curves
from src.plotting_families.stats_family import plot_bar, plot_box, plot_violin
from src.text_normalization import slugify_label

TENSILE_TEMPLATE_ID = "builtin/tensile"
RAW_CSV_ENCODINGS = (
    "gb18030",
    "gbk",
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "latin-1",
)
REPRESENTATIVE_CURVE_SHEET = "Representative_Curve"
ALL_CURVES_SHEET = "All_Curves"
SUMMARY_SHEET = "Summary"
ALL_SPECIMENS_SHEET = "All_Specimens"
METADATA_SHEET = "DataStudio_Metadata"
METRIC_SPECS = (
    ("Strength", "MPa", ("拉伸应力", "最大值", "力"), ("最大应力",)),
    ("Modulus", "MPa", ("模量",), ("modulus",)),
    ("Elongation", "%", ("拉伸应变", "断裂"), ("断裂应变", "break strain")),
)
METRIC_NAMES = tuple(label for label, _, _, _ in METRIC_SPECS)
REQUIRED_TENSILE_WORKBOOK_SHEETS = frozenset(
    {
        REPRESENTATIVE_CURVE_SHEET,
        SUMMARY_SHEET,
        *(f"{label}_Replicates" for label in METRIC_NAMES),
    }
)
COMPARISON_CURVE_FILENAME = "representative_curve_compare.pdf"


@dataclass(frozen=True)
class TensileMetricSummary:
    label: str
    unit: str
    mean: float | None
    std: float | None


@dataclass(frozen=True)
class TensileRawSample:
    source_path: Path
    filename: str
    strength: float | None
    modulus: float | None
    elongation: float | None
    curve: pd.DataFrame


@dataclass(frozen=True)
class LoadedTensileWorkbookData:
    workbook_path: Path
    base_label: str
    sheet_names: tuple[str, ...]
    sample_count: int
    representative_filename: str
    representative_curve: CurveSeries
    metrics: tuple[TensileMetricSummary, ...]
    replicate_groups: dict[str, ReplicateGroup]
    warnings: tuple[str, ...]
    source_files: tuple[Path, ...]


def infer_group_name(file_paths: Iterable[str | Path]) -> str:
    paths = [Path(path) for path in file_paths]
    stems = [path.stem for path in paths if path.stem]
    if not stems:
        return "Tensile_Group"
    prefix = os.path.commonprefix(stems).strip()
    prefix = re.sub(r"[_\-\s]+$", "", prefix)
    if prefix:
        return prefix
    parent_name = paths[0].parent.name.strip()
    if parent_name:
        return parent_name
    return stems[0]


def default_template_match() -> TemplateMatch:
    return TemplateMatch(
        template_id=TENSILE_TEMPLATE_ID,
        label="Tensile",
        family="tensile",
        confidence=0.99,
        reasons=("Matched the built-in tensile export structure.",),
        auto_selected=True,
    )


def export_tensile_replicate_workbook(
    file_paths: Iterable[str | Path],
    output_path: str | Path,
    *,
    group_name: str | None = None,
) -> DataStudioWorkbook:
    paths = [Path(path).expanduser() for path in file_paths]
    if not paths:
        raise ValueError("Select at least one raw tensile CSV file.")

    parsed_samples: list[TensileRawSample] = []
    warnings: list[str] = []
    workbook_samples: list[WorkbookSample] = []

    for path in paths:
        try:
            sample = parse_tensile_csv(path)
            parsed_samples.append(sample)
            workbook_samples.append(
                WorkbookSample(
                    id=str(path),
                    source_path=path,
                    filename=path.name,
                    parsed=True,
                    metrics={
                        "Strength": sample.strength,
                        "Modulus": sample.modulus,
                        "Elongation": sample.elongation,
                    },
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
        raise ValueError(
            "No tensile CSV files could be parsed successfully. Confirm that "
            "the files come from the same tensile export format."
        )

    resolved_group_name = (group_name or infer_group_name(paths)).strip() or "Tensile_Group"
    summary_df = _build_summary_dataframe(parsed_samples)
    representative_index = _representative_index(summary_df)
    representative_sample = parsed_samples[representative_index]

    workbook_path = Path(output_path).expanduser()
    if workbook_path.suffix.lower() != ".xlsx":
        workbook_path = workbook_path.with_suffix(".xlsx")
    workbook_path.parent.mkdir(parents=True, exist_ok=True)

    metrics = _metric_summaries(summary_df)
    sheets = _workbook_sheets(parsed_samples, summary_df, representative_sample, resolved_group_name, metrics)
    with pd.ExcelWriter(workbook_path) as writer:
        for sheet_name, dataframe in sheets:
            dataframe.to_excel(writer, sheet_name=sheet_name, header=False, index=False)

    return DataStudioWorkbook(
        workbook_id=str(workbook_path),
        workbook_path=workbook_path,
        label=resolved_group_name,
        template_match=default_template_match(),
        source_files=tuple(paths),
        sheet_names=tuple(sheet_name for sheet_name, _ in sheets),
        preferred_sheet=REPRESENTATIVE_CURVE_SHEET,
        parsed_sample_count=len(parsed_samples),
        failed_sample_count=len(paths) - len(parsed_samples),
        representative_filename=representative_sample.filename,
        metrics=tuple(
            WorkbookMetricSummary(
                id=metric.label,
                label=metric.label,
                unit=metric.unit,
                mean=metric.mean,
                std=metric.std,
            )
            for metric in metrics
        ),
        warnings=tuple(warnings),
        exclusions=tuple(
            sample.filename for sample in workbook_samples if not sample.parsed
        ),
        samples=tuple(workbook_samples),
    )


def parse_tensile_csv(path: str | Path) -> TensileRawSample:
    file_path = Path(path).expanduser()
    rows = _read_csv_rows(file_path)
    scalar_header_index = _find_scalar_header_index(rows)
    if scalar_header_index is None:
        raise ValueError("Could not find the scalar header row in Results Table 1.")

    scalar_headers = rows[scalar_header_index]
    scalar_values = _find_scalar_value_row(rows, scalar_header_index)
    if scalar_values is None:
        raise ValueError("Could not find a valid numeric row in Results Table 1.")

    metric_values = {
        "strength": _extract_scalar_value(
            scalar_headers,
            scalar_values,
            primary_keywords=("拉伸应力", "最大值", "力"),
            fallback_keywords=(("最大应力",), ("tensile stress", "maximum"), ("max stress",)),
        ),
        "modulus": _extract_scalar_value(
            scalar_headers,
            scalar_values,
            primary_keywords=("模量",),
            fallback_keywords=(("modulus",),),
        ),
        "elongation": _extract_scalar_value(
            scalar_headers,
            scalar_values,
            primary_keywords=("拉伸应变", "断裂"),
            fallback_keywords=(("断裂应变",), ("break strain",), ("tensile strain", "break")),
        ),
    }

    curve = _extract_curve_dataframe(rows, start_index=scalar_header_index)
    if curve.empty:
        raise ValueError("No stress-strain curve was found in Results Table 2.")

    return TensileRawSample(
        source_path=file_path,
        filename=file_path.name,
        strength=metric_values["strength"],
        modulus=metric_values["modulus"],
        elongation=metric_values["elongation"],
        curve=curve,
    )


def inspect_tensile_workbook(workbook_path: str | Path) -> DataStudioWorkbook:
    loaded = load_tensile_workbook(workbook_path)
    return DataStudioWorkbook(
        workbook_id=str(loaded.workbook_path),
        workbook_path=loaded.workbook_path,
        label=loaded.base_label,
        template_match=default_template_match(),
        source_files=loaded.source_files,
        sheet_names=loaded.sheet_names,
        preferred_sheet=REPRESENTATIVE_CURVE_SHEET,
        parsed_sample_count=loaded.sample_count,
        failed_sample_count=0,
        representative_filename=loaded.representative_filename,
        metrics=tuple(
            WorkbookMetricSummary(
                id=metric.label,
                label=metric.label,
                unit=metric.unit,
                mean=metric.mean,
                std=metric.std,
            )
            for metric in loaded.metrics
        ),
        warnings=loaded.warnings,
        samples=(),
    )


def load_tensile_workbook(workbook_path: str | Path) -> LoadedTensileWorkbookData:
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

    metadata = load_metadata_sheet(path)
    source_files = tuple(Path(item) for item in metadata.get("source_files", ()))
    warnings = tuple(str(item) for item in metadata.get("warnings", ()))

    return LoadedTensileWorkbookData(
        workbook_path=path,
        base_label=infer_workbook_label(path),
        sheet_names=sheet_names,
        sample_count=sample_count,
        representative_filename=representative_filename,
        representative_curve=representative_curves[0],
        metrics=tuple(metrics),
        replicate_groups=replicate_groups,
        warnings=warnings,
        source_files=source_files,
    )


def load_metadata_sheet(path: Path) -> dict[str, Any]:
    if METADATA_SHEET not in list_sheet_names(path):
        return {}
    raw = read_raw_table(path, sheet_name=METADATA_SHEET).fillna("")
    payload: dict[str, Any] = {}
    for row_index in range(raw.shape[0]):
        key = cell_text(raw.iloc[row_index, 0]) if raw.shape[1] > 0 else ""
        value = cell_text(raw.iloc[row_index, 1]) if raw.shape[1] > 1 else ""
        if key and value:
            if key in {"source_files", "warnings"}:
                payload[key] = tuple(item for item in value.split(" | ") if item)
            else:
                payload[key] = value
    return payload


def tensile_comparison_recipes(workbooks: list[LoadedTensileWorkbookData]) -> tuple[ComparisonRecipe, ...]:
    recipes: list[ComparisonRecipe] = [
        ComparisonRecipe(
            id="representative_curve",
            label="Representative Curve Compare",
            category="curve",
            template_id="curve",
            sheet_name=REPRESENTATIVE_CURVE_SHEET,
        )
    ]
    for metric_name in METRIC_NAMES:
        recipes.extend(
            (
                ComparisonRecipe(
                    id=f"{metric_name.lower()}_bar",
                    label=f"{metric_name} Bar Compare",
                    category="metric",
                    template_id="bar",
                    sheet_name=f"{metric_name}_Replicates",
                    metric_id=metric_name,
                ),
                ComparisonRecipe(
                    id=f"{metric_name.lower()}_box",
                    label=f"{metric_name} Box Compare",
                    category="metric",
                    template_id="box",
                    sheet_name=f"{metric_name}_Replicates",
                    metric_id=metric_name,
                ),
                ComparisonRecipe(
                    id=f"{metric_name.lower()}_violin",
                    label=f"{metric_name} Violin Compare",
                    category="metric",
                    template_id="violin",
                    sheet_name=f"{metric_name}_Replicates",
                    metric_id=metric_name,
                ),
                ComparisonRecipe(
                    id=f"{metric_name.lower()}_box_strip",
                    label=f"{metric_name} Box + Strip Compare",
                    category="metric",
                    template_id="box_strip",
                    sheet_name=f"{metric_name}_Replicates",
                    metric_id=metric_name,
                ),
            )
        )
    return tuple(recipes)


def export_tensile_comparison_bundle(
    workbook_paths: list[str | Path],
    output_dir: str | Path,
) -> tuple[Path, Path, tuple[ComparisonRecipe, ...], tuple[DataStudioFigureOutput, ...]]:
    loaded_sources = [load_tensile_workbook(path) for path in workbook_paths]
    if len(loaded_sources) < 2:
        raise ValueError("Tensile comparison requires at least 2 prepared workbooks.")

    labels = dedupe_labels(source.base_label for source in loaded_sources)
    validate_metric_units(loaded_sources)
    validate_curve_axes(loaded_sources)

    parent_dir = Path(output_dir).expanduser()
    parent_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = parent_dir / bundle_dir_name(labels)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    comparison_workbook_path = bundle_dir / f"{bundle_dir.name}.xlsx"

    with pd.ExcelWriter(comparison_workbook_path) as writer:
        representative_curve_dataframe(loaded_sources, labels).to_excel(
            writer,
            sheet_name=REPRESENTATIVE_CURVE_SHEET,
            header=False,
            index=False,
        )
        for metric_name, metric_unit in ((label, unit) for label, unit, _, _ in METRIC_SPECS):
            comparison_replicate_dataframe(
                metric_name,
                metric_unit,
                loaded_sources,
                labels,
            ).to_excel(
                writer,
                sheet_name=f"{metric_name}_Replicates",
                header=False,
                index=False,
            )
        comparison_summary_dataframe(loaded_sources, labels).to_excel(
            writer,
            sheet_name=SUMMARY_SHEET,
            header=False,
            index=False,
        )
        _metadata_sheet_dataframe(
            label=" vs ".join(labels),
            source_files=[Path(path) for path in workbook_paths],
            warnings=[],
            template_id=TENSILE_TEMPLATE_ID,
        ).to_excel(writer, sheet_name=METADATA_SHEET, header=False, index=False)

    recipes = tensile_comparison_recipes(loaded_sources)
    figure_outputs = export_comparison_figures(loaded_sources, labels, bundle_dir, recipes)
    return bundle_dir, comparison_workbook_path, recipes, tuple(figure_outputs)


def export_comparison_figures(
    loaded_sources: list[LoadedTensileWorkbookData],
    labels: list[str],
    bundle_dir: Path,
    recipes: tuple[ComparisonRecipe, ...] | None = None,
) -> list[DataStudioFigureOutput]:
    plot_style.apply_style(plot_style.DEFAULT_STYLE_PRESET, plot_style.DEFAULT_PALETTE_PRESET)

    recipe_map = {recipe.id: recipe for recipe in (recipes or tensile_comparison_recipes(loaded_sources))}
    outputs: list[DataStudioFigureOutput] = []
    figures = []
    try:
        representative_series = [
            CurveSeries(
                sample=label,
                x_label=source.representative_curve.x_label,
                y_label=source.representative_curve.y_label,
                x_unit=source.representative_curve.x_unit,
                y_unit=source.representative_curve.y_unit,
                data=source.representative_curve.data.copy(deep=True),
            )
            for label, source in zip(labels, loaded_sources, strict=True)
        ]
        representative_figure, _ = plot_curves(
            representative_series,
            show_markers=False,
            axis_mode="auto_positive",
            width_mm=60.0,
            height_mm=55.0,
            xscale="linear",
            yscale="linear",
            reverse_x=False,
        )
        figures.append(representative_figure)
        representative_path = save_pdf(representative_figure, bundle_dir / COMPARISON_CURVE_FILENAME)
        outputs.append(
            DataStudioFigureOutput(
                path=representative_path,
                label="Representative Curve Compare",
                category="curve",
                template_id="curve",
                sheet_name=REPRESENTATIVE_CURVE_SHEET,
                recipe_id="representative_curve",
            )
        )

        for metric_name in METRIC_NAMES:
            groups = [
                ReplicateGroup(
                    group=label,
                    value_label=source.replicate_groups[metric_name].value_label,
                    value_unit=source.replicate_groups[metric_name].value_unit,
                    data=source.replicate_groups[metric_name].data.copy(deep=True),
                )
                for label, source in zip(labels, loaded_sources, strict=True)
            ]
            metric_slug = slugify_label(metric_name)
            metric_sheet = f"{metric_name}_Replicates"

            bar_figure, _ = plot_bar(groups, width_mm=60.0, height_mm=55.0)
            figures.append(bar_figure)
            bar_path = save_pdf(bar_figure, bundle_dir / f"{metric_slug}_bar_compare.pdf")
            outputs.append(
                DataStudioFigureOutput(
                    path=bar_path,
                    label=f"{metric_name} Bar Compare",
                    category="metric",
                    template_id="bar",
                    sheet_name=metric_sheet,
                    metric_id=metric_name,
                    recipe_id=f"{metric_name.lower()}_bar",
                )
            )

            box_figure, _ = plot_box(groups, width_mm=60.0, height_mm=55.0)
            figures.append(box_figure)
            box_path = save_pdf(box_figure, bundle_dir / f"{metric_slug}_box_compare.pdf")
            outputs.append(
                DataStudioFigureOutput(
                    path=box_path,
                    label=f"{metric_name} Box Compare",
                    category="metric",
                    template_id="box",
                    sheet_name=metric_sheet,
                    metric_id=metric_name,
                    recipe_id=f"{metric_name.lower()}_box",
                )
            )

            violin_figure, _ = plot_violin(groups, width_mm=60.0, height_mm=55.0)
            figures.append(violin_figure)
            violin_path = save_pdf(violin_figure, bundle_dir / f"{metric_slug}_violin_compare.pdf")
            outputs.append(
                DataStudioFigureOutput(
                    path=violin_path,
                    label=f"{metric_name} Violin Compare",
                    category="metric",
                    template_id="violin",
                    sheet_name=metric_sheet,
                    metric_id=metric_name,
                    recipe_id=f"{metric_name.lower()}_violin",
                )
            )
            box_strip_recipe = recipe_map.get(f"{metric_name.lower()}_box_strip")
            if box_strip_recipe is not None and box_strip_recipe.supported:
                box_strip_figure, _ = plot_box(
                    groups,
                    width_mm=60.0,
                    height_mm=55.0,
                    show_raw_points=True,
                    show_fliers=False,
                )
                figures.append(box_strip_figure)
                box_strip_path = save_pdf(
                    box_strip_figure,
                    bundle_dir / f"{metric_slug}_box_strip_compare.pdf",
                )
                outputs.append(
                    DataStudioFigureOutput(
                        path=box_strip_path,
                        label=f"{metric_name} Box + Strip Compare",
                        category="metric",
                        template_id="box_strip",
                        sheet_name=metric_sheet,
                        metric_id=metric_name,
                        recipe_id=box_strip_recipe.id,
                    )
                )
    finally:
        for figure in figures:
            plt.close(figure)
    return outputs


def representative_curve_dataframe(
    loaded_sources: list[LoadedTensileWorkbookData],
    labels: list[str],
) -> pd.DataFrame:
    axis_row: list[object] = []
    unit_row: list[object] = []
    sample_row: list[object] = []
    max_rows = max(len(source.representative_curve.data.index) for source in loaded_sources)
    for label, source in zip(labels, loaded_sources, strict=True):
        axis_row.extend([source.representative_curve.x_label, source.representative_curve.y_label])
        unit_row.extend([source.representative_curve.x_unit, source.representative_curve.y_unit])
        sample_row.extend([label, label])

    rows: list[list[object]] = [axis_row, unit_row, sample_row]
    for row_index in range(max_rows):
        row: list[object] = []
        for source in loaded_sources:
            dataframe = source.representative_curve.data
            if row_index < len(dataframe.index):
                row.extend([float(dataframe.iloc[row_index]["x"]), float(dataframe.iloc[row_index]["y"])])
            else:
                row.extend(["", ""])
        rows.append(row)
    return pd.DataFrame(rows)


def comparison_replicate_dataframe(
    metric_name: str,
    metric_unit: str,
    loaded_sources: list[LoadedTensileWorkbookData],
    labels: list[str],
) -> pd.DataFrame:
    max_rows = max(len(source.replicate_groups[metric_name].data.index) for source in loaded_sources)
    rows: list[list[object]] = [[metric_name], labels, [metric_unit] * len(loaded_sources)]
    for row_index in range(max_rows):
        row: list[object] = []
        for source in loaded_sources:
            values = source.replicate_groups[metric_name].data.reset_index(drop=True)
            row.append(float(values.iloc[row_index]) if row_index < len(values.index) else "")
        rows.append(row)
    return pd.DataFrame(rows)


def comparison_summary_dataframe(
    loaded_sources: list[LoadedTensileWorkbookData],
    labels: list[str],
) -> pd.DataFrame:
    rows: list[list[object]] = [
        [
            "Label",
            "Workbook Path",
            "Specimens",
            "Representative File",
            "Strength Mean (MPa)",
            "Strength Std (MPa)",
            "Modulus Mean (MPa)",
            "Modulus Std (MPa)",
            "Elongation Mean (%)",
            "Elongation Std (%)",
        ]
    ]
    for label, source in zip(labels, loaded_sources, strict=True):
        metric_map = {metric.label: metric for metric in source.metrics}
        rows.append(
            [
                label,
                str(source.workbook_path),
                source.sample_count,
                source.representative_filename,
                metric_map["Strength"].mean,
                metric_map["Strength"].std,
                metric_map["Modulus"].mean,
                metric_map["Modulus"].std,
                metric_map["Elongation"].mean,
                metric_map["Elongation"].std,
            ]
        )
    return pd.DataFrame(rows)


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


def validate_metric_units(loaded_sources: list[LoadedTensileWorkbookData]) -> None:
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


def validate_curve_axes(loaded_sources: list[LoadedTensileWorkbookData]) -> None:
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
    metadata = load_metadata_sheet(path)
    label = str(metadata.get("label", "")).strip()
    if label:
        return label
    sheet_names = set(list_sheet_names(path))
    if REQUIRED_TENSILE_WORKBOOK_SHEETS.issubset(sheet_names):
        label = _infer_standard_tensile_workbook_label(path)
        if label:
            return label
    stem = path.stem.strip()
    if stem:
        return stem
    name = path.name.strip()
    return name or "Tensile Workbook"


def _infer_standard_tensile_workbook_label(path: Path) -> str:
    for metric_name in METRIC_NAMES:
        try:
            groups = load_replicate_table(path, sheet_name=f"{metric_name}_Replicates")
        except Exception:
            continue
        if len(groups) == 1:
            label = str(groups[0].group).strip()
            if label:
                return label
    try:
        curves = load_curve_table(path, sheet_name=REPRESENTATIVE_CURVE_SHEET)
    except Exception:
        return ""
    if len(curves) != 1:
        return ""
    sample = str(curves[0].sample).strip()
    return re.sub(r"\s+representative\s*$", "", sample, flags=re.IGNORECASE).strip()


def dedupe_labels(labels: Iterable[Any]) -> list[str]:
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
    base = f"{slug}_data_studio_compare"
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


def _read_csv_rows(path: Path) -> list[list[str]]:
    raw_bytes = path.read_bytes()
    for encoding in RAW_CSV_ENCODINGS:
        try:
            text = raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _looks_like_tensile_text(text):
            return list(csv.reader(text.splitlines()))
    raise ValueError("Could not decode the tensile export CSV with the common fallback encodings.")


def _looks_like_tensile_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in text or marker in lowered
        for marker in ("结果表格", "拉伸应力", "result table", "tensile stress")
    )


def _find_scalar_header_index(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows):
        joined = ",".join(_clean_cell(cell) for cell in row)
        lowered = joined.lower()
        if ("拉伸应力" in joined and "最大值" in joined) or ("tensile stress" in lowered and "modulus" in lowered):
            return index
    return None


def _find_scalar_value_row(rows: list[list[str]], scalar_header_index: int) -> list[str] | None:
    for index in range(scalar_header_index + 1, min(len(rows), scalar_header_index + 6)):
        row = rows[index]
        numeric_count = sum(_parse_float(cell) is not None for cell in row)
        if numeric_count >= 4:
            return row
    return None


def _extract_scalar_value(
    headers: list[str],
    values: list[str],
    *,
    primary_keywords: tuple[str, ...],
    fallback_keywords: tuple[tuple[str, ...], ...],
) -> float | None:
    keyword_sets = (primary_keywords,) + fallback_keywords
    for keywords in keyword_sets:
        for index, header in enumerate(headers):
            if _cell_contains_all(header, keywords):
                if index < len(values):
                    return _parse_float(values[index])
    return None


def _extract_curve_dataframe(rows: list[list[str]], *, start_index: int) -> pd.DataFrame:
    curve_header_index = _find_curve_header_index(rows, start_index)
    if curve_header_index is None:
        return pd.DataFrame(columns=["x", "y"])

    header_row = rows[curve_header_index]
    strain_index = _find_curve_column_index(
        header_row,
        required_keywords=(("拉伸应变", "位移"), ("tensile strain",), ("strain",)),
        forbidden_keywords=("断裂", "break"),
    )
    stress_index = _find_curve_column_index(
        header_row,
        required_keywords=(("拉伸应力",), ("tensile stress",), ("stress",)),
        forbidden_keywords=("断裂", "break"),
    )
    if strain_index is None or stress_index is None:
        return pd.DataFrame(columns=["x", "y"])

    strain_values: list[float] = []
    stress_values: list[float] = []
    for row in rows[curve_header_index + 2 :]:
        if max(strain_index, stress_index) >= len(row):
            continue
        strain = _parse_float(row[strain_index])
        stress = _parse_float(row[stress_index])
        if strain is None or stress is None:
            continue
        strain_values.append(strain)
        stress_values.append(stress)

    if not strain_values:
        return pd.DataFrame(columns=["x", "y"])

    curve = pd.DataFrame({"x": strain_values, "y": stress_values})
    curve = curve.dropna(subset=["x", "y"]).sort_values("x")
    return curve.reset_index(drop=True)


def _find_curve_header_index(rows: list[list[str]], start_index: int) -> int | None:
    for index in range(start_index, len(rows)):
        joined = ",".join(_clean_cell(cell) for cell in rows[index])
        lowered = joined.lower()
        has_curve_axes = ("拉伸应变" in joined and "拉伸应力" in joined) or (
            "tensile strain" in lowered and "stress" in lowered
        )
        has_curve_context = any(
            marker in joined or marker in lowered
            for marker in ("位移", "时间", "displacement", "time")
        )
        if has_curve_axes and has_curve_context:
            return index
    return None


def _find_curve_column_index(
    header_row: list[str],
    *,
    required_keywords: tuple[tuple[str, ...], ...],
    forbidden_keywords: tuple[str, ...] = (),
) -> int | None:
    for index, cell in enumerate(header_row):
        normalized = _clean_cell(cell)
        lowered = normalized.lower()
        if any(keyword.lower() in lowered for keyword in forbidden_keywords):
            continue
        for keywords in required_keywords:
            if all(keyword.lower() in lowered for keyword in keywords):
                return index
            if all(keyword in normalized for keyword in keywords):
                return index
    return None


def _build_summary_dataframe(samples: list[TensileRawSample]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Filename": sample.filename,
                "Strength (MPa)": sample.strength,
                "Modulus (MPa)": sample.modulus,
                "Elongation (%)": sample.elongation,
            }
            for sample in samples
        ]
    )


def _representative_index(summary_df: pd.DataFrame) -> int:
    if summary_df.empty:
        raise ValueError("No replicate summary statistics are available.")
    mean_values = summary_df.mean(numeric_only=True)
    std_values = summary_df.std(numeric_only=True)
    scores = pd.Series(0.0, index=summary_df.index, dtype=float)
    numeric_columns = summary_df.select_dtypes(include=[np.number]).columns
    for column in numeric_columns:
        std_value = std_values[column]
        if pd.notna(std_value) and float(std_value) > 0:
            scores += ((summary_df[column] - mean_values[column]) / std_value) ** 2
    representative_index = scores.idxmin()
    return int(representative_index)


def _metric_summaries(summary_df: pd.DataFrame) -> tuple[TensileMetricSummary, ...]:
    mean_values = summary_df.mean(numeric_only=True)
    std_values = summary_df.std(numeric_only=True)
    summaries: list[TensileMetricSummary] = []
    for label, unit, _, _ in METRIC_SPECS:
        column_name = f"{label} ({unit})"
        mean_value = mean_values.get(column_name)
        std_value = std_values.get(column_name)
        summaries.append(
            TensileMetricSummary(
                label=label,
                unit=unit,
                mean=float(mean_value) if pd.notna(mean_value) else None,
                std=float(std_value) if pd.notna(std_value) else None,
            )
        )
    return tuple(summaries)


def _workbook_sheets(
    samples: list[TensileRawSample],
    summary_df: pd.DataFrame,
    representative_sample: TensileRawSample,
    group_name: str,
    metrics: tuple[TensileMetricSummary, ...],
) -> list[tuple[str, pd.DataFrame]]:
    sheets: list[tuple[str, pd.DataFrame]] = [
        (
            REPRESENTATIVE_CURVE_SHEET,
            _curve_table_dataframe(
                (
                    (
                        f"{group_name} representative",
                        representative_sample.curve,
                    ),
                )
            ),
        ),
        (
            ALL_CURVES_SHEET,
            _curve_table_dataframe((_sample_name(sample), sample.curve) for sample in samples),
        ),
        (
            SUMMARY_SHEET,
            _summary_sheet_dataframe(summary_df, representative_sample.filename, metrics),
        ),
        (
            ALL_SPECIMENS_SHEET,
            _plain_table_dataframe(summary_df),
        ),
    ]
    for metric in metrics:
        column_name = f"{metric.label} ({metric.unit})"
        sheets.append(
            (
                f"{metric.label}_Replicates",
                _replicate_table_dataframe(
                    group_name=group_name,
                    value_label=metric.label,
                    value_unit=metric.unit,
                    values=summary_df[column_name].dropna().tolist(),
                ),
            )
        )
    return sheets


def _curve_table_dataframe(series_pairs: Iterable[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    normalized_pairs = [(sample_name, dataframe.reset_index(drop=True)) for sample_name, dataframe in series_pairs]
    if not normalized_pairs:
        return pd.DataFrame()

    axis_row: list[object] = []
    unit_row: list[object] = []
    sample_row: list[object] = []
    max_rows = max(len(dataframe.index) for _, dataframe in normalized_pairs)
    for sample_name, _ in normalized_pairs:
        axis_row.extend(["Strain", "Stress"])
        unit_row.extend(["%", "MPa"])
        sample_row.extend([sample_name, sample_name])

    rows: list[list[object]] = [axis_row, unit_row, sample_row]
    for row_index in range(max_rows):
        row: list[object] = []
        for _, dataframe in normalized_pairs:
            if row_index < len(dataframe.index):
                x_value = dataframe.iloc[row_index]["x"]
                y_value = dataframe.iloc[row_index]["y"]
                row.extend([float(x_value), float(y_value)])
            else:
                row.extend(["", ""])
        rows.append(row)
    return pd.DataFrame(rows)


def _replicate_table_dataframe(
    *,
    group_name: str,
    value_label: str,
    value_unit: str,
    values: Iterable[float],
) -> pd.DataFrame:
    rows: list[list[object]] = [
        [value_label],
        [group_name],
        [value_unit],
    ]
    rows.extend([[float(value)] for value in values if pd.notna(value)])
    return pd.DataFrame(rows)


def _summary_sheet_dataframe(
    summary_df: pd.DataFrame,
    representative_filename: str,
    metrics: tuple[TensileMetricSummary, ...],
) -> pd.DataFrame:
    rows: list[list[object]] = [["Item", "Unit", "Mean", "Std", "Representative File"]]
    for index, metric in enumerate(metrics):
        rows.append(
            [
                metric.label,
                metric.unit,
                metric.mean,
                metric.std,
                representative_filename if index == 0 else "",
            ]
        )
    rows.append([])
    rows.append(["Specimens", len(summary_df.index), "", "", ""])
    return pd.DataFrame(rows)


def _plain_table_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    rows = [list(dataframe.columns)]
    rows.extend(dataframe.where(pd.notna(dataframe), "").values.tolist())
    return pd.DataFrame(rows)


def curve_table_dataframe(series_pairs: Iterable[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    return _curve_table_dataframe(series_pairs)


def replicate_table_dataframe(
    *,
    group_name: str,
    value_label: str,
    value_unit: str,
    values: Iterable[float],
) -> pd.DataFrame:
    return _replicate_table_dataframe(
        group_name=group_name,
        value_label=value_label,
        value_unit=value_unit,
        values=values,
    )


def summary_sheet_dataframe(
    summary_df: pd.DataFrame,
    representative_filename: str,
    metrics: tuple[TensileMetricSummary, ...],
) -> pd.DataFrame:
    return _summary_sheet_dataframe(summary_df, representative_filename, metrics)


def plain_table_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    return _plain_table_dataframe(dataframe)


def _metadata_sheet_dataframe(
    *,
    label: str,
    source_files: Iterable[Path],
    warnings: Iterable[str],
    template_id: str,
) -> pd.DataFrame:
    rows = [
        ["label", label],
        ["template_id", template_id],
        ["source_files", " | ".join(str(path) for path in source_files)],
        ["warnings", " | ".join(warnings)],
    ]
    return pd.DataFrame(rows)


def _sample_name(sample: TensileRawSample) -> str:
    return sample.source_path.stem


def _cell_contains_all(cell: str, keywords: tuple[str, ...]) -> bool:
    normalized = _clean_cell(cell)
    lowered = normalized.lower()
    return all(keyword.lower() in lowered for keyword in keywords) or all(keyword in normalized for keyword in keywords)


def _clean_cell(cell: object) -> str:
    return str(cell).replace('"', "").strip()


def _parse_float(value: object) -> float | None:
    text = _clean_cell(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


__all__ = [
    "ALL_CURVES_SHEET",
    "ALL_SPECIMENS_SHEET",
    "COMPARISON_CURVE_FILENAME",
    "LoadedTensileWorkbookData",
    "METADATA_SHEET",
    "METRIC_NAMES",
    "METRIC_SPECS",
    "REPRESENTATIVE_CURVE_SHEET",
    "SUMMARY_SHEET",
    "TENSILE_TEMPLATE_ID",
    "TensileMetricSummary",
    "bundle_dir_name",
    "curve_table_dataframe",
    "default_template_match",
    "export_comparison_figures",
    "export_tensile_comparison_bundle",
    "export_tensile_replicate_workbook",
    "inspect_tensile_workbook",
    "load_metadata_sheet",
    "load_tensile_workbook",
    "parse_tensile_csv",
    "plain_table_dataframe",
    "replicate_table_dataframe",
    "summary_sheet_dataframe",
    "tensile_comparison_recipes",
]
