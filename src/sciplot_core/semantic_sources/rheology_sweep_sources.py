"""Read and normalize rheology sweep comparison samples."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import re
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)
from sciplot_core.semantic_sources.rheology_units import _unit_conversion as _unit_conversion
from sciplot_core.semantic_sources.rheology_frequency_metrics import (
    complete_sweep_metrics,
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
    _float,
    _read_raw_table_normalized,
)

from sciplot_core.semantic_sources.series_labels import (
    _source_display_sample,
)

from sciplot_core.semantic_sources.rheology_ordering import (
    _sweep_sample_order_key,
)

from sciplot_core.semantic_sources.rheology_sweep_columns import (
    _find_rheology_sweep_headers as _find_rheology_sweep_headers,
    _rheology_sweep_units as _rheology_sweep_units,
    _sweep_metric_column as _sweep_metric_column,
    _sweep_source_unit as _sweep_source_unit,
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


def _frequency_result_sections(
    raw: pd.DataFrame, sample: str,
) -> list[tuple[str, pd.DataFrame, dict[str, Any] | None]]:
    """Keep explicitly temperature-labelled instrument results as distinct traces.

    A measured temperature column can drift during a sweep. Only the literal
    Result metadata establishes the nominal condition; no measured values are
    rounded or regrouped into temperatures. Other sweep formats keep their
    existing interval interpretation.
    """
    results: list[tuple[int, str, str, float]] = []
    for index in range(len(raw)):
        if _token(raw.iat[index, 0]) != "result":
            continue
        text = _clean_text(raw.iat[index, 1]) if raw.shape[1] > 1 else ""
        temperature = re.fullmatch(r"(?:FS|Frequency\s+Sweep)\s+([+-]?\d+(?:\.\d+)?)\s*(?:°C|℃)", text, flags=re.IGNORECASE)
        if temperature is None:
            continue
        results.append((index, text, temperature[1], float(temperature[1])))
    all_results = [index for index in range(len(raw)) if _token(raw.iat[index, 0]) == "result"]
    if results and len(all_results) != len(results):
        raise ValueError("Mixed frequency Result metadata cannot be silently merged; bind each original result explicitly.")
    if len(results) <= 1:
        return [(sample, raw, None)]
    sections = []
    for position, (start, text, nominal_text, nominal) in enumerate(results):
        stop = results[position + 1][0] if position + 1 < len(results) else len(raw)
        block = raw.iloc[start:stop]
        header_indexes = _find_rheology_sweep_headers(block, x_aliases=("angularfrequency", "frequency", "omega", "ω"), metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS)
        if len(header_indexes) != 1:
            raise ValueError("Each temperature-labelled frequency Result must contain exactly one original interval.")
        header = header_indexes[0]
        headers = [_clean_text(value) for value in block.iloc[header].tolist()]
        x_index = _find_column(headers, ("angularfrequency", "frequency", "omega", "ω"))
        numeric = [index for index in range(header + 1, len(block)) if _float(block.iat[index, x_index]) is not None]
        if not numeric:
            raise ValueError("A temperature-labelled frequency Result contains no numeric observations.")
        label = f"{sample} · {nominal_text} °C"
        sections.append((label, block, {"sample": sample, "result": text,
            "result_row": int(raw.index[start]), "nominal_temperature": nominal,
            "nominal_temperature_unit": "°C", "header_row": int(block.index[header]),
            "data_start_row": int(block.index[numeric[0]]), "data_end_row": int(block.index[numeric[-1]]) + 1,
            "point_count": len(numeric), "interval_index": position + 1,
            "interval_count": len(results), "basis": "literal original Result metadata; measured temperatures retained"}))
    return sections


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
            metric_index = _sweep_metric_column(headers, key, aliases)
        except LookupError:
            continue
        metric_indexes[key] = metric_index
    if not metric_indexes:
        raise ValueError(f"Could not find a requested rheology response in {source}.")
    units = _rheology_sweep_units(
        raw,
        header_index=header_index,
        columns=(x_index, *metric_indexes.values()),
    )
    explicit_units = _token(x_label) == 'angularfrequency'
    source_x_unit, x_unit_authority = _sweep_source_unit(
        headers, units, x_index, default_x_unit, explicit=explicit_units,
    )
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
        source_unit, unit_authority = _sweep_source_unit(
            headers, units, metric_index, default_unit, explicit=explicit_units,
        )
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
            'source_header': headers[metric_index],
            'source_column': metric_index,
            'source_unit_authority': unit_authority,
        }
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
        if any(key in row for key in metric_indexes):
            rows.append(row)
    if not rows:
        raise ValueError(f"No numeric rheology sweep points found in {source}.")
    complete_sweep_metrics(rows, metric_units, metric_conversions, x_label=x_label, x_unit=x_unit)
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
            'source_header': headers[x_index],
            'source_column': x_index,
            'source_unit_authority': x_unit_authority,
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
                sections = (_frequency_result_sections(block, sample) if x_label == "Angular Frequency" else [(sample, block, None)])
                for label, section, evidence in sections:
                    parsed = _read_rheology_sweep_sample(
                        candidate,
                        x_aliases=x_aliases,
                        x_label=x_label,
                        default_x_unit=default_x_unit,
                        interval_selection=interval_selection,
                        metrics=metrics,
                        raw=section,
                        sample=label,
                    )
                    if evidence is not None:
                        parsed = replace(parsed, interval_count=evidence["interval_count"],
                            selected_interval_index=evidence["interval_index"],
                            interval_selection_policy="explicit_result_temperature", source_interval=evidence)
                    samples.append(parsed)
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
    # Explicit result conditions already have an authoritative acquisition
    # order. Sorting by measured modulus must not reorder those conditions.
    if any(sample.source_interval is not None for sample in samples):
        return samples
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
