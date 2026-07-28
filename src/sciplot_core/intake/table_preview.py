"""Source discovery and bounded table preview generation."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.ingest import smart_decode
from sciplot_core.semantic import is_tensile_export_dir

from .config import (
    _PREVIEW_DISPLAY_COLUMNS,
    _PREVIEW_DISPLAY_ROWS,
    _PREVIEW_SCAN_ROWS,
    _TABLE_EXTENSIONS,
    _TEXT_EXTENSIONS,
)


def _decode_text_preview(path: Path, *, max_bytes: int = 8192) -> str:
    return smart_decode(path.read_bytes()[:max_bytes])[0]


def _tensile_export_dirs(source: Path) -> list[Path]:
    if is_tensile_export_dir(source):
        return [source]
    if not source.is_dir():
        return []
    direct = [path for path in source.iterdir() if is_tensile_export_dir(path)]
    if direct:
        return sorted(direct, key=lambda path: path.name.casefold())
    return sorted(
        (path for path in source.rglob("*") if is_tensile_export_dir(path)),
        key=lambda path: path.name,
    )


def _is_torque_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in _TEXT_EXTENSIONS:
        return False
    text = _decode_text_preview(path).casefold()
    return "screw torque" in text or "转矩" in text


def _torque_files(source: Path) -> list[Path]:
    if _is_torque_file(source):
        return [source]
    if not source.is_dir():
        return []
    return sorted(
        (path for path in source.iterdir() if _is_torque_file(path)),
        key=lambda path: path.name.casefold(),
    )


def _table_files(source: Path) -> list[Path]:
    if source.is_file() and source.suffix.lower() in _TABLE_EXTENSIONS:
        return [source]
    if not source.is_dir():
        return []
    return sorted(
        (
            path
            for path in source.iterdir()
            if path.is_file() and path.suffix.lower() in _TABLE_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )


def _rheology_comparison_files(source: Path) -> list[Path]:
    files = _table_files(source)
    text_files = [
        path for path in files if path.suffix.lower() in {".csv", ".tsv", ".txt"}
    ]
    return text_files or files


def _file_payload(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "name": path.name,
        "source_path": str(path.expanduser().resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _duplicate_source_warnings(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[dict[str, str]]] = {}
    for group in groups:
        sample = str(group.get("sample") or "")
        for item in group.get("files", []):
            if not isinstance(item, dict):
                continue
            digest = str(item.get("sha256") or "")
            if not digest:
                continue
            by_hash.setdefault(digest, []).append(
                {
                    "sample": sample,
                    "name": str(item.get("original_name") or item.get("name") or ""),
                    "source_path": str(item.get("source_path") or ""),
                }
            )
    warnings: list[dict[str, Any]] = []
    for digest, records in sorted(by_hash.items()):
        samples = sorted({record["sample"] for record in records if record["sample"]})
        if len(records) < 2 or len(samples) < 2:
            continue
        warnings.append(
            {
                "id": "duplicate_source_files",
                "severity": "warning",
                "message": (
                    "Multiple sample files have identical byte content; rendered curves may overlap exactly."
                ),
                "sha256": digest,
                "samples": samples,
                "files": records,
            }
        )
    return warnings


def _preview_cell(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _preview_is_number(value: object) -> bool:
    text = _preview_cell(value).replace(",", "").strip()
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _preview_read_frame(
    name: str, content: bytes
) -> tuple[pd.DataFrame, str | None, str | None]:
    suffix = Path(name).suffix.lower()
    encoding: str | None = None
    sheet: str | None = None
    if suffix in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(io.BytesIO(content))
        sheet = str(workbook.sheet_names[0])
        frame = pd.read_excel(
            workbook, sheet_name=sheet, header=None, nrows=_PREVIEW_SCAN_ROWS
        )
    else:
        text, encoding = smart_decode(content)
        buffer = io.StringIO(text)
        try:
            frame = pd.read_csv(
                buffer, sep=None, engine="python", header=None, nrows=_PREVIEW_SCAN_ROWS
            )
        except Exception:
            buffer = io.StringIO(text)
            delimiter = (
                "\t" if suffix in {".tsv", ".txt"} or "\t" in text[:4096] else ","
            )
            frame = pd.read_csv(
                buffer, sep=delimiter, header=None, nrows=_PREVIEW_SCAN_ROWS
            )
    frame = frame.dropna(axis=1, how="all")
    if frame.shape[1] > _PREVIEW_DISPLAY_COLUMNS:
        frame = frame.iloc[:, :_PREVIEW_DISPLAY_COLUMNS]
    return frame, sheet, encoding


def _preview_header_score(frame: pd.DataFrame, row_index: int) -> int:
    row = [_preview_cell(value).strip() for value in frame.iloc[row_index].tolist()]
    non_empty = [value for value in row if value]
    if len(non_empty) < 2:
        return 0
    text_cells = sum(1 for value in non_empty if not _preview_is_number(value))
    numeric_after = 0
    for column_index, header in enumerate(row):
        if not header:
            continue
        for lookahead in range(row_index + 1, min(frame.shape[0], row_index + 8)):
            if _preview_is_number(frame.iat[lookahead, column_index]):
                numeric_after += 1
                break
    return text_cells * 2 + min(len(non_empty), 12) + numeric_after


def _preview_header_row(frame: pd.DataFrame) -> int | None:
    if frame.empty:
        return None
    candidates = [
        (row_index, _preview_header_score(frame, row_index))
        for row_index in range(min(frame.shape[0], 14))
    ]
    row_index, score = max(candidates, key=lambda item: item[1])
    return row_index if score >= 6 else None


def _infer_preview_type(values: list[object]) -> str:
    non_empty = [value for value in values if _preview_cell(value).strip()]
    if not non_empty:
        return "ignore"
    numeric_count = sum(1 for value in non_empty if _preview_is_number(value))
    if numeric_count / len(non_empty) >= 0.75:
        return "numeric"
    unique_count = len({_preview_cell(value).strip() for value in non_empty})
    if len(non_empty) >= 4 and unique_count <= max(2, len(non_empty) // 3):
        return "categorical"
    unit_like = sum(
        1
        for value in non_empty
        if re.fullmatch(r"\[?[%A-Za-zµμ°./^·\-0-9]+\]?", _preview_cell(value))
    )
    if unit_like == len(non_empty) and len(non_empty) <= 4:
        return "unit"
    return "text"


def _suggest_preview_role(
    column_name: str, column_index: int, inferred_type: str
) -> str:
    token = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", column_name.casefold())
    if inferred_type == "ignore":
        return "ignore"
    if any(
        item in token
        for item in ("sample", "specimen", "legend", "group", "样品", "组别")
    ):
        return "sample"
    if any(item in token for item in ("unit", "单位")):
        return "unit"
    x_tokens = (
        "time",
        "temperature",
        "frequency",
        "strain",
        "wavenumber",
        "2theta",
        "时间",
        "温度",
    )
    if any(item in token for item in x_tokens):
        return "x"
    if inferred_type == "numeric" and column_index == 0:
        return "x"
    if inferred_type == "numeric":
        return "y"
    if inferred_type == "categorical":
        return "series"
    return "metadata"


def preview_table_payload(
    *,
    name: str,
    content: bytes | None = None,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    if content is None:
        if source_path is None:
            raise ValueError("Preview requires `source_path` or `content_base64`.")
        path = Path(source_path).expanduser()
        content = path.read_bytes()
        name = name or path.name
    frame, sheet, encoding = _preview_read_frame(name, content)
    header_row = _preview_header_row(frame)
    columns: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    start_row = (header_row + 1) if header_row is not None else 0
    for column_index in range(frame.shape[1]):
        header = (
            _preview_cell(frame.iat[header_row, column_index]).strip()
            if header_row is not None
            else ""
        )
        values = frame.iloc[start_row:, column_index].tolist()
        inferred_type = _infer_preview_type(values)
        name_value = header or f"Column {column_index + 1}"
        columns.append(
            {
                "index": column_index,
                "name": name_value,
                "inferred_type": inferred_type,
                "suggested_role": _suggest_preview_role(
                    name_value, column_index, inferred_type
                ),
                "non_empty": sum(1 for value in values if _preview_cell(value).strip()),
                "numeric": sum(1 for value in values if _preview_is_number(value)),
            }
        )
    for row_index, row in frame.head(_PREVIEW_DISPLAY_ROWS).iterrows():
        rows.append(
            {
                "index": int(row_index) + 1,
                "values": [_preview_cell(value) for value in row.tolist()],
            }
        )
    return {
        "kind": "sciplot_table_preview",
        "name": name,
        "sheet": sheet,
        "encoding": encoding,
        "header_row": (header_row + 1) if header_row is not None else None,
        "preview_rows": len(rows),
        "preview_columns": len(columns),
        "columns": columns,
        "rows": rows,
    }
