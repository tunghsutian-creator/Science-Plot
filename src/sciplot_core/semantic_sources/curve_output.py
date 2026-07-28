"""Write aligned paired-curve tables for processed semantic outputs."""

from __future__ import annotations

from pathlib import Path
import pandas as pd


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)


def _write_curve_table(
    series_list: list[CurveSeriesPayload], output_path: Path
) -> None:
    max_points = max(len(series.points) for series in series_list)
    rows: list[list[object]] = [[], [], []]
    for series in series_list:
        rows[0].extend([series.x_label, series.y_label])
        rows[1].extend([series.x_unit, series.y_unit])
        rows[2].extend([series.sample, series.sample])
    for point_index in range(max_points):
        row: list[object] = []
        for series in series_list:
            if point_index < len(series.points):
                x_value, y_value = series.points[point_index]
                row.extend([x_value, y_value])
            else:
                row.extend(["", ""])
        rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, header=False, index=False)
