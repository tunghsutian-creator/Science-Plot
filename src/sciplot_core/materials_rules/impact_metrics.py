"""Read impact tables and compute replicate-level impact metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from sciplot_core.source_tables import read_raw_table

from sciplot_core.materials_rules.metric_tables import (
    _metric,
)


def _impact_metric_tables(processed_source: Path) -> list[tuple[str, pd.DataFrame]]:
    """Read every deterministic impact table represented by one source file."""

    suffix = processed_source.suffix.casefold()
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        workbook = pd.ExcelFile(processed_source)
        return [
            (
                str(sheet_name),
                pd.read_excel(processed_source, sheet_name=sheet_name, header=None)
                .dropna(how="all")
                .dropna(axis=1, how="all"),
            )
            for sheet_name in workbook.sheet_names
        ]
    return [
        (
            "",
            read_raw_table(processed_source)
            .dropna(how="all")
            .dropna(axis=1, how="all"),
        )
    ]


def _impact_metrics(processed_source: Path) -> list[dict[str, Any]]:
    grouped_values: dict[tuple[str, str], tuple[str, list[float]]] = {}
    for table_name, raw in _impact_metric_tables(processed_source):
        if raw.shape[0] < 4:
            continue
        for column in range(raw.shape[1]):
            sample = str(raw.iat[2, column]).strip()
            if not sample or sample.casefold() == "nan":
                sample = f"Sample {column + 1}"
            unit = str(raw.iat[1, column]).strip()
            if not unit or unit.casefold() == "nan":
                unit = "kJ/m2"
            values = (
                pd.to_numeric(raw.iloc[3:, column], errors="coerce")
                .dropna()
                .to_numpy(dtype=float)
            )
            if values.size == 0:
                continue
            key = (table_name, sample)
            existing_unit, existing_values = grouped_values.setdefault(key, (unit, []))
            existing_values.extend(float(value) for value in values)
            grouped_values[key] = (existing_unit, existing_values)

    if not grouped_values:
        return [
            _metric(
                "impact_group_n",
                None,
                "count",
                "skipped",
                "The prepared impact table did not contain categorical raw values.",
            )
        ]

    sample_occurrences: dict[str, int] = {}
    for _table_name, sample in grouped_values:
        sample_occurrences[sample] = sample_occurrences.get(sample, 0) + 1

    rows: list[dict[str, Any]] = []
    for (table_name, sample), (unit, raw_values) in grouped_values.items():
        label = (
            f"{sample} ({table_name})"
            if table_name and sample_occurrences[sample] > 1
            else sample
        )
        values = np.asarray(raw_values, dtype=float)
        rows.append(_metric(f"impact_group_n[{label}]", int(values.size), "count"))
        rows.append(
            _metric(
                f"impact_group_median[{label}]", float(np.quantile(values, 0.5)), unit
            )
        )
        if values.size >= 2:
            iqr = float(np.quantile(values, 0.75) - np.quantile(values, 0.25))
            rows.append(_metric(f"impact_group_iqr[{label}]", iqr, unit))
        else:
            rows.append(
                _metric(
                    f"impact_group_iqr[{label}]",
                    None,
                    unit,
                    "skipped",
                    "At least two raw replicates are required for an IQR summary; the raw point is retained.",
                )
            )
    if rows:
        return rows
    return [
        _metric(
            "impact_group_n",
            None,
            "count",
            "skipped",
            "The prepared impact table did not contain finite raw values.",
        )
    ]
