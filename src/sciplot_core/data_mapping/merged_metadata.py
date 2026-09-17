"""Expose workbook merge declarations and resolve explicitly selected metadata."""

from __future__ import annotations

from pathlib import Path
import posixpath
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd

from sciplot_core.data_mapping.column_choice import _original_text
from sciplot_core.source_tables.read_session import read_table_once


def _coordinate(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?([1-9][0-9]*)", value)
    if match is None:
        raise ValueError("Invalid original merge-cell coordinate.")
    column = 0
    for letter in match[1].upper():
        column = column * 26 + ord(letter) - ord("A") + 1
    return int(match[2]), column


def merged_metadata_ranges(source: Path, sheet: str | None) -> list[dict[str, int]]:
    if source.suffix.casefold() not in {".xlsx", ".xlsm"}:
        return []

    def read() -> pd.DataFrame:
        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        with ZipFile(source) as archive:
            book = ET.fromstring(archive.read("xl/workbook.xml"))
            sheets = book.findall(f"{{{main}}}sheets/{{{main}}}sheet")
            selected = next((item for item in sheets if item.get("name") == sheet), None)
            if selected is None:
                raise ValueError("Merged metadata requires an exact original worksheet.")
            links = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            target = next(item.attrib["Target"] for item in links
                          if item.get("Id") == selected.get(f"{{{rel}}}id"))
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")
            records = []
            with archive.open(member) as stream:
                for _event, element in ET.iterparse(stream, events=("end",)):
                    if element.tag == f"{{{main}}}mergeCell":
                        ends = element.attrib["ref"].split(":")
                        top, left = _coordinate(ends[0])
                        bottom, right = _coordinate(ends[-1])
                        if len(ends) > 2 or bottom < top or right < left:
                            raise ValueError("Invalid original merged-cell range.")
                        records.append({"row_start": top - 1, "row_end": bottom,
                                        "column_start": left - 1, "column_end": right})
                    element.clear()
        return pd.DataFrame(records)

    frame = read_table_once(source, ("merged_metadata", sheet), read)
    return [{str(key): int(value) for key, value in row.items()} for row in frame.to_dict("records")]


def selected_metadata_cells(
    frame: pd.DataFrame, rows: list[int], *, ranges: list[dict[str, int]], data_start: int,
) -> tuple[dict[tuple[int, int], str], dict[int, dict[str, str]], list[dict[str, Any]]]:
    resolved: dict[tuple[int, int], str] = {}
    evidence: dict[int, dict[str, str]] = {}
    associations = []
    for merged in ranges:
        selected = [row for row in rows if merged["row_start"] <= row < merged["row_end"]]
        if not selected:
            continue
        if merged["row_end"] > data_start or merged["column_end"] > frame.shape[1]:
            raise ValueError("Merged metadata must lie wholly above data and inside the original table.")
        top, left = merged["row_start"], merged["column_start"]
        text = _original_text(frame.iat[top, left])
        associations.append({**merged, "anchor": {"row_index": top, "column_index": left, "text": text}})
        for row in selected:
            for column in range(left, merged["column_end"]):
                resolved[row, column] = text
                evidence.setdefault(column, {})[f"{top},{left}"] = text
    return resolved, evidence, associations
