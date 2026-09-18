"""Bounded structural evidence and conservative repair of explicit XY layouts."""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sciplot_core.data_mapping.table_choice import _read, select_table


def table_diagnostics(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Locate numeric extents, retaining holes as problems rather than removing them."""
    tables = []
    source = Path(snapshot["source"])
    for table in snapshot["tables"][:8]:
        frame = _read(source, table["sheet"], snapshot["file_sha256"])
        columns = []
        for index in range(min(frame.shape[1], 24)):
            values = pd.to_numeric(frame.iloc[:, index], errors="coerce").to_numpy(dtype=float)
            rows = np.flatnonzero(np.isfinite(values))
            if not len(rows):
                continue
            start, end = int(rows[0]), int(rows[-1]) + 1
            columns.append({"index": index, "first_numeric_row": start, "data_end_row": end,
                            "numeric_count": int(len(rows)), "invalid_inside": end - start - int(len(rows))})
        tables.append({"sheet": table["sheet"], "columns": columns,
                       "columns_truncated": frame.shape[1] > 24})
    return {"indices": "zero_based; data_end_row exclusive", "tables": tables,
            "tables_truncated": len(snapshot["tables"]) > 8,
            "interpretation": "Numeric extents are evidence, not selected ranges. Numeric sample IDs and summary rows may lie inside; never drop holes or infer quantities/units from magnitudes."}


def explicit_layout_mapping(snapshot: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any] | None:
    """Repair only one complete header/unit/sample layout with unique paired identities."""
    if len(snapshot["tables"]) != 1 or not diagnostics["tables"]:
        return None
    table = snapshot["tables"][0]
    columns = diagnostics["tables"][0]["columns"]
    count = table["column_count"]
    if not 2 <= count <= 24 or count % 2 or len(columns) != count:
        return None
    bounds = {(item["first_numeric_row"], item["data_end_row"]) for item in columns}
    if len(bounds) != 1 or any(item["invalid_inside"] for item in columns):
        return None
    start, end = next(iter(bounds))
    if start < 3 or end != table["row_count"]:
        return None
    selection = {"sheet": table["sheet"], "header_rows": [start - 3], "unit_row": start - 2,
                 "sample_row": start - 1, "data_start_row": start, "data_end_row": end}
    selected = select_table(snapshot, selection)
    samples = []
    for index in range(0, count, 2):
        x, y = selected["columns"][index:index+2]
        if not x["x_eligible"] or not y["y_eligible"] or not x["sample"] or x["sample"] != y["sample"]:
            return None
        samples.append(x["sample"])
    if len(set(samples)) != len(samples):
        return None
    return {"source_sha256": snapshot["file_sha256"], "table_selection": selection,
            "column_mapping": {"pairs": [{"x_column": i, "y_column": i+1} for i in range(0, count, 2)]}}
