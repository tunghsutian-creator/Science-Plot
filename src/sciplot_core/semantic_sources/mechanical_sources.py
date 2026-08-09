"""Read non-tensile mechanical curves and specimen summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)
from sciplot_core.policy import (
    COMPRESSION_X_AXIS_LABEL,
    COMPRESSION_Y_AXIS_LABEL,
    FLEXURAL_X_AXIS_LABEL,
    FLEXURAL_Y_AXIS_LABEL,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _float,
    _scan_curve_series_source,
)

_NON_TENSILE_MECHANICAL_CONTRACTS: dict[str, dict[str, Any]] = {
    "compression_curve": {
        "x_label": COMPRESSION_X_AXIS_LABEL.removesuffix(" (%)"),
        "y_label": COMPRESSION_Y_AXIS_LABEL.removesuffix(" (MPa)"),
        "x_aliases": ("strain", "compressive strain", "compression strain", "压缩应变"),
        "y_aliases": (
            "stress",
            "compressive stress",
            "compression stress",
            "压缩应力",
            "σ",
        ),
        "strength_metric": "compressive_strength_MPa",
        "magnitude": True,
    },
    "flexural_curve": {
        "x_label": FLEXURAL_X_AXIS_LABEL.removesuffix(" (%)"),
        "y_label": FLEXURAL_Y_AXIS_LABEL.removesuffix(" (MPa)"),
        "x_aliases": ("strain", "flexural strain", "bending strain", "弯曲应变"),
        "y_aliases": ("stress", "flexural stress", "bending stress", "弯曲应力", "σ"),
        "strength_metric": "flexural_strength_MPa",
        "magnitude": False,
    },
}


def _read_non_tensile_mechanical_series(
    source: Path,
    *,
    family: str,
) -> list[CurveSeriesPayload]:
    contract = _NON_TENSILE_MECHANICAL_CONTRACTS[family]
    paths = (
        [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file()
            and path.suffix.casefold() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        ]
        if source.is_dir()
        else [source]
    )
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for path in paths:
        try:
            parsed = _scan_curve_series_source(
                path,
                x_aliases=contract["x_aliases"],
                y_aliases=contract["y_aliases"],
                x_label=str(contract["x_label"]),
                y_label=str(contract["y_label"]),
                default_x_unit="%",
                default_y_unit="MPa",
                sample_prefix=path.stem,
            )
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        series_list.extend(
            CurveSeriesPayload(
                sample=series.sample,
                x_label=series.x_label,
                x_unit=series.x_unit,
                y_label=series.y_label,
                y_unit=series.y_unit,
                points=series.points,
                diagnostics={
                    **(series.diagnostics or {}),
                    "source_file": str(path.resolve()),
                },
            )
            for series in parsed
        )
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(
            f"No {family.removesuffix('_curve')} stress-strain curves found under "
            f"{source}. {detail}".strip()
        )
    return series_list


def _read_non_tensile_mechanical_workbook_directory(
    source: Path,
    *,
    family: str,
) -> tuple[list[CurveSeriesPayload], list[dict[str, Any]]] | None:
    """Read curated mechanical workbooks using tensile's sheet contract."""

    contract = _NON_TENSILE_MECHANICAL_CONTRACTS[family]
    workbook_paths = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls"}
    )
    if not workbook_paths:
        return None
    required_sheets = {"Representative_Curve", "All_Specimens"}
    if not all(
        required_sheets <= set(pd.ExcelFile(path).sheet_names)
        for path in workbook_paths
    ):
        return None

    representatives: list[CurveSeriesPayload] = []
    summary_rows: list[dict[str, Any]] = []
    strength_metric = str(contract["strength_metric"])
    for workbook_path in workbook_paths:
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
            raise ValueError(
                f"Representative_Curve has no two-column data in {workbook_path.name}."
            )
        points = tuple(
            (strain, stress)
            for strain, stress in (
                (
                    _float(representative.iat[row_index, 0]),
                    _float(representative.iat[row_index, 1]),
                )
                for row_index in range(3, representative.shape[0])
            )
            if strain is not None and stress is not None
        )
        if len(points) < 2:
            raise ValueError(
                f"Representative_Curve has fewer than two numeric points in "
                f"{workbook_path.name}."
            )
        sample = workbook_path.stem
        try:
            metadata = pd.read_excel(
                workbook_path,
                sheet_name="DataStudio_Metadata",
                header=None,
            )
            for row_index in range(metadata.shape[0]):
                if _clean_text(metadata.iat[row_index, 0]).casefold() == "label":
                    sample = (
                        _clean_text(metadata.iat[row_index, 1]) or workbook_path.stem
                    )
                    break
        except (KeyError, ValueError, IndexError):
            pass
        representatives.append(
            CurveSeriesPayload(
                sample=sample,
                x_label=str(contract["x_label"]),
                x_unit=_clean_text(representative.iat[1, 0]) or "%",
                y_label=str(contract["y_label"]),
                y_unit=_clean_text(representative.iat[1, 1]) or "MPa",
                points=points,
                diagnostics={
                    "source_file": str(workbook_path),
                    "source_table": "Representative_Curve",
                    "representative_source": ("workbook Representative_Curve sheet"),
                },
            )
        )

        specimens = pd.read_excel(
            workbook_path,
            sheet_name="All_Specimens",
        )
        strength_column = next(
            (column for column in specimens.columns if "strength" in _token(column)),
            None,
        )
        if strength_column is None:
            raise ValueError(
                f"All_Specimens has no strength column in {workbook_path.name}."
            )
        for row_index, row in specimens.iterrows():
            strength = _float(row[strength_column])
            if strength is None:
                continue
            replicate = _clean_text(row.iloc[0]) if len(row) else ""
            summary_rows.append(
                {
                    "sample": sample,
                    "replicate": (replicate or f"{workbook_path.stem}_{row_index + 1}"),
                    strength_metric: abs(strength)
                    if contract["magnitude"]
                    else strength,
                    "source_file": (f"{workbook_path}:{replicate or row_index + 1}"),
                    "strength_source": "instrument_report",
                    "reported_metric_headers": json.dumps(
                        {strength_metric: str(strength_column)},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
    if not representatives or not summary_rows:
        raise ValueError(
            f"No curated {family.removesuffix('_curve')} curves and specimen "
            f"strengths found under {source}."
        )
    return representatives, summary_rows
