"""Apply explicit column confirmations to rheology sweep sources."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from tempfile import TemporaryDirectory
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.semantic_sources.confirmation_contract import has_column_intent, require_supported_confirmations
from sciplot_core.semantic_sources.instrument_regions import rheology_instrument_regions
from sciplot_core.semantic_sources.paired_curve_data_block import first_paired_curve_data_block
from sciplot_core.foundation.path_names import safe_filename
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.rheology_frequency_metrics import complete_sweep_metrics
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
    _RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
    _RHEOLOGY_SWEEP_METRICS,
)

from sciplot_core.semantic_sources.table_scanning import (
    _unit_row_score,
    _float,
    _read_raw_table_normalized,
)
from sciplot_core.semantic_sources.rheology_sweep_columns import FREQUENCY_X_ALIASES, TEMPERATURE_X_ALIASES, _find_rheology_sweep_headers, _rheology_sweep_units, _sweep_source_unit
from sciplot_core.semantic_sources.paired_curve_table_metadata import header_quantity_text
from sciplot_core.semantic_sources.rheology_frequency_metrics import is_rheology_magnitude_header

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


def _metric_key_from_label(
    label: object,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> str | None:
    text = header_quantity_text(label).casefold()
    token = _token(text)
    if not token:
        return None
    for key, metric_label, aliases, _default_unit in metrics:
        if key in {"complex_modulus", "complex_viscosity"}:
            matched = is_rheology_magnitude_header(label, metric=key)
        else:
            names = (metric_label, *aliases)
            matched = any(text == name.casefold() or
                          len(_token(name)) > 1 and _token(name) in token for name in names)
        if matched:
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
    raw = _read_raw_table_normalized(source)
    if rheology_instrument_regions(raw) is not None:
        raise ValueError("Explicit columns support one plain table, not instrument Test/Result/Interval scope; select the exact source region through task mapping.")
    columns = confirmation["columns"]

    x_index: int | None = None
    metric_indexes: dict[str, int] = {}
    match_metrics = (*metrics, _RHEOLOGY_COMPLEX_MODULUS_METRIC)
    for column in columns:
        index = column["index"]
        if index < 0 or index >= raw.shape[1]:
            raise ValueError("A confirmed column is outside the current original table.")
        confirmed_type = _clean_text(column.get("confirmed_type")).casefold()
        if confirmed_type == "ignore":
            continue
        role = _clean_text(column.get("role")).casefold()
        if role == "x":
            if x_index is not None:
                raise ValueError("An explicit source has conflicting X columns.")
            x_index = index
            continue
        if role != "y":
            continue
        metric_key = _metric_key_from_label(column.get("name"), match_metrics)
        if metric_key is None:
            raise ValueError("Unsupported explicit Y quantity; select its scientific meaning through source-bound task mapping.")
        if metric_key in metric_indexes:
            raise ValueError(f"An explicit source has conflicting {metric_key} columns.")
        metric_indexes[metric_key] = index

    if x_index is None:
        raise ValueError(f"No confirmed X column found in {source}.")
    if "storage_modulus" not in metric_indexes:
        raise ValueError(f"No confirmed storage modulus column found in {source}.")

    default_units = _metric_default_units(match_metrics)
    block = first_paired_curve_data_block(raw, data_start=0,
        pairs=tuple((x_index, index) for index in metric_indexes.values()))
    numeric_rows = [
        row_index
        for row_index in block.rows
        if _float(raw.iat[row_index, x_index], decimal_comma=block.decimal_comma) is not None
        and any(
            _float(raw.iat[row_index, metric_index], decimal_comma=block.decimal_comma) is not None
            for metric_index in metric_indexes.values()
        )
    ]
    if not numeric_rows:
        raise ValueError(f"No numeric rheology sweep points found in {source}.")

    selected_columns = (x_index, *metric_indexes.values())
    explicit_units = _token(x_label) == "angularfrequency"
    try:
        header_indexes = _find_rheology_sweep_headers(raw,
            x_aliases=FREQUENCY_X_ALIASES if explicit_units else TEMPERATURE_X_ALIASES, metrics=match_metrics)
    except ValueError:
        # The original explicit-column route also serves opaque headers. Its
        # adjacent observed unit row is evidence, never an invented source unit.
        adjacent = numeric_rows[0] - 1
        has_units = adjacent >= 0 and _unit_row_score(raw, adjacent, selected_columns) > 0
        header_index = adjacent - 1 if has_units else adjacent
    else:
        if len(header_indexes) != 1:
            raise ValueError("Explicit columns require one source table; select repeated intervals through task mapping.")
        header_index = header_indexes[0]
    headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()] if header_index >= 0 else [""] * raw.shape[1]
    units = _rheology_sweep_units(raw, header_index=header_index, columns=selected_columns) if header_index >= 0 else []
    source_x_unit, x_authority = _sweep_source_unit(headers, units, x_index, default_x_unit, explicit=explicit_units)
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
        source_unit, unit_authority = _sweep_source_unit(headers, units, metric_index, default_unit, explicit=explicit_units)
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
            "source_header": headers[metric_index], "source_column": metric_index,
            "source_unit_authority": unit_authority,
        }
    rows: list[dict[str, float]] = []
    for row_index in numeric_rows:
        x_value = _float(raw.iat[row_index, x_index], decimal_comma=block.decimal_comma)
        if x_value is None:
            continue
        row: dict[str, float] = {"x": x_value * x_factor}
        for key, metric_index in metric_indexes.items():
            y_value = _float(raw.iat[row_index, metric_index], decimal_comma=block.decimal_comma)
            if y_value is not None:
                row[key] = y_value * metric_factors[key]
        rows.append(row)
    empty_metrics = [
        key for key in metric_indexes if not any(key in row for row in rows)
    ]
    if empty_metrics:
        raise ValueError(
            f"Confirmed rheology columns contain no numeric values in {source}: "
            f"{', '.join(empty_metrics)}."
        )

    complete_sweep_metrics(rows, metric_units, metric_conversions, x_label=x_label, x_unit=x_unit)
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
            "source_header": headers[x_index], "source_column": x_index,
            "source_unit_authority": x_authority,
        },
        metric_conversions=metric_conversions,
    )


def _read_confirmed_rheology_sweep_samples(
    source: Path,
    column_confirmations: list[dict[str, Any]],
    *,
    x_label: str,
    default_x_unit: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> list[RheologySweepSample]:
    confirmations = [item for item in column_confirmations if has_column_intent(item)]
    if not confirmations:
        return []
    samples: list[RheologySweepSample] = []
    errors: list[str] = []
    candidates = _sweep_source_files(source)
    assignments: dict[Path, dict[str, Any]] = {}
    for confirmation in confirmations:
        locator = confirmation.get("source_path")
        if not isinstance(locator, str) or not Path(locator).is_absolute():
            raise ValueError("Confirmed rheology history requires its exact recorded source path; reconfirm the source.")
        matches = [candidate for candidate in candidates
                   if literal_source_path(candidate) == literal_source_path(Path(locator))]
        if len(matches) != 1:
            raise ValueError("A confirmation does not identify one exact selected source; reconfirm ambiguous history.")
        candidate = matches[0]
        if candidate in assignments:
            raise ValueError("Duplicate or conflicting confirmations for one source.")
        if confirmation.get("source_sha256") and file_sha256(candidate) != confirmation["source_sha256"]:
            raise ValueError("The confirmed rheology source version changed; reconfirm the current bytes.")
        assignments[candidate] = confirmation
    if set(assignments) != set(candidates):
        raise ValueError("Explicit rheology columns must cover every selected source; silent partial datasets are not allowed.")
    for candidate, confirmation in assignments.items():
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


def check_confirmed_rheology_bytes(name: str, content: bytes, confirmation: dict[str, Any], *, rule_id: str) -> None:
    """Check executable choice on captured bytes before allocating a project."""
    frequency = get_rule(rule_id).scientific_source_adapter == "rheology_frequency"
    with TemporaryDirectory(prefix="sciplot-intake-confirmation-") as directory:
        path = Path(directory) / safe_filename(name)
        path.write_bytes(content)
        _confirmed_rheology_sweep_sample(path, confirmation,
            x_label="Angular Frequency" if frequency else "Temperature",
            default_x_unit="rad/s" if frequency else "°C",
            metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS if frequency else _RHEOLOGY_SWEEP_METRICS)


def read_rheology_sweep_samples(
    source: Path, column_confirmations: object,
    automatic_reader: Callable[[Path], list[RheologySweepSample]], *,
    rule_id: str,
    x_label: str, default_x_unit: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> list[RheologySweepSample]:
    """Explicit scientific intent wins; auto preview evidence never overrides it."""
    confirmations = require_supported_confirmations(get_rule(rule_id), column_confirmations)
    if any(has_column_intent(item) for item in confirmations):
        return _read_confirmed_rheology_sweep_samples(source, confirmations, x_label=x_label,
            default_x_unit=default_x_unit, metrics=metrics)
    return automatic_reader(source)
