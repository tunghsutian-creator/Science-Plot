from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src import plot_style
from src.data_loader import CurveSeries, ReplicateGroup
from src.plot_style import save_pdf
from src.plotting_families.curve_family import plot_curves
from src.plotting_families.stats_family import plot_bar, plot_box
from src.rendering.tensile_loading import (
    bundle_dir_name,
    dedupe_labels,
    load_tensile_workbook,
    validate_curve_axes,
    validate_metric_units,
)
from src.rendering.tensile_models import (
    COMPARISON_CURVE_FILENAME,
    METRIC_NAMES,
    METRIC_UNITS,
    SUMMARY_COLUMNS,
    LoadedTensileWorkbook,
    TensileComparisonExport,
    TensileComparisonFigureOutput,
)
from src.tensile_replicates import REPRESENTATIVE_CURVE_SHEET, SUMMARY_SHEET
from src.text_normalization import slugify_label


def export_tensile_comparison_bundle(
    workbook_paths: list[str | Path],
    output_dir: str | Path,
) -> TensileComparisonExport:
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
        for metric_name in METRIC_NAMES:
            comparison_replicate_dataframe(
                metric_name,
                METRIC_UNITS[metric_name],
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

    figure_outputs = export_comparison_figures(loaded_sources, labels, bundle_dir)
    return TensileComparisonExport(
        bundle_dir=bundle_dir,
        comparison_workbook_path=comparison_workbook_path,
        labels=tuple(labels),
        outputs=tuple(item.path for item in figure_outputs),
        figure_outputs=tuple(figure_outputs),
    )


def representative_curve_dataframe(
    loaded_sources: list[LoadedTensileWorkbook],
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
    loaded_sources: list[LoadedTensileWorkbook],
    labels: list[str],
) -> pd.DataFrame:
    max_rows = max(len(source.replicate_groups[metric_name].data.index) for source in loaded_sources)
    metric_header_row: list[object] = [metric_name]
    metric_header_row.extend([""] * max(0, len(loaded_sources) - 1))
    label_row: list[object] = []
    label_row.extend(labels)
    unit_row: list[object] = []
    unit_row.extend([metric_unit] * len(loaded_sources))
    rows: list[list[object]] = [metric_header_row, label_row, unit_row]
    for row_index in range(max_rows):
        row: list[object] = []
        for source in loaded_sources:
            values = source.replicate_groups[metric_name].data.reset_index(drop=True)
            if row_index < len(values.index):
                row.append(float(values.iloc[row_index]))
            else:
                row.append("")
        rows.append(row)
    return pd.DataFrame(rows)


def comparison_summary_dataframe(
    loaded_sources: list[LoadedTensileWorkbook],
    labels: list[str],
) -> pd.DataFrame:
    rows: list[list[object]] = [list(SUMMARY_COLUMNS)]
    for label, source in zip(labels, loaded_sources, strict=True):
        metric_map = {metric.label: metric for metric in source.metrics}
        strength = metric_map["Strength"]
        modulus = metric_map["Modulus"]
        elongation = metric_map["Elongation"]
        rows.append(
            [
                label,
                str(source.workbook_path),
                source.sample_count,
                source.representative_filename,
                strength.mean,
                strength.std,
                modulus.mean,
                modulus.std,
                elongation.mean,
                elongation.std,
            ]
        )
    return pd.DataFrame(rows)


def export_comparison_figures(
    loaded_sources: list[LoadedTensileWorkbook],
    labels: list[str],
    bundle_dir: Path,
) -> list[TensileComparisonFigureOutput]:
    plot_style.apply_style(plot_style.DEFAULT_STYLE_PRESET, plot_style.DEFAULT_PALETTE_PRESET)

    outputs: list[TensileComparisonFigureOutput] = []
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
            TensileComparisonFigureOutput(
                path=representative_path,
                category="curve",
                kind="representative_curve",
                metric=None,
                label="Representative Curve Compare",
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
            box_figure, _ = plot_box(groups, width_mm=60.0, height_mm=55.0)
            figures.append(box_figure)
            box_path = save_pdf(box_figure, bundle_dir / f"{metric_slug}_box_compare.pdf")
            outputs.append(
                TensileComparisonFigureOutput(
                    path=box_path,
                    category="metric",
                    kind="box_compare",
                    metric=metric_name,
                    label=f"{metric_name} Box Compare",
                )
            )

            bar_figure, _ = plot_bar(groups, width_mm=60.0, height_mm=55.0)
            figures.append(bar_figure)
            bar_path = save_pdf(bar_figure, bundle_dir / f"{metric_slug}_bar_compare.pdf")
            outputs.append(
                TensileComparisonFigureOutput(
                    path=bar_path,
                    category="metric",
                    kind="bar_compare",
                    metric=metric_name,
                    label=f"{metric_name} Bar Compare",
                )
            )
    finally:
        for figure in figures:
            plt.close(figure)
    return outputs


__all__ = [
    "comparison_replicate_dataframe",
    "comparison_summary_dataframe",
    "export_comparison_figures",
    "export_tensile_comparison_bundle",
    "representative_curve_dataframe",
]
