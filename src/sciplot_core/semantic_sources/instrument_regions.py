"""Observe original Test/Result/Interval regions without choosing scientific axes."""
from __future__ import annotations

from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text as _clean_text, token as _token
from sciplot_core.semantic_sources.numeric_separators import parse_numeric_cell as _float
from sciplot_core.semantic_sources.paired_curve_table_metadata import looks_like_unit as _looks_like_unit


class InstrumentLayoutError(ValueError):
    """An observed instrument wrapper has no unambiguous measurement body."""

    def __init__(self, message: str, row: int) -> None:
        super().__init__(f"{message} (original row {row + 1}).")
        self.row = row


def _rheology_test_bounds(raw: pd.DataFrame) -> list[tuple[int, int, str | None]]:
    """Observe literal Test spans without dropping or reordering source rows."""
    starts = [row for row in range(len(raw)) if raw.shape[1] and _token(raw.iat[row, 0]) == "test"]
    headers = [row for row in range(len(raw)) if raw.shape[1] and _token(raw.iat[row, 0]) == "intervaldata"]
    documents = []
    for row in range(len(raw)):
        marker = _clean_text(raw.iat[row, 0]) if raw.shape[1] else ""
        if _token(marker) != "project" or not marker.endswith(":") or not headers or row < headers[0]:
            continue
        following = next((start for start in starts if start > row), None)
        if following is None or any(any(_clean_text(value) for value in raw.iloc[index])
                                    for index in range(row + 1, following)):
            raise InstrumentLayoutError("A repeated Project wrapper must lead directly through layout spacers to an original Test", int(raw.index[row]))
        documents.append(row)
    if not starts:
        return [(0, len(raw), None)]
    bounds: list[tuple[int, int, str | None]] = []
    if any(_token(raw.iat[row, 0]) == "intervaldata" for row in range(starts[0])):
        bounds.append((0, next((row for row in documents if row < starts[0]), starts[0]), None))
    for index, start in enumerate(starts):
        sample = _clean_text(raw.iat[start, 1]) if raw.shape[1] > 1 else ""
        if not sample:
            raise InstrumentLayoutError("A literal Test marker has no Test name", int(raw.index[start]))
        stop = starts[index + 1] if index + 1 < len(starts) else len(raw)
        stop = next((row for row in documents if start < row < stop), stop)
        bounds.append((start, stop, sample))
    return bounds


def rheology_instrument_regions(raw: pd.DataFrame) -> list[dict[str, Any]] | None:
    """Observe bounded Test/Result/Interval bodies, independently of any axes.

    An interval header declares its record members. Original records in those
    members establish the body; numeric statistics and a declared count do not.
    Only outer layout spacers are excluded. An interior empty/disconnected body
    needs an explicit source selection instead of an inferred join or deletion.
    """
    if not raw.shape[1]:
        return None
    markers = {"test", "result", "intervalanddatapoints", "intervaldata"}
    for row in range(len(raw)):
        marker = _clean_text(raw.iat[row, 0])
        if marker.endswith(":") and _token(marker).startswith("interval") and _token(marker) not in markers:
            raise InstrumentLayoutError("Unsupported original interval marker", int(raw.index[row]))
    observed = [(row, _token(raw.iat[row, 0])) for row in range(len(raw))
                if _token(raw.iat[row, 0]) in markers]
    if not any(kind in {"intervaldata", "intervalanddatapoints"}
               or _clean_text(raw.iat[row, 0]).endswith(":") for row, kind in observed):
        return None
    headers = [row for row, kind in observed if kind == "intervaldata"]
    if not headers:
        raise InstrumentLayoutError("Instrument metadata has no supported Interval data header", int(raw.index[observed[0][0]]))
    regions = []
    for test_start, test_end, sample in _rheology_test_bounds(raw):
        test_headers = [header for header in headers if test_start <= header < test_end]
        if not test_headers:
            raise InstrumentLayoutError("An original Test contains no supported measurement interval", int(raw.index[test_start]))
        for interval_index, header in enumerate(test_headers):
            stop = next((row for row, _kind in observed if row > header), test_end)
            stop = min(stop, test_end)
            members = [column for column in range(1, raw.shape[1]) if _clean_text(raw.iat[header, column])]
            if not members:
                raise InstrumentLayoutError("An Interval data header declares no record columns", int(raw.index[header]))
            row = header + 1
            while row < stop and not any(_clean_text(value) for value in raw.iloc[row]):
                row += 1
            unit_row = None
            if row < stop:
                values = [_clean_text(raw.iat[row, column]) for column in members]
                if all(not value or _float(value) is None for value in values):
                    literal_unit = any(value.startswith("[") and value.endswith("]") and value[1:-1].strip()
                                       for value in values)
                    if literal_unit or any(_looks_like_unit(value.strip("[]() ")) for value in values if value):
                        unit_row = row
                        row += 1
                    else:
                        raise InstrumentLayoutError("The first interval row has no unambiguous unit or record identity", int(raw.index[row]))
            while row < stop and not any(_clean_text(value) for value in raw.iloc[row]):
                row += 1
            start = row
            end = start
            closed = False
            for row in range(start, stop):
                values = [_clean_text(value) for value in raw.iloc[row]]
                if not any(values):
                    closed = True
                    continue
                if closed:
                    raise InstrumentLayoutError("An instrument body is disconnected by an ambiguous empty region", int(raw.index[row]))
                if values[0] or any(value for column, value in enumerate(values) if column and column not in members):
                    raise InstrumentLayoutError("Unsupported metadata or undeclared cells inside an instrument body", int(raw.index[row]))
                if all(values[column] == _clean_text(raw.iat[header, column]) for column in members):
                    raise InstrumentLayoutError("An unlabelled repeated instrument header requires an exact source region", int(raw.index[row]))
                end = row + 1
            if end == start:
                raise InstrumentLayoutError("An original interval contains no record evidence", int(raw.index[header]))
            result_row = next((row for row, kind in reversed(observed)
                               if kind == "result" and test_start <= row < header), None)
            test_row = test_start if sample is not None else None
            region: dict[str, Any] = {"header_row": int(raw.index[header]),
                      "data_start_row": int(raw.index[start]), "data_end_row": int(raw.index[end - 1]) + 1,
                      "point_count": end - start, "interval_index": interval_index + 1,
                      "interval_count": len(test_headers)}
            if unit_row is not None:
                region["unit_row"] = int(raw.index[unit_row])
            if test_row is not None:
                region.update(test_name=sample, test_row=int(raw.index[test_row]))
            if result_row is not None:
                region.update(result=_clean_text(raw.iat[result_row, 1]) if raw.shape[1] > 1 else "",
                              result_row=int(raw.index[result_row]))
            regions.append(region)
    return regions
