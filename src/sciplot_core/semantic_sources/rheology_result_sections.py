"""Separate original frequency Result blocks using literal temperature metadata."""

import re
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text as _clean_text, token as _token
from sciplot_core.semantic_sources.models import _RHEOLOGY_FREQUENCY_OUTPUT_METRICS
from sciplot_core.semantic_sources.rheology_sweep_columns import FREQUENCY_X_ALIASES, _find_rheology_sweep_headers
from sciplot_core.semantic_sources.table_scanning import _find_column, _float


def frequency_result_condition(text: str) -> tuple[str, float] | None:
    """Read the registered frequency Result condition without reading a source."""
    temperature = re.fullmatch(r"(?:FS|Frequency\s+Sweep)\s+([+-]?\d+(?:\.\d+)?)\s*(?:°C|℃)", text, flags=re.IGNORECASE)
    return (temperature[1], float(temperature[1])) if temperature is not None else None


def _frequency_result_sections(
    raw: pd.DataFrame, sample: str, *, source_regions: list[dict[str, Any]] | None = None,
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
        temperature = frequency_result_condition(text)
        if temperature is None:
            continue
        results.append((index, text, temperature[0], temperature[1]))
    all_results = [index for index in range(len(raw)) if _token(raw.iat[index, 0]) == "result"]
    if results and len(all_results) != len(results):
        raise ValueError("Mixed frequency Result metadata cannot be silently merged; bind each original result explicitly.")
    if len(results) <= 1:
        return [(sample, raw, None)]
    sections: list[tuple[str, pd.DataFrame, dict[str, Any] | None]] = []
    for position, (start, text, nominal_text, nominal) in enumerate(results):
        stop = results[position + 1][0] if position + 1 < len(results) else len(raw)
        block = raw.iloc[start:stop]
        header_indexes = _find_rheology_sweep_headers(block, x_aliases=FREQUENCY_X_ALIASES, metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS)
        if len(header_indexes) != 1:
            raise ValueError("Each temperature-labelled frequency Result must contain exactly one original interval.")
        header = header_indexes[0]
        headers = [_clean_text(value) for value in block.iloc[header].tolist()]
        x_index = _find_column(headers, ("angularfrequency", "frequency", "omega", "ω"))
        region = next((region for region in (source_regions or [])
                       if region["header_row"] == int(block.index[header])), None)
        records = ([index for index in range(len(block))
                    if region["data_start_row"] <= int(block.index[index]) < region["data_end_row"]]
                   if region is not None else [index for index in range(header + 1, len(block))
                                               if _float(block.iat[index, x_index]) is not None])
        if not records:
            raise ValueError("A temperature-labelled frequency Result contains no numeric observations.")
        label = f"{sample} · {nominal_text} °C"
        sections.append((label, block, {"sample": sample, "result": text,
            "result_row": int(raw.index[start]), "nominal_temperature": nominal,
            "nominal_temperature_unit": "°C", "header_row": int(block.index[header]),
            "data_start_row": int(block.index[records[0]]), "data_end_row": int(block.index[records[-1]]) + 1,
            "point_count": len(records), "interval_index": position + 1,
            "interval_count": len(results), "basis": "literal original Result metadata; measured temperatures retained"}))
    return sections
