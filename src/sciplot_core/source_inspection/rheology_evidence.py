"""Original physical interval bindings, independent of scientific interpretation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.semantic_sources.table_scanning import (
    InstrumentLayoutError, rheology_instrument_regions,
)
from sciplot_core.source_inspection.input_errors import SourceInputError


def instrument_candidate(frame: pd.DataFrame, *, sheet: str | None, position: int,
                         source: Path, column_reader: Any) -> dict[str, Any] | None:
    """Project every original region without choosing an axis, recipe or formula."""
    try:
        regions = rheology_instrument_regions(frame)
    except InstrumentLayoutError as exc:
        raise SourceInputError("instrument_layout_unsupported", str(exc), repair={
            "action": "inspect_original_table", "source": str(source), "sheet": sheet,
            "row_index": exc.row,
            "message": "Preserve this task and original cells; resolve the unsupported original layout before creation. No whole-file numeric fallback was used.",
        }) from exc
    if regions is None:
        return None
    blocks = []
    all_columns = []
    for index, region in enumerate(regions):
        header, unit_row = region["header_row"], region.get("unit_row")
        start, end = region["data_start_row"], region["data_end_row"]
        sample = region.get("test_name", source.stem)
        columns = [column_reader(frame.iloc[:end], column, header, unit_row, start) for column in range(frame.shape[1])]
        selection = {"sheet": sheet, "header_rows": [header],
                     "data_start_row": start, "data_end_row": end}
        if unit_row is not None:
            selection["unit_row"] = unit_row
        times = [column["column_id"] for column in columns if column["quantity"] == "time"]
        block = {"block_id": f"block:{index}", "order": index, "columns": columns,
                 "column_indices": [column["column_index"] for column in columns],
                 "data_start_row": start, "data_end_row": end, "point_count": region["point_count"],
                 "time_column": times[0] if len(times) == 1 else None, "time_columns": times, "segments": [],
                 "temperature_columns": [column["column_id"] for column in columns if column["quantity"] == "temperature"],
                 "response_columns": [column["column_id"] for column in columns
                    if column["unit"] and column["quantity"] not in {"time", "temperature", "angular_frequency"}],
                 "table_selection": selection, "sample": sample, "label": sample,
                 "source_interval": {**region, "sample": sample,
                                     "basis": "literal original Test/Result/Interval physical rows"}}
        block.update({key: region[key] for key in ("test_name", "test_row", "result", "result_row") if key in region})
        blocks.append(block)
        all_columns = all_columns or columns
    return {"candidate_id": f"table:{position}", "sheet": sheet, "table_selection": blocks[0]["table_selection"],
            "columns": all_columns, "blocks": blocks, "ambiguities": [], "format": "instrument_intervals"}
