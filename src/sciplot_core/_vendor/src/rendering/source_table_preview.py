from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.rendering.data_transforms import apply_data_transforms_to_frame
from src.rendering.dataset_models import CandidateRoles, ColumnProfile

try:
    from charset_normalizer import from_bytes as detect_charset
except Exception:  # pragma: no cover - optional dependency fallback
    detect_charset = None


SUPPORTED_SOURCE_EXTENSIONS = {".csv", ".txt", ".tsv", ".xls", ".xlsx", ".xlsm"}
TEXT_SOURCE_EXTENSIONS = {".csv", ".txt", ".tsv"}
EXCEL_SOURCE_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
FALLBACK_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "gbk",
    "gb2312",
    "latin-1",
)
DELIMITER_CANDIDATES = ("\t", ",", ";", "|")

X_HINTS = (
    "time",
    "test time",
    "average time",
    "temperature",
    "angular frequency",
    "frequency",
    "strain",
    "shear strain",
    "拉伸应变",
    "时间",
    "温度",
    "频率",
)
Y_HINTS = (
    "storage modulus",
    "loss modulus",
    "relaxation modulus",
    "creep compliance",
    "complex viscosity",
    "complex shear modulus",
    "stress",
    "shear stress",
    "force",
    "load",
    "modulus",
    "拉伸应力",
    "力",
    "模量",
)
METRIC_HINTS = (
    "strength",
    "elongation",
    "break",
    "maximum",
    "slope",
    "viscosity",
    "compliance",
    "断裂",
    "最大值",
    "伸长",
)
GROUP_HINTS = ("group", "sample", "specimen", "test", "status", "样品", "试样", "组")
Z_HINTS = (
    "intensity",
    "signal",
    "height",
    "amplitude",
    "response",
    "强度",
    "信号",
)


@dataclass(frozen=True)
class SourceTableSegment:
    id: str
    sheet_name: str
    label: str
    result_label: str | None
    interval_index: int | None
    start_row: int
    end_row: int
    header_row_index: int | None
    unit_row_index: int | None
    data_start_row_index: int | None
    column_count: int
    row_count: int


@dataclass(frozen=True)
class SourceTablePreview:
    input_path: Path
    sheet: str | int
    offset: int
    limit: int
    total_rows: int
    total_cols: int
    column_headers: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    candidate_roles: CandidateRoles
    detected_x_label: str | None
    detected_y_label: str | None
    column_profiles: tuple[ColumnProfile, ...]
    segments: tuple[SourceTableSegment, ...]
    selected_segment_id: str | None
    encoding: str | None
    delimiter: str | None
    diagnostics: tuple[dict[str, Any], ...] = ()


def _diagnostic(status_code: str, message: str, *, severity: str = "info", **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status_code": status_code,
        "severity": severity,
        "message": message,
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload


def sniff_text_encoding(raw_bytes: bytes) -> str | None:
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
        return "utf-16"
    if detect_charset is not None:
        match = detect_charset(raw_bytes).best()
        if match is not None and match.encoding:
            return match.encoding
    for encoding in FALLBACK_ENCODINGS:
        try:
            raw_bytes.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return None


def sniff_text_encoding_with_diagnostics(
    raw_bytes: bytes,
    *,
    requested_encoding: str | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    if requested_encoding:
        return requested_encoding, [
            _diagnostic(
                "encoding_selected",
                f"Using requested text encoding {requested_encoding}.",
                encoding=requested_encoding,
                confidence=1.0,
            )
        ]
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", [
            _diagnostic("encoding_detected", "Detected UTF-8 byte order mark.", encoding="utf-8-sig", confidence=1.0)
        ]
    if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
        return "utf-16", [
            _diagnostic("encoding_detected", "Detected UTF-16 byte order mark.", encoding="utf-16", confidence=1.0)
        ]
    if detect_charset is not None:
        match = detect_charset(raw_bytes).best()
        if match is not None and match.encoding:
            coherence = getattr(match, "percent_coherence", None)
            chaos = getattr(match, "percent_chaos", None)
            confidence = None
            if isinstance(coherence, (int, float)):
                confidence = max(0.0, min(1.0, float(coherence) / 100.0))
            elif isinstance(chaos, (int, float)):
                confidence = max(0.0, min(1.0, 1.0 - (float(chaos) / 100.0)))
            return match.encoding, [
                _diagnostic(
                    "encoding_detected",
                    f"Detected text encoding {match.encoding}.",
                    encoding=match.encoding,
                    confidence=confidence,
                )
            ]
    for fallback in FALLBACK_ENCODINGS:
        try:
            raw_bytes.decode(fallback)
            return fallback, [
                _diagnostic(
                    "encoding_detected",
                    f"Decoded with fallback text encoding {fallback}.",
                    encoding=fallback,
                    confidence=0.5,
                )
            ]
        except UnicodeDecodeError:
            continue
    return None, [
        _diagnostic(
            "encoding_detection_failed",
            "Could not decode the source with common experiment encodings.",
            severity="error",
        )
    ]


def delimiter_candidates(text: str, suffix: str) -> list[dict[str, Any]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if suffix == ".tsv":
        return [{"delimiter": "\t", "score": 1.0, "confidence": 1.0, "label": "Tab"}]
    candidates: list[dict[str, Any]] = []
    for delimiter in DELIMITER_CANDIDATES:
        widths = [len(line.split(delimiter)) for line in lines]
        useful_widths = [width for width in widths if width > 1]
        if not useful_widths:
            continue
        max_width = max(useful_widths)
        wide_rows = sum(1 for width in useful_widths if width == max_width)
        consistency = wide_rows / max(len(useful_widths), 1)
        score = (max_width - 1) * 2.0 + wide_rows * 0.35 + consistency
        if delimiter == "," and suffix == ".csv":
            score += 0.25
        candidates.append(
            {
                "delimiter": delimiter,
                "score": round(score, 4),
                "confidence": round(consistency, 4),
                "max_width": max_width,
                "consistent_rows": wide_rows,
                "label": "Tab" if delimiter == "\t" else delimiter,
            }
        )
    return sorted(candidates, key=lambda item: float(item["score"]), reverse=True)


def sniff_delimiter(text: str, suffix: str) -> str | None:
    if suffix == ".tsv":
        return "\t"
    candidates = delimiter_candidates(text, suffix)
    if candidates:
        return str(candidates[0]["delimiter"])
    lines = [line for line in text.splitlines() if line.strip()]
    sample = "\n".join(lines[:12])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return "," if suffix == ".csv" else None


def read_source_sheets_with_diagnostics(
    path: str | Path,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> tuple[list[tuple[str, pd.DataFrame]], str | None, str | None, tuple[dict[str, Any], ...]]:
    source_path = Path(path).expanduser()
    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_SOURCE_EXTENSIONS:
        raise ValueError(f"Unsupported source table type: {suffix}")
    if suffix in EXCEL_SOURCE_EXTENSIONS:
        with pd.ExcelFile(source_path) as workbook:
            sheets = [
                (str(sheet_name), pd.read_excel(workbook, sheet_name=sheet_name, header=None).fillna(""))
                for sheet_name in workbook.sheet_names
            ]
        diagnostics = [
            _diagnostic(
                "excel_sheets_detected",
                f"Detected {len(sheets)} Excel sheet(s).",
                sheet_names=[sheet_name for sheet_name, _frame in sheets],
            )
        ]
        return sheets, None, None, tuple(diagnostics)
    raw_bytes = source_path.read_bytes()
    resolved_encoding, diagnostics = sniff_text_encoding_with_diagnostics(raw_bytes, requested_encoding=encoding)
    if resolved_encoding is None:
        raise ValueError(f"Could not decode {source_path.name} with common experiment encodings.")
    text = raw_bytes.decode(resolved_encoding, errors="replace")
    candidates = delimiter_candidates(text, suffix)
    resolved_delimiter = delimiter if delimiter is not None and delimiter != "" else (
        str(candidates[0]["delimiter"]) if candidates else sniff_delimiter(text, suffix)
    )
    if resolved_delimiter is None:
        resolved_delimiter = ","
    delimiter_label = "Tab" if resolved_delimiter == "\t" else resolved_delimiter
    diagnostics.append(
        _diagnostic(
            "delimiter_selected" if delimiter else "delimiter_detected",
            f"Using {'requested' if delimiter else 'detected'} delimiter {delimiter_label!r}.",
            delimiter=resolved_delimiter,
            candidates=candidates[:4],
            confidence=(candidates[0].get("confidence") if candidates and not delimiter else 1.0),
        )
    )
    reader = csv.reader(text.splitlines(), delimiter=resolved_delimiter)
    rows = list(reader)
    widths = [len(row) for row in rows]
    non_empty_widths = [
        width
        for row, width in zip(rows, widths, strict=False)
        if any(str(value).strip() for value in row)
    ]
    if non_empty_widths and len(set(non_empty_widths)) > 1:
        most_common_width = max(set(non_empty_widths), key=non_empty_widths.count)
        ragged_rows = [
            index
            for index, width in enumerate(widths)
            if width not in {0, most_common_width} and any(str(value).strip() for value in rows[index])
        ]
        diagnostics.append(
            _diagnostic(
                "ragged_rows_detected",
                "Detected rows with fewer or more columns than the dominant table width.",
                severity="warning",
                row_numbers=ragged_rows[:20],
                expected_columns=most_common_width,
                affected_row_count=len(ragged_rows),
            )
        )
    width = max((len(row) for row in rows), default=0)
    padded = [row + [""] * (width - len(row)) for row in rows]
    return [("Sheet1", pd.DataFrame(padded).fillna(""))], resolved_encoding, resolved_delimiter, tuple(diagnostics)


def read_source_sheets(
    path: str | Path,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> tuple[list[tuple[str, pd.DataFrame]], str | None, str | None]:
    sheets, resolved_encoding, resolved_delimiter, _diagnostics = read_source_sheets_with_diagnostics(
        path,
        encoding=encoding,
        delimiter=delimiter,
    )
    return sheets, resolved_encoding, resolved_delimiter


def source_sheet_names(path: str | Path) -> list[str]:
    source_path = Path(path).expanduser()
    if source_path.suffix.lower() in EXCEL_SOURCE_EXTENSIONS:
        with pd.ExcelFile(source_path) as workbook:
            return [str(sheet_name) for sheet_name in workbook.sheet_names]
    return ["Sheet1"]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip().strip('"')


def _has_content(value: object) -> bool:
    return _cell_text(value) != ""


def _looks_numeric(value: object) -> bool:
    try:
        float(_cell_text(value))
    except ValueError:
        return False
    return True


def _row_texts(frame: pd.DataFrame, row_index: int) -> list[str]:
    return [_cell_text(value) for value in frame.iloc[row_index].tolist()]


def _row_has_numeric_data(frame: pd.DataFrame, row_index: int) -> bool:
    return sum(1 for value in frame.iloc[row_index].tolist() if _looks_numeric(value)) >= 2


def _segment_label(result_label: str | None, interval_index: int | None) -> str:
    parts = []
    if result_label:
        parts.append(result_label)
    if interval_index is not None:
        parts.append(f"Interval {interval_index}")
    return " / ".join(parts) or "Segment"


def detect_source_segments(sheet_name: str, frame: pd.DataFrame) -> tuple[SourceTableSegment, ...]:
    result_label: str | None = None
    pending_interval: int | None = None
    header_rows: list[tuple[int, str | None, int | None]] = []
    for row_index in range(frame.shape[0]):
        first = _cell_text(frame.iloc[row_index, 0]) if frame.shape[1] > 0 else ""
        row = _row_texts(frame, row_index)
        if first.lower().startswith("result:"):
            result_label = next((value for value in row[1:] if value), None)
            continue
        if first.lower().startswith("interval and data points"):
            interval_text = row[1] if len(row) > 1 else ""
            try:
                pending_interval = int(float(interval_text))
            except ValueError:
                pending_interval = None
            continue
        if first.lower().startswith("interval data"):
            header_rows.append((row_index, result_label, pending_interval))

    segments: list[SourceTableSegment] = []
    for index, (header_row, current_result, current_interval) in enumerate(header_rows):
        next_header = header_rows[index + 1][0] if index + 1 < len(header_rows) else frame.shape[0]
        end_row = max(header_row, next_header - 1)
        unit_row = None
        for candidate_row in range(header_row + 1, min(header_row + 4, frame.shape[0])):
            row = _row_texts(frame, candidate_row)
            non_empty = [value for value in row if value]
            if non_empty and any(value.startswith("[") or value.startswith("(") for value in non_empty):
                unit_row = candidate_row
                break
        data_start = None
        search_start = (unit_row + 1) if unit_row is not None else header_row + 1
        for candidate_row in range(search_start, min(end_row + 1, frame.shape[0])):
            if _row_has_numeric_data(frame, candidate_row):
                data_start = candidate_row
                break
        active_cols = [
            col_index
            for col_index in range(frame.shape[1])
            if any(_has_content(frame.iloc[row_index, col_index]) for row_index in range(header_row, end_row + 1))
        ]
        if not active_cols:
            continue
        start_col = min(active_cols)
        end_col = max(active_cols)
        column_count = end_col - start_col + 1
        segment_id = f"{sheet_name}::segment{len(segments) + 1}"
        segments.append(
            SourceTableSegment(
                id=segment_id,
                sheet_name=sheet_name,
                label=_segment_label(current_result, current_interval),
                result_label=current_result,
                interval_index=current_interval,
                start_row=header_row,
                end_row=end_row,
                header_row_index=header_row,
                unit_row_index=unit_row,
                data_start_row_index=data_start,
                column_count=column_count,
                row_count=end_row - header_row + 1,
            )
        )
    return tuple(segments)


def _coerce_sheet(sheet: str | int) -> str | int:
    if isinstance(sheet, int):
        return sheet
    stripped = str(sheet).strip()
    if stripped.isdigit():
        return int(stripped)
    return stripped or "0"


def _select_sheet(sheets: list[tuple[str, pd.DataFrame]], sheet: str | int) -> tuple[str, pd.DataFrame]:
    if isinstance(sheet, int):
        try:
            return sheets[sheet]
        except IndexError as exc:
            raise ValueError(f"Sheet index {sheet} is out of range.") from exc
    for sheet_name, frame in sheets:
        if sheet_name == sheet:
            return sheet_name, frame
    if sheet == "0" and sheets:
        return sheets[0]
    raise ValueError(f"Sheet {sheet!r} was not found.")


def _headers_for(frame: pd.DataFrame, *, header_row_index: int | None) -> tuple[str, ...]:
    if header_row_index is None or header_row_index < 0 or header_row_index >= frame.shape[0]:
        return tuple(f"Column {index + 1}" for index in range(frame.shape[1]))
    headers: list[str] = []
    for index, value in enumerate(frame.iloc[header_row_index].tolist()):
        text = _cell_text(value)
        if index == 0 and text.lower().startswith("interval data"):
            text = ""
        headers.append(text or f"Column {index + 1}")
    return tuple(headers)


def _header_diagnostics(headers: tuple[str, ...]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    duplicates: set[str] = set()
    empty_count = 0
    for header in headers:
        stripped = header.strip()
        if not stripped:
            empty_count += 1
            continue
        lowered = stripped.lower()
        seen[lowered] = seen.get(lowered, 0) + 1
        if seen[lowered] > 1:
            duplicates.add(stripped)
    if duplicates:
        diagnostics.append(
            _diagnostic(
                "duplicate_headers_detected",
                "Detected duplicate column headers; stable column ids will be used for bindings.",
                severity="warning",
                duplicate_headers=sorted(duplicates),
            )
        )
    if empty_count:
        diagnostics.append(
            _diagnostic(
                "empty_headers_detected",
                "Detected empty column headers; fallback Column N labels were generated.",
                severity="warning",
                empty_header_count=empty_count,
            )
        )
    return diagnostics


def _structure_diagnostics(
    *,
    header_row_index: int | None,
    unit_row_index: int | None,
    data_start_row_index: int | None,
    segments: tuple[SourceTableSegment, ...],
) -> list[dict[str, Any]]:
    return [
        _diagnostic(
            "structure_rows_detected",
            "Detected source table header, unit, and data start rows.",
            header_row_index=header_row_index,
            unit_row_index=unit_row_index,
            data_start_row_index=data_start_row_index,
            segment_count=len(segments),
        )
    ]


def _looks_like_unit_row(values: list[str]) -> bool:
    non_empty = [value for value in values if value]
    if not non_empty:
        return False
    unit_like = sum(1 for value in non_empty if value.startswith("[") or value.startswith("(") or len(value) <= 8)
    return unit_like >= max(1, len(non_empty) // 2)


def _default_structure_rows(frame: pd.DataFrame) -> tuple[int | None, int | None, int | None]:
    if frame.empty:
        return None, None, None
    header = 0
    unit = None
    data_start = 1
    if frame.shape[0] > 1 and _looks_like_unit_row(_row_texts(frame, 1)):
        unit = 1
        data_start = 2
    if frame.shape[0] > 3 and _row_has_numeric_data(frame, 3):
        row_2 = _row_texts(frame, 2)
        if row_2 and sum(1 for value in row_2 if value and not _looks_numeric(value)) >= 1:
            data_start = 3
    return header, unit, data_start


def _unit_for(frame: pd.DataFrame, *, unit_row_index: int | None, column_index: int) -> str:
    if unit_row_index is None or unit_row_index < 0 or unit_row_index >= frame.shape[0]:
        return ""
    if column_index >= frame.shape[1]:
        return ""
    unit = _cell_text(frame.iloc[unit_row_index, column_index])
    return unit.strip("[]()")


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in hints)


def _numeric_stats(values: Iterable[object]) -> tuple[str, int, int, float | None, float | None]:
    texts = [_cell_text(value) for value in values]
    non_empty = [value for value in texts if value]
    numeric_values: list[float] = []
    for value in non_empty:
        try:
            numeric_values.append(float(value))
        except ValueError:
            continue
    if non_empty and len(numeric_values) / len(non_empty) >= 0.8:
        inferred = "numeric"
    elif non_empty:
        inferred = "text"
    else:
        inferred = "empty"
    return (
        inferred,
        len(non_empty),
        len(texts) - len(non_empty),
        min(numeric_values) if numeric_values else None,
        max(numeric_values) if numeric_values else None,
    )


def _column_profiles(
    frame: pd.DataFrame,
    *,
    headers: tuple[str, ...],
    unit_row_index: int | None,
    data_start_row_index: int,
) -> tuple[ColumnProfile, ...]:
    profiles: list[ColumnProfile] = []
    for column_index in range(frame.shape[1]):
        values = frame.iloc[data_start_row_index:, column_index].tolist()
        inferred, non_empty, missing, min_value, max_value = _numeric_stats(values)
        unit = _unit_for(frame, unit_row_index=unit_row_index, column_index=column_index)
        header_preview = tuple(value or None for value in (headers[column_index], unit))
        profiles.append(
            ColumnProfile(
                name=headers[column_index],
                header_preview=header_preview,
                inferred_type=inferred,
                non_empty_count=non_empty,
                missing_count=missing,
                min_value=min_value,
                max_value=max_value,
            )
        )
    return tuple(profiles)


def _role_label_from_xyz_header(
    frame: pd.DataFrame,
    *,
    local_header: int | None,
    local_data_start: int,
    column_index: int,
    fallback: str,
) -> str:
    if local_header is None or local_header < 0 or local_header >= frame.shape[0]:
        return fallback
    header_value = _cell_text(frame.iloc[local_header, column_index]).lower()
    if header_value not in {"x", "y", "z"}:
        return fallback
    label_row = local_header + 1
    if label_row < local_data_start and label_row < frame.shape[0]:
        label = _cell_text(frame.iloc[label_row, column_index])
        if label and label.lower() not in {"x", "y", "z"}:
            return label
    return fallback


def _candidate_roles(
    frame: pd.DataFrame,
    *,
    headers: tuple[str, ...],
    profiles: tuple[ColumnProfile, ...],
    local_header: int | None,
    local_data_start: int,
) -> CandidateRoles:
    x: list[str] = []
    y: list[str] = []
    z: list[str] = []
    group: list[str] = []
    metric: list[str] = []
    for column_index, (header, profile) in enumerate(zip(headers, profiles, strict=False)):
        hint_text = " ".join(str(item or "") for item in (header, *profile.header_preview))
        display_header = _role_label_from_xyz_header(
            frame,
            local_header=local_header,
            local_data_start=local_data_start,
            column_index=column_index,
            fallback=header,
        )
        header_token = header.strip().lower()
        if profile.inferred_type == "numeric" and header_token == "x":
            x.append(display_header)
            continue
        if profile.inferred_type == "numeric" and header_token == "y":
            y.append(display_header)
            continue
        if profile.inferred_type == "numeric" and header_token == "z":
            z.append(display_header)
            continue
        if profile.inferred_type == "numeric" and _contains_hint(hint_text, X_HINTS):
            x.append(display_header)
        if profile.inferred_type == "numeric" and _contains_hint(hint_text, Y_HINTS):
            y.append(display_header)
        if profile.inferred_type == "numeric" and _contains_hint(hint_text, Z_HINTS):
            z.append(display_header)
        if profile.inferred_type == "numeric" and _contains_hint(hint_text, METRIC_HINTS):
            metric.append(display_header)
        if _contains_hint(hint_text, GROUP_HINTS):
            group.append(display_header)
    if not x:
        numeric_headers = [profile.name for profile in profiles if profile.inferred_type == "numeric"]
        if numeric_headers:
            x.append(numeric_headers[0])
    if not y:
        numeric_headers = [profile.name for profile in profiles if profile.inferred_type == "numeric"]
        y.extend(header for header in numeric_headers[1:3] if header not in x)
    return CandidateRoles(
        x=tuple(dict.fromkeys(x)),
        y=tuple(dict.fromkeys(y)),
        z=tuple(dict.fromkeys(z)),
        group=tuple(dict.fromkeys(group)),
        metric=tuple(dict.fromkeys(metric)),
        value=tuple(dict.fromkeys(metric or y)),
        label=tuple(dict.fromkeys(group)),
        series=tuple(dict.fromkeys(group)),
    )


def source_table_preview(
    path: str | Path,
    *,
    sheet: str | int = 0,
    offset: int = 0,
    limit: int = 50,
    encoding: str | None = None,
    delimiter: str | None = None,
    segment_id: str | None = None,
    header_row_index: int | None = None,
    unit_row_index: int | None = None,
    data_start_row_index: int | None = None,
    data_transforms: object = None,
    data_variables: object = None,
) -> SourceTablePreview:
    source_path = Path(path).expanduser()
    sheets, resolved_encoding, resolved_delimiter, read_diagnostics = read_source_sheets_with_diagnostics(
        source_path,
        encoding=encoding,
        delimiter=delimiter,
    )
    resolved_sheet = _coerce_sheet(sheet)
    sheet_name, frame = _select_sheet(sheets, resolved_sheet)
    if data_transforms is not None:
        frame = apply_data_transforms_to_frame(frame, data_transforms, variables=data_variables)
    segments = detect_source_segments(sheet_name, frame)
    selected_segment = next((segment for segment in segments if segment.id == segment_id), None)
    if segment_id and selected_segment is None:
        raise ValueError(f"Unknown source table segment: {segment_id}")

    effective_header = header_row_index
    effective_unit = unit_row_index
    effective_data_start = data_start_row_index
    start_row = 0
    end_row = frame.shape[0] - 1
    if selected_segment is not None:
        start_row = selected_segment.start_row
        end_row = selected_segment.end_row
        effective_header = effective_header if effective_header is not None else selected_segment.header_row_index
        effective_unit = effective_unit if effective_unit is not None else selected_segment.unit_row_index
        effective_data_start = (
            effective_data_start if effective_data_start is not None else selected_segment.data_start_row_index
        )
    view = frame.iloc[start_row : end_row + 1].reset_index(drop=True)
    if effective_header is None or effective_data_start is None:
        default_header, default_unit, default_data_start = _default_structure_rows(view)
        if effective_header is None:
            effective_header = start_row + default_header if default_header is not None else 0
        if effective_unit is None and default_unit is not None:
            effective_unit = start_row + default_unit
        if effective_data_start is None:
            effective_data_start = start_row + (default_data_start if default_data_start is not None else 1)
    local_header = effective_header - start_row if effective_header is not None else None
    local_unit = effective_unit - start_row if effective_unit is not None else None
    local_data_start = max(0, effective_data_start - start_row)
    headers = _headers_for(view, header_row_index=local_header)
    diagnostics = [
        *read_diagnostics,
        *_structure_diagnostics(
            header_row_index=effective_header,
            unit_row_index=effective_unit,
            data_start_row_index=effective_data_start,
            segments=segments,
        ),
        *_header_diagnostics(headers),
    ]
    profiles = _column_profiles(
        view,
        headers=headers,
        unit_row_index=local_unit,
        data_start_row_index=min(local_data_start, view.shape[0]),
    )
    roles = _candidate_roles(
        view,
        headers=headers,
        profiles=profiles,
        local_header=local_header,
        local_data_start=local_data_start,
    )
    bounded_offset = max(0, offset)
    bounded_limit = max(1, min(limit, 200))
    page = view.iloc[bounded_offset : bounded_offset + bounded_limit]
    return SourceTablePreview(
        input_path=source_path,
        sheet=sheet_name,
        offset=bounded_offset,
        limit=bounded_limit,
        total_rows=int(view.shape[0]),
        total_cols=int(view.shape[1]),
        column_headers=headers,
        rows=tuple(tuple(value for value in row) for row in page.itertuples(index=False)),
        candidate_roles=roles,
        detected_x_label=roles.x[0] if roles.x else None,
        detected_y_label=roles.y[0] if roles.y else None,
        column_profiles=profiles,
        segments=segments,
        selected_segment_id=selected_segment.id if selected_segment is not None else None,
        encoding=resolved_encoding,
        delimiter=resolved_delimiter,
        diagnostics=tuple(diagnostics),
    )
