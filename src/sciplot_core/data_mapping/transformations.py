"""Apply one validated declarative transformation to a mapped table."""

from __future__ import annotations

import math
from typing import Any
import pandas as pd
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mapping_contract import (
    DeclarativeTransformation,
)
from sciplot_core.materials_rules import convert_value

from sciplot_core.data_mapping.raw_tables import (
    _require_columns,
    _numeric_series,
    _deterministic_sort_key,
    _condition_mask,
)


def _apply_transformation(
    frame: pd.DataFrame,
    units: dict[str, str],
    transformation: DeclarativeTransformation,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, Any]]:
    operation = transformation.transformation_type
    parameters = transformation.parameters
    before_rows = int(frame.shape[0])
    before_columns = [str(column) for column in frame.columns]
    result = frame.copy()
    updated_units = dict(units)

    if operation == "rename":
        columns = {str(key): str(value) for key, value in parameters["columns"].items()}
        _require_columns(result, list(columns), operation=operation)
        targets = [columns.get(str(column), str(column)) for column in result.columns]
        if len(set(targets)) != len(targets):
            raise ValueError("rename would create duplicate output columns.")
        result = result.rename(columns=columns)
        updated_units = {
            columns.get(column, column): unit for column, unit in updated_units.items()
        }
    elif operation == "select":
        columns = [str(column) for column in parameters["columns"]]
        _require_columns(result, columns, operation=operation)
        result = result.loc[:, columns]
        updated_units = {
            column: unit for column, unit in updated_units.items() if column in columns
        }
    elif operation == "exclude":
        if "columns" in parameters:
            columns = [str(column) for column in parameters["columns"]]
            _require_columns(result, columns, operation=operation)
            result = result.drop(columns=columns)
            updated_units = {
                column: unit
                for column, unit in updated_units.items()
                if column not in columns
            }
        if "row_indices" in parameters:
            indexes = [int(index) for index in parameters["row_indices"]]
            outside = [index for index in indexes if index >= len(result)]
            if outside:
                raise ValueError(
                    f"exclude row_indices are outside the current table: {outside}"
                )
            result = result.drop(index=result.index[indexes])
        if "where" in parameters:
            masks = [
                _condition_mask(result, dict(condition))
                for condition in parameters["where"]
            ]
            combined = masks[0]
            for mask in masks[1:]:
                combined = (
                    combined | mask
                    if parameters.get("match", "all") == "any"
                    else combined & mask
                )
            result = result.loc[~combined]
        result = result.reset_index(drop=True)
    elif operation == "drop_missing":
        columns = [str(column) for column in parameters.get("columns", result.columns)]
        _require_columns(result, columns, operation=operation)
        result = result.dropna(
            axis=0,
            subset=columns,
            how=str(parameters.get("how") or "any"),
        ).reset_index(drop=True)
    elif operation == "sort":
        columns = [str(column) for column in parameters["by"]]
        _require_columns(result, columns, operation=operation)
        result = result.sort_values(
            by=columns,
            ascending=parameters.get("ascending", True),
            na_position=str(parameters.get("na_position") or "last"),
            kind="mergesort",
            key=_deterministic_sort_key,
        ).reset_index(drop=True)
    elif operation == "unit_convert":
        column = str(parameters["column"])
        output = str(parameters.get("output_column") or column)
        numeric = _numeric_series(result, column, operation=operation)
        converted = numeric.map(
            lambda value: (
                pd.NA
                if pd.isna(value)
                else convert_value(
                    float(value),
                    str(parameters["from_unit"]),
                    str(parameters["to_unit"]),
                )
            )
        )
        if output != column and output in result.columns:
            raise ValueError(f"unit_convert output column already exists: {output!r}")
        result[output] = converted
        updated_units[output] = str(parameters["to_unit"])
    elif operation == "derive_ratio":
        numerator = _numeric_series(
            result, str(parameters["numerator"]), operation=operation
        )
        denominator = _numeric_series(
            result, str(parameters["denominator"]), operation=operation
        )
        output = str(parameters["output"])
        if output in result.columns:
            raise ValueError(f"derive_ratio output column exists: {output!r}")
        zero = denominator == 0.0
        if zero.any() and parameters.get("zero_policy", "error") == "error":
            rows = [int(index) for index in denominator.index[zero].tolist()[:8]]
            raise ValueError(f"derive_ratio denominator is zero at rows {rows}.")
        denominator = denominator.mask(zero)
        result[output] = numerator / denominator * float(parameters.get("scale", 1.0))
    elif operation == "normalize_baseline":
        column = str(parameters["column"])
        output = str(parameters["output"])
        if output in result.columns:
            raise ValueError(f"normalize_baseline output column exists: {output!r}")
        numeric = _numeric_series(result, column, operation=operation)
        finite = numeric[numeric.map(math.isfinite)]
        if finite.empty:
            raise ValueError("normalize_baseline has no finite values.")
        method = str(parameters.get("method") or "first_finite")
        if method == "first_finite":
            baseline = float(finite.iloc[0])
        elif method == "last_finite":
            baseline = float(finite.iloc[-1])
        elif method == "max_abs":
            baseline = float(finite.abs().max())
        elif method == "mean_first_n":
            baseline = float(finite.iloc[: int(parameters["n"])].mean())
        else:
            baseline = float(parameters["value"])
        if not math.isfinite(baseline) or baseline == 0.0:
            raise ValueError(
                "normalize_baseline resolved a non-finite or zero baseline."
            )
        result[output] = numeric / baseline
        updated_units[output] = "1"
    elif operation == "aggregate_replicates":
        group_by = [str(column) for column in parameters["group_by"]]
        value_columns = [str(column) for column in parameters["value_columns"]]
        _require_columns(result, [*group_by, *value_columns], operation=operation)
        for column in value_columns:
            result[column] = _numeric_series(result, column, operation=operation)
        grouped = result.groupby(group_by, dropna=False, sort=False)
        method = str(parameters.get("method") or "mean")
        if method == "mean":
            result = grouped[value_columns].mean().reset_index()
        else:
            result = grouped[value_columns].median().reset_index()
        if parameters.get("include_count", True):
            count_column = str(parameters.get("count_column") or "replicate_count")
            if count_column in result.columns:
                raise ValueError(
                    f"aggregate count column already exists: {count_column!r}"
                )
            counts = grouped.size().reset_index(name=count_column)
            result = result.merge(
                counts,
                on=group_by,
                how="left",
                validate="one_to_one",
            )
        updated_units = {
            column: unit
            for column, unit in updated_units.items()
            if column in result.columns
        }
    else:
        raise ValueError(f"Unsupported declarative transformation: {operation}")

    return (
        result,
        updated_units,
        {
            "transformation_id": transformation.transformation_id,
            "transformation_type": operation,
            "source_ids": list(transformation.source_ids),
            "parameters": json_safe(parameters),
            "rows_before": before_rows,
            "rows_after": int(result.shape[0]),
            "columns_before": before_columns,
            "columns_after": [str(column) for column in result.columns],
        },
    )
