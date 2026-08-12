"""Read tensile workbook curves and specimen summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)
from sciplot_core.materials_rules import (
    ELONGATION_AT_BREAK_METRIC,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _float,
    _scan_curve_series_source,
)


def _read_tensile_workbook_series(source: Path) -> list[CurveSeriesPayload]:
    series_list = _scan_curve_series_source(
        source,
        x_aliases=("strain", "拉伸应变"),
        y_aliases=("stress", "σ", "sigma", "拉伸应力", "应力"),
        x_label="Tensile strain",
        y_label="Tensile stress",
        default_x_unit="%",
        default_y_unit="MPa",
        sample_prefix=source.stem,
    )
    if not series_list:
        raise ValueError("No tensile curves found by structure scan.")
    return series_list


def _read_tensile_workbook_directory(
    source: Path,
) -> tuple[list[CurveSeriesPayload], list[dict[str, Any]]]:
    """Read curated tensile workbooks as representative curves plus repeats.

    These workbooks are already reduced exports: ``Representative_Curve`` is
    the authoritative curve for each sample, while ``All_Specimens`` is the
    authoritative replicate table for summary metrics.  Do not scan
    ``All_Curves`` here, because that would replace the requested
    representative-only presentation with every specimen trace.
    """

    workbook_paths = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls"}
    )
    if not workbook_paths:
        raise ValueError(f"No tensile workbook files found under {source}.")

    representatives: list[CurveSeriesPayload] = []
    summary_rows: list[dict[str, Any]] = []
    for workbook_path in workbook_paths:
        try:
            representative = (
                pd.read_excel(
                    workbook_path,
                    sheet_name="Representative_Curve",
                    header=None,
                )
                .dropna(how="all")
                .dropna(axis=1, how="all")
            )
            if representative.shape[0] < 4 or representative.shape[1] < 2:
                raise ValueError("Representative_Curve has no two-column data.")
            points = tuple(
                (x_value, y_value)
                for x_value, y_value in (
                    (
                        _float(representative.iat[row_index, 0]),
                        _float(representative.iat[row_index, 1]),
                    )
                    for row_index in range(3, representative.shape[0])
                )
                if x_value is not None and y_value is not None
            )
            if len(points) < 2:
                raise ValueError(
                    "Representative_Curve has fewer than two numeric points."
                )
            sample = workbook_path.stem
            try:
                metadata = pd.read_excel(
                    workbook_path, sheet_name="DataStudio_Metadata", header=None
                )
                for row_index in range(metadata.shape[0]):
                    if _clean_text(metadata.iat[row_index, 0]).casefold() == "label":
                        metadata_sample = _clean_text(metadata.iat[row_index, 1])
                        if metadata_sample:
                            sample = metadata_sample
                        break
            except (KeyError, ValueError, IndexError):
                pass
            representatives.append(
                CurveSeriesPayload(
                    sample=sample,
                    x_label=_clean_text(representative.iat[0, 0]) or "Tensile strain",
                    x_unit=_clean_text(representative.iat[1, 0]) or "%",
                    y_label=_clean_text(representative.iat[0, 1]) or "Tensile stress",
                    y_unit=_clean_text(representative.iat[1, 1]) or "MPa",
                    points=points,
                    diagnostics={
                        "source_file": str(workbook_path),
                        "source_table": "Representative_Curve",
                        "representative_source": "workbook Representative_Curve sheet",
                    },
                )
            )

            specimens = pd.read_excel(workbook_path, sheet_name="All_Specimens")
            metric_columns: dict[str, object] = {}
            for column in specimens.columns:
                token = _token(column)
                if "strength" in token and "strength_MPa" not in metric_columns:
                    metric_columns["strength_MPa"] = column
                elif "modulus" in token and "modulus_MPa" not in metric_columns:
                    metric_columns["modulus_MPa"] = column
                elif (
                    "elongation" in token
                    and ELONGATION_AT_BREAK_METRIC not in metric_columns
                ):
                    metric_columns[ELONGATION_AT_BREAK_METRIC] = column
            for row_index, row in specimens.iterrows():
                metrics = {
                    metric: _float(row[column])
                    for metric, column in metric_columns.items()
                }
                metrics = {
                    metric: value
                    for metric, value in metrics.items()
                    if value is not None
                }
                if not metrics:
                    continue
                replicate = _clean_text(row.iloc[0]) if len(row) else ""
                summary_rows.append(
                    {
                        "sample": sample,
                        "replicate": replicate
                        or f"{workbook_path.stem}_{row_index + 1}",
                        **metrics,
                        "source_file": f"{workbook_path}:{replicate or row_index + 1}",
                        "reported_metric_headers": json.dumps(
                            {
                                metric: str(column)
                                for metric, column in metric_columns.items()
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                )
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError(
                f"Could not read tensile workbook {workbook_path.name}: {exc}"
            ) from exc

    if not representatives:
        raise ValueError(f"No representative tensile curves found under {source}.")
    if not summary_rows:
        raise ValueError(f"No tensile specimen metrics found under {source}.")
    return representatives, summary_rows
