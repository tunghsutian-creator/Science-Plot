"""Apply explicit column confirmations to rheology sweep sources."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)
from sciplot_core.materials_rules import (
    format_unit_label,
)


from sciplot_core.semantic_sources.models import (
    RheologySweepSample,
    _RHEOLOGY_COMPLEX_MODULUS_METRIC,
)

from sciplot_core.semantic_sources.table_scanning import (
    _unit_for,
    _float,
    _read_raw_table_normalized,
)

from sciplot_core.semantic_sources.series_labels import (
    _source_display_sample,
)

from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _sweep_source_files,
    _unit_conversion,
)

from sciplot_core.semantic_sources.rheology_ordering import (
    _sweep_sample_order_key,
)


def _confirmed_column_items(column_confirmations: object) -> list[dict[str, Any]]:
    if not isinstance(column_confirmations, list | tuple):
        return []
    return [item for item in column_confirmations if isinstance(item, dict)]


def _confirmation_names(confirmation: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    file_name = _clean_text(confirmation.get("file_name"))
    if file_name:
        names.add(file_name)
    source_path = _clean_text(confirmation.get("source_path"))
    if source_path:
        names.add(Path(source_path).name)
    return names


def _candidate_names(candidate: Path) -> set[str]:
    names = {candidate.name}
    if "__" in candidate.name:
        _sample, original = candidate.name.split("__", 1)
        if original:
            names.add(original)
    return names


def _matching_column_confirmation(
    candidate: Path,
    column_confirmations: object,
) -> dict[str, Any] | None:
    candidate_names = _candidate_names(candidate)
    for confirmation in _confirmed_column_items(column_confirmations):
        if candidate_names & _confirmation_names(confirmation):
            return confirmation
    return None


def _metric_key_from_label(
    label: object,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> str | None:
    token = _token(label)
    if not token:
        return None
    for key, metric_label, aliases, _default_unit in metrics:
        metric_tokens = {_token(metric_label), *(_token(alias) for alias in aliases)}
        if any(
            metric_token and metric_token in token for metric_token in metric_tokens
        ):
            return key
    return None


def _metric_default_units(
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> dict[str, str]:
    units = {key: default_unit for key, _label, _aliases, default_unit in metrics}
    units.setdefault("complex_modulus", _RHEOLOGY_COMPLEX_MODULUS_METRIC[3])
    return units


def _confirmed_rheology_sweep_sample(
    source: Path,
    confirmation: dict[str, Any],
    *,
    x_label: str,
    default_x_unit: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> RheologySweepSample:
    raw = _read_raw_table_normalized(source).dropna(axis=1, how="all").dropna(how="all")
    columns = confirmation.get("columns")
    if not isinstance(columns, list | tuple):
        raise ValueError("Column confirmation does not contain columns.")

    x_index: int | None = None
    metric_indexes: dict[str, int] = {}
    match_metrics = (*metrics, _RHEOLOGY_COMPLEX_MODULUS_METRIC)
    for column in columns:
        if not isinstance(column, dict):
            continue
        try:
            index = int(column.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= raw.shape[1]:
            continue
        confirmed_type = _clean_text(column.get("confirmed_type")).casefold()
        if confirmed_type == "ignore":
            continue
        role = _clean_text(column.get("role")).casefold()
        if role == "x" and x_index is None:
            x_index = index
            continue
        if role != "y":
            continue
        metric_key = _metric_key_from_label(column.get("name"), match_metrics)
        if metric_key and metric_key not in metric_indexes:
            metric_indexes[metric_key] = index

    if x_index is None:
        raise ValueError(f"No confirmed X column found in {source}.")
    if "storage_modulus" not in metric_indexes:
        raise ValueError(f"No confirmed storage modulus column found in {source}.")

    default_units = _metric_default_units(match_metrics)
    numeric_rows = [
        row_index
        for row_index in range(raw.shape[0])
        if _float(raw.iat[row_index, x_index]) is not None
        and any(
            _float(raw.iat[row_index, metric_index]) is not None
            for metric_index in metric_indexes.values()
        )
    ]
    if not numeric_rows:
        raise ValueError(f"No numeric rheology sweep points found in {source}.")

    unit_index = numeric_rows[0] - 1
    units = (
        [_clean_text(value) for value in raw.iloc[unit_index].tolist()]
        if unit_index >= 0
        else []
    )
    source_x_unit = _unit_for(units, x_index, default_x_unit)
    x_unit, x_factor, x_method = _unit_conversion(source_x_unit, default_x_unit)
    if x_method == "source_unit_preserved":
        raise ValueError(
            f"Unsupported confirmed rheology x unit `{source_x_unit}` in "
            f"{source}; expected a validated conversion to "
            f"`{format_unit_label(default_x_unit)}`."
        )
    metric_units: dict[str, str] = {}
    metric_factors: dict[str, float] = {}
    metric_conversions: dict[str, dict[str, Any]] = {}
    for key, metric_index in metric_indexes.items():
        default_unit = default_units.get(key, "")
        source_unit = _unit_for(units, metric_index, default_unit)
        output_unit, factor, method = _unit_conversion(source_unit, default_unit)
        if method == "source_unit_preserved":
            raise ValueError(
                f"Unsupported confirmed rheology unit `{source_unit}` for "
                f"metric `{key}` in {source}; expected a validated "
                f"conversion to `{format_unit_label(default_unit)}`."
            )
        metric_units[key] = output_unit
        metric_factors[key] = factor
        metric_conversions[key] = {
            "source_unit": source_unit,
            "output_unit": output_unit,
            "factor": factor,
            "method": method,
        }
    should_derive_complex_modulus = (
        "complex_modulus" not in metric_indexes
        and "storage_modulus" in metric_indexes
        and "loss_modulus" in metric_indexes
    )
    if should_derive_complex_modulus:
        metric_units["complex_modulus"] = (
            metric_units.get("storage_modulus")
            or metric_units.get("loss_modulus")
            or "Pa"
        )

    rows: list[dict[str, float]] = []
    for row_index in numeric_rows:
        x_value = _float(raw.iat[row_index, x_index])
        if x_value is None:
            continue
        row: dict[str, float] = {"x": x_value * x_factor}
        for key, metric_index in metric_indexes.items():
            y_value = _float(raw.iat[row_index, metric_index])
            if y_value is not None:
                row[key] = y_value * metric_factors[key]
        if should_derive_complex_modulus:
            storage = row.get("storage_modulus")
            loss = row.get("loss_modulus")
            if storage is not None and loss is not None:
                row["complex_modulus"] = math.hypot(storage, loss)
        rows.append(row)
    empty_metrics = [
        key for key in metric_indexes if not any(key in row for row in rows)
    ]
    if empty_metrics:
        raise ValueError(
            f"Confirmed rheology columns contain no numeric values in {source}: "
            f"{', '.join(empty_metrics)}."
        )

    return RheologySweepSample(
        sample=_source_display_sample(source),
        source=source,
        x_label=x_label,
        x_unit=x_unit,
        metric_units=metric_units,
        rows=tuple(rows),
        source_x_unit=source_x_unit,
        x_conversion={
            "source_unit": source_x_unit,
            "output_unit": x_unit,
            "factor": x_factor,
            "method": x_method,
        },
        metric_conversions=metric_conversions,
    )


def _read_confirmed_rheology_sweep_samples(
    source: Path,
    column_confirmations: object,
    *,
    x_label: str,
    default_x_unit: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> list[RheologySweepSample]:
    confirmations = _confirmed_column_items(column_confirmations)
    if not confirmations:
        return []
    samples: list[RheologySweepSample] = []
    errors: list[str] = []
    matched_confirmation_ids: set[int] = set()
    for candidate in _sweep_source_files(source):
        confirmation = _matching_column_confirmation(candidate, column_confirmations)
        if confirmation is None:
            continue
        matched_confirmation_ids.add(id(confirmation))
        try:
            samples.append(
                _confirmed_rheology_sweep_sample(
                    candidate,
                    confirmation,
                    x_label=x_label,
                    default_x_unit=default_x_unit,
                    metrics=metrics,
                )
            )
        except (OSError, ValueError) as exc:
            errors.append(f"{candidate.name}: {exc}")
    for confirmation in confirmations:
        if id(confirmation) in matched_confirmation_ids:
            continue
        names = sorted(_confirmation_names(confirmation))
        errors.append(
            "unmatched confirmation "
            + (f"for {', '.join(names)}" if names else "without a source name")
        )
    if errors:
        raise ValueError(
            "Confirmed rheology sweep preparation rejected one or more "
            "confirmed samples; silent partial datasets are not allowed "
            f"({'; '.join(errors[:3])})."
        )
    if not samples:
        raise ValueError(
            "Confirmed rheology sweep preparation found no confirmed samples."
        )
    return sorted(samples, key=_sweep_sample_order_key)
