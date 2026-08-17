"""Read and normalize rheology sweep comparison samples."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)
from sciplot_core.materials_rules import (
    format_unit_label,
)


from sciplot_core.semantic_sources.models import (
    RheologySweepSample,
    _RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
    _RHEOLOGY_SWEEP_METRICS,
)
from sciplot_core.semantic_sources.numeric_separators import (
    selected_columns_use_decimal_comma,
)

from sciplot_core.semantic_sources.table_scanning import (
    _sample_from_interval_metadata,
    _rheology_test_sections,
    _find_column,
    _unit_for,
    _float,
    _read_raw_table_normalized,
    _axis_match,
    _unit_row_score,
)

from sciplot_core.semantic_sources.series_labels import (
    _source_display_sample,
)

from sciplot_core.semantic_sources.rheology_ordering import (
    _sweep_sample_order_key,
)


def _sweep_source_files(source: Path) -> list[Path]:
    if not source.is_dir():
        return [source]
    suffixes = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
    candidates = sorted(
        (
            child
            for child in source.iterdir()
            if child.is_file() and child.suffix.lower() in suffixes
        ),
        key=lambda path: path.name.casefold(),
    )
    instrument_exports = [
        candidate
        for candidate in candidates
        if candidate.suffix.lower() in {".csv", ".tsv", ".txt"}
    ]
    # Instrument folders often retain an Origin/Excel workbook derived from
    # the same raw exports.  Prefer the original text exports as the sole
    # evidence surface so a saved analysis workbook cannot become a duplicate
    # sample during direct CLI preparation.
    return instrument_exports or candidates


def selected_rheology_sweep_source_files(source: Path) -> tuple[Path, ...]:
    """Return the exact ordered files selected by the sweep parser.

    Workflow task-source attestations need to fingerprint the same evidence
    surface as semantic preparation.  Keeping this projection beside the
    parser prevents adapters from independently rediscovering files or
    accidentally including a derived workbook alongside raw text exports.
    """

    return tuple(path.expanduser().resolve() for path in _sweep_source_files(source))


def _find_rheology_sweep_headers(
    raw: pd.DataFrame,
    *,
    x_aliases: tuple[str, ...],
    metrics: tuple[
        tuple[str, str, tuple[str, ...], str], ...
    ] = _RHEOLOGY_SWEEP_METRICS,
) -> list[int]:
    metric_alias_groups = tuple(metric[2] for metric in metrics)

    def is_sweep_header(row_index: int) -> bool:
        headers = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        try:
            _find_column(headers, x_aliases)
            return any(
                any(_axis_match(header, aliases) for header in headers)
                for aliases in metric_alias_groups
            )
        except ValueError:
            return False

    # Instrument exports can include project metadata such as an operator name
    # containing the single-letter symbolic alias ``G``.  That metadata may
    # also contain "frequency sweep", so a loose token scan can mistake it for
    # the table header.  The explicitly labelled interval header is the
    # authority whenever it exists; the generic scan remains available for
    # plain public tables without an interval wrapper.
    interval_matches = [
        row_index
        for row_index in range(raw.shape[0])
        if _token(raw.iat[row_index, 0] if raw.shape[1] else None) == "intervaldata"
        and is_sweep_header(row_index)
    ]
    if interval_matches:
        return interval_matches

    matches: list[int] = []
    for row_index in range(raw.shape[0]):
        if is_sweep_header(row_index):
            matches.append(row_index)
    if matches:
        return matches
    raise ValueError("Could not find rheology sweep X and requested response columns.")


def _unit_conversion(source_unit: str, target_unit: str) -> tuple[str, float, str]:
    source = format_unit_label(source_unit.strip()).strip()
    target = format_unit_label(target_unit).strip()
    if source == target:
        return target, 1.0, "identity"
    conversions = {
        ("1", "%"): (100.0, "fraction_to_percent"),
        ("fraction", "%"): (100.0, "fraction_to_percent"),
        ("%", "1"): (0.01, "percent_to_fraction"),
        ("fraction", "1"): (1.0, "fraction_identity"),
        ("kPa", "Pa"): (1000.0, "kPa_to_Pa"),
        ("MPa", "Pa"): (1_000_000.0, "MPa_to_Pa"),
        ("Pa", "kPa"): (0.001, "Pa_to_kPa"),
        ("Pa", "MPa"): (0.000001, "Pa_to_MPa"),
        ("Pa·s", "mPa·s"): (1000.0, "Pa_s_to_mPa_s"),
        ("cP", "mPa·s"): (1.0, "cP_to_mPa_s"),
    }
    conversion = conversions.get((source, target))
    if conversion is None:
        return source or target, 1.0, "source_unit_preserved"
    factor, method = conversion
    return target, factor, method


def _rheology_sweep_units(
    raw: pd.DataFrame,
    *,
    header_index: int,
    columns: tuple[int, ...],
) -> list[str]:
    candidates = [
        row_index
        for row_index in (header_index + 1, header_index + 2)
        if row_index < raw.shape[0]
    ]
    if not candidates:
        return []
    best_index = max(
        candidates, key=lambda row_index: _unit_row_score(raw, row_index, columns)
    )
    if _unit_row_score(raw, best_index, columns) <= 0:
        return []
    return [_clean_text(value) for value in raw.iloc[best_index].tolist()]


def _read_rheology_sweep_sample(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    x_label: str,
    default_x_unit: str,
    interval_selection: str = "all_numeric_rows",
    metrics: tuple[
        tuple[str, str, tuple[str, ...], str], ...
    ] = _RHEOLOGY_SWEEP_METRICS,
    raw: pd.DataFrame | None = None,
    sample: str | None = None,
) -> RheologySweepSample:
    raw = (_read_raw_table_normalized(source) if raw is None else raw.copy()).dropna(
        axis=1, how="all"
    )
    header_indexes = _find_rheology_sweep_headers(
        raw, x_aliases=x_aliases, metrics=metrics
    )
    select_last_interval = interval_selection == "last_numeric_interval"
    header_index = header_indexes[-1] if select_last_interval else header_indexes[0]
    headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
    x_index = _find_column(headers, x_aliases)
    metric_indexes: dict[str, int] = {}
    for key, _label, aliases, _default_unit in metrics:
        try:
            metric_index = _find_column(headers, aliases)
        except ValueError:
            continue
        metric_indexes[key] = metric_index
    if not metric_indexes:
        raise ValueError(f"Could not find a requested rheology response in {source}.")
    units = _rheology_sweep_units(
        raw,
        header_index=header_index,
        columns=(x_index, *metric_indexes.values()),
    )
    source_x_unit = _unit_for(units, x_index, default_x_unit)
    x_unit, x_factor, x_method = _unit_conversion(source_x_unit, default_x_unit)
    if x_method == "source_unit_preserved":
        raise ValueError(
            f"Unsupported rheology x unit `{source_x_unit}` in {source}; "
            f"expected a validated conversion to `{format_unit_label(default_x_unit)}`."
        )
    metric_units: dict[str, str] = {}
    metric_factors: dict[str, float] = {}
    metric_conversions: dict[str, dict[str, Any]] = {}
    for key, _label, _aliases, default_unit in metrics:
        metric_index = metric_indexes.get(key)
        if metric_index is None:
            continue
        source_unit = _unit_for(units, metric_index, default_unit)
        output_unit, factor, method = _unit_conversion(source_unit, default_unit)
        if method == "source_unit_preserved":
            raise ValueError(
                f"Unsupported rheology unit `{source_unit}` for metric `{key}` "
                f"in {source}; expected a validated conversion to "
                f"`{format_unit_label(default_unit)}`."
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

    decimal_comma = selected_columns_use_decimal_comma(
        raw,
        start_row=header_index + 1,
        columns=(x_index, *metric_indexes.values()),
    )
    rows: list[dict[str, float]] = []
    for row_index in range(header_index + 1, raw.shape[0]):
        x_value = _float(raw.iat[row_index, x_index], decimal_comma=decimal_comma)
        if x_value is None:
            continue
        row: dict[str, float] = {"x": x_value * x_factor}
        for key, metric_index in metric_indexes.items():
            y_value = _float(
                raw.iat[row_index, metric_index], decimal_comma=decimal_comma
            )
            if y_value is not None:
                row[key] = y_value * metric_factors.get(key, 1.0)
        if should_derive_complex_modulus:
            storage = row.get("storage_modulus")
            loss = row.get("loss_modulus")
            if storage is not None and loss is not None:
                row["complex_modulus"] = math.hypot(storage, loss)
        if any(key in row for key in metric_indexes):
            rows.append(row)
    if not rows:
        raise ValueError(f"No numeric rheology sweep points found in {source}.")
    return RheologySweepSample(
        sample=sample
        or _sample_from_interval_metadata(raw, _source_display_sample(source)),
        source=source,
        x_label=x_label,
        x_unit=x_unit,
        metric_units=metric_units,
        rows=tuple(rows),
        interval_count=len(header_indexes),
        selected_interval_index=(len(header_indexes) if select_last_interval else 1),
        interval_selection_policy=(
            "last_numeric_interval"
            if select_last_interval and len(header_indexes) > 1
            else "single_interval"
        ),
        source_x_unit=source_x_unit,
        x_conversion={
            "source_unit": source_x_unit,
            "output_unit": x_unit,
            "factor": x_factor,
            "method": x_method,
        },
        metric_conversions=metric_conversions,
    )


def _read_rheology_sweep_comparison_samples(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    x_label: str,
    default_x_unit: str,
    interval_selection: str = "all_numeric_rows",
    metrics: tuple[
        tuple[str, str, tuple[str, ...], str], ...
    ] = _RHEOLOGY_SWEEP_METRICS,
    strict_scope: bool = True,
) -> list[RheologySweepSample]:
    samples: list[RheologySweepSample] = []
    candidates = _sweep_source_files(source)
    errors: list[str] = []
    for candidate in candidates:
        try:
            raw = _read_raw_table_normalized(candidate).dropna(axis=1, how="all")
            for sample, block in _rheology_test_sections(
                raw,
                fallback=_source_display_sample(candidate),
            ):
                samples.append(
                    _read_rheology_sweep_sample(
                        candidate,
                        x_aliases=x_aliases,
                        x_label=x_label,
                        default_x_unit=default_x_unit,
                        interval_selection=interval_selection,
                        metrics=metrics,
                        raw=block,
                        sample=sample,
                    )
                )
        except (OSError, ValueError) as exc:
            errors.append(f"{candidate.name}: {exc}")
    if errors and strict_scope:
        detail = "; ".join(errors[:3])
        raise ValueError(
            "Rheology sweep preparation rejected one or more in-scope source "
            f"files; silent partial datasets are not allowed ({detail})."
        )
    if not samples and strict_scope:
        raise ValueError(f"No rheology sweep exports found under {source}.")
    return sorted(samples, key=_sweep_sample_order_key)


def _read_rheology_frequency_comparison_samples(
    source: Path,
    *,
    strict_scope: bool = True,
) -> list[RheologySweepSample]:
    return _read_rheology_sweep_comparison_samples(
        source,
        x_aliases=("angularfrequency", "frequency", "omega", "ω"),
        x_label="Angular Frequency",
        default_x_unit="rad/s",
        metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
        strict_scope=strict_scope,
    )


def _read_rheology_temperature_comparison_samples(
    source: Path,
    *,
    strict_scope: bool = True,
) -> list[RheologySweepSample]:
    return _read_rheology_sweep_comparison_samples(
        source,
        x_aliases=("temperature", "temp", "温度"),
        x_label="Temperature",
        default_x_unit="°C",
        interval_selection="last_numeric_interval",
        strict_scope=strict_scope,
    )
