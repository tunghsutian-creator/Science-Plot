"""Original interval bindings for explicitly labelled rheology frequency exports."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.semantic_sources.models import _RHEOLOGY_FREQUENCY_OUTPUT_METRICS
from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _find_rheology_sweep_headers, _frequency_result_sections,
)


def instrument_frequency_candidate(frame: pd.DataFrame, *, sheet: str | None, position: int,
                                   source: Path, column_reader: Any, finite: Any, unit_reader: Any) -> dict[str, Any] | None:
    """Project exact original interval rows; never manufacture magnitude columns."""
    if not any(token(frame.iat[index, 0]) == "intervaldata" for index in range(len(frame))):
        return None
    try:
        headers = _find_rheology_sweep_headers(frame,
            x_aliases=("angularfrequency", "frequency", "omega", "ω"), metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS)
    except ValueError:
        return None
    sample = next((clean_text(frame.iat[index, 1]) for index in range(len(frame))
                   if token(frame.iat[index, 0]) == "test" and frame.shape[1] > 1), source.stem)
    sections = _frequency_result_sections(frame, sample)
    if len(headers) != len(sections):
        # Repeated unlabelled intervals need an explicit scientific mapping.
        return None
    blocks = []
    all_columns = []
    for index, (_original_label, section, interval) in enumerate(sections):
        header = headers[index]
        sample = next((clean_text(frame.iat[row, 1]) for row in range(header - 1, -1, -1)
                       if token(frame.iat[row, 0]) == "test" and frame.shape[1] > 1), source.stem)
        if interval is not None:
            bound_interval = {**interval, "sample": sample}
            label = f"{sample} · {interval['nominal_temperature']:g} °C"
        else:
            bound_interval = None
            label = sample
        unit_rows = [row for row in (header + 1, header + 2) if row < len(frame)]
        unit_row = max(unit_rows, key=lambda row: sum(bool(unit_reader(value)) for value in frame.iloc[row]))
        start = unit_row + 1
        stop = int(section.index[-1]) + 1
        frequencies = [column for column in range(frame.shape[1])
                       if token(frame.iat[header, column]) in {"angularfrequency", "frequency", "omega", "ω"}]
        if len(frequencies) != 1:
            return None
        x_index = frequencies[0]
        rows = [row for row in range(start, stop) if finite(frame.iat[row, x_index]) is not None]
        if not rows or rows != list(range(rows[0], rows[-1] + 1)):
            raise ValueError("Frequency interval data must be one contiguous original numeric region.")
        start, end = rows[0], rows[-1] + 1
        columns = [column_reader(frame.iloc[:end], column, header, unit_row, start) for column in range(frame.shape[1])]
        selection = {"sheet": sheet, "header_rows": [header], "unit_row": unit_row,
                     "data_start_row": start, "data_end_row": end}
        block = {"block_id": f"block:{index}", "order": index, "columns": columns,
                 "column_indices": [column["column_index"] for column in columns],
                 "data_start_row": start, "data_end_row": end, "point_count": len(rows),
                 "time_column": None, "time_columns": [], "segments": [],
                 "temperature_columns": [column["column_id"] for column in columns if column["quantity"] == "temperature"],
                 "response_columns": [column["column_id"] for column in columns
                    if column["unit"] and column["quantity"] not in {"temperature", "angular_frequency"}],
                 "table_selection": selection, "sample": sample, "label": label, "source_interval": bound_interval}
        magnitude = [column for column in columns if column["quantity"] == "complex_viscosity"]
        storage = [column for column in columns if column["quantity"] == "storage_modulus"]
        loss = [column for column in columns if column["quantity"] == "loss_modulus"]
        if not magnitude and len(storage) == len(loss) == 1:
            block["derived_coordinates"] = {"complex_viscosity": {
                "quantity": "complex_viscosity", "unit": "Pa s", "method": "derived_from_storage_and_loss_modulus",
                "formula": "hypot(storage_modulus, loss_modulus) / angular_frequency",
                "inputs": {"angular_frequency": columns[x_index], "storage_modulus": storage[0], "loss_modulus": loss[0]}}}
        blocks.append(block)
        all_columns = all_columns or columns
    return {"candidate_id": f"table:{position}", "sheet": sheet, "table_selection": blocks[0]["table_selection"],
            "columns": all_columns, "blocks": blocks, "ambiguities": [], "format": "rheology_frequency_intervals"}
