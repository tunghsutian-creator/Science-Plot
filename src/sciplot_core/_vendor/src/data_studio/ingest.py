from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src.data_studio.models import (
    BindingSuggestion,
    DataStudioRange,
    FieldCandidate,
    PreviewRange,
    RawFilePreview,
    RawSheetPreview,
    SheetBlock,
    TemplateDefinition,
    TemplateMatch,
)
from src.data_studio.template_store import list_templates
from src.rendering.source_table_preview import read_source_sheets as shared_read_source_sheets

try:
    from charset_normalizer import from_bytes as detect_charset
except Exception:  # pragma: no cover - optional import fallback
    detect_charset = None


TEXT_EXTENSIONS = {".csv", ".txt", ".tsv"}
EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | EXCEL_EXTENSIONS
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
UNIT_TOKENS = {
    "%",
    "mpa",
    "gpa",
    "pa",
    "kpa",
    "s",
    "sec",
    "min",
    "h",
    "n",
    "kn",
    "mm",
    "um",
    "cm",
    "c",
    "°c",
    "k",
}
CURVE_X_HINTS = (
    "strain",
    "应变",
    "time",
    "时间",
    "temperature",
    "温度",
    "frequency",
    "频率",
    "wavenumber",
    "波数",
    "chemical shift",
    "ppm",
    "位移",
)
CURVE_Y_HINTS = (
    "stress",
    "应力",
    "force",
    "力",
    "load",
    "modulus",
    "模量",
    "intensity",
    "signal",
    "强度",
)
METRIC_HINTS = (
    "strength",
    "断裂强度",
    "强度",
    "modulus",
    "模量",
    "elongation",
    "伸长",
    "break",
)
METADATA_HINTS = (
    "sample",
    "样品",
    "name",
    "batch",
    "group",
    "组",
    "specimen",
    "试样",
    "id",
    "编号",
)


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _has_content(value: object) -> bool:
    return _cell_text(value) != ""


def _normalize_token(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in text).strip()


def _token_set(text: str) -> set[str]:
    return {token for token in _normalize_token(text).split() if token}


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in hints)


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


def sniff_delimiter(text: str, suffix: str) -> str | None:
    if suffix == ".tsv":
        return "\t"
    sample = "\n".join(text.splitlines()[:12])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return "," if suffix == ".csv" else None


def _read_text_frame(path: Path) -> tuple[pd.DataFrame, str | None, str | None]:
    raw_bytes = path.read_bytes()
    encoding = sniff_text_encoding(raw_bytes)
    if encoding is None:
        raise ValueError(f"Could not decode {path.name} with the common experiment encodings.")
    text = raw_bytes.decode(encoding, errors="replace")
    delimiter = sniff_delimiter(text, path.suffix.lower())
    lines = text.splitlines()
    if delimiter is None:
        sample = "\n".join(lines[:12])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            reader = csv.reader(lines, dialect=dialect)
            delimiter = dialect.delimiter
        except csv.Error:
            reader = csv.reader(lines)
            delimiter = ","
    else:
        reader = csv.reader(lines, delimiter=delimiter)
    rows = list(reader)
    width = max((len(row) for row in rows), default=0)
    padded_rows = [row + [""] * (width - len(row)) for row in rows]
    frame = pd.DataFrame(padded_rows)
    return frame.fillna(""), encoding, delimiter


def _read_excel_sheets(path: Path) -> tuple[list[tuple[str, pd.DataFrame]], None, None]:
    with pd.ExcelFile(path) as workbook:
        sheets = [
            (str(sheet_name), pd.read_excel(workbook, sheet_name=sheet_name, header=None).fillna(""))
            for sheet_name in workbook.sheet_names
        ]
    return sheets, None, None


def read_preview_source(path: str | Path) -> tuple[list[tuple[str, pd.DataFrame]], str | None, str | None]:
    source_path = Path(path).expanduser()
    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported Data Studio input type: {suffix}")
    return shared_read_source_sheets(source_path)


def _contiguous_runs(indices: Iterable[int]) -> list[tuple[int, int]]:
    sorted_indices = sorted(set(indices))
    if not sorted_indices:
        return []
    runs: list[tuple[int, int]] = []
    start = sorted_indices[0]
    end = start
    for index in sorted_indices[1:]:
        if index == end + 1:
            end = index
            continue
        runs.append((start, end))
        start = index
        end = index
    runs.append((start, end))
    return runs


def detect_sheet_blocks(sheet_name: str, frame: pd.DataFrame) -> tuple[SheetBlock, ...]:
    non_empty_rows = [
        row_index
        for row_index in range(frame.shape[0])
        if any(_has_content(value) for value in frame.iloc[row_index].tolist())
    ]
    blocks: list[SheetBlock] = []
    for block_index, (row_start, row_end) in enumerate(_contiguous_runs(non_empty_rows), start=1):
        slice_frame = frame.iloc[row_start : row_end + 1].reset_index(drop=True)
        active_cols = [
            col_index
            for col_index in range(slice_frame.shape[1])
            if any(_has_content(value) for value in slice_frame.iloc[:, col_index].tolist())
        ]
        for col_run_index, (col_start, col_end) in enumerate(_contiguous_runs(active_cols), start=1):
            block_frame = slice_frame.iloc[:, col_start : col_end + 1].reset_index(drop=True)
            header_row_index = detect_header_row(block_frame)
            unit_row_index = detect_unit_row(block_frame, header_row_index)
            data_start = detect_data_start_row(block_frame, header_row_index, unit_row_index)
            sample_rows = tuple(tuple(value for value in row) for row in block_frame.head(24).itertuples(index=False))
            blocks.append(
                SheetBlock(
                    id=f"{sheet_name}::block{block_index}_{col_run_index}",
                    sheet_name=sheet_name,
                    label=f"{sheet_name} block {block_index}.{col_run_index}",
                    row_count=block_frame.shape[0],
                    col_count=block_frame.shape[1],
                    range=DataStudioRange(
                        sheet_name=sheet_name,
                        start_row=row_start,
                        end_row=row_end,
                        start_col=col_start,
                        end_col=col_end,
                    ),
                    header_row_index=header_row_index,
                    unit_row_index=unit_row_index,
                    data_start_row_index=data_start,
                    sample_rows=sample_rows,
                )
            )
    return tuple(blocks)


def detect_header_row(frame: pd.DataFrame) -> int | None:
    candidates: list[tuple[float, int]] = []
    for row_index in range(min(frame.shape[0], 6)):
        row = [_cell_text(value) for value in frame.iloc[row_index].tolist()]
        if not any(row):
            continue
        non_empty_count = sum(1 for value in row if value)
        text_count = sum(1 for value in row if value and not _looks_numeric(value))
        numeric_count = sum(1 for value in row if _looks_numeric(value))
        unit_like_count = sum(
            1
            for value in row
            if value.lower() in UNIT_TOKENS or value.startswith("(") or value.endswith(")")
        )
        score = text_count - numeric_count * 0.5 - unit_like_count * 0.85
        if non_empty_count >= 2:
            score += 0.25
        if non_empty_count == 1:
            score -= 1.0
        if score > 0:
            candidates.append((score, row_index))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def detect_unit_row(frame: pd.DataFrame, header_row_index: int | None) -> int | None:
    if header_row_index is None:
        return None
    next_index = header_row_index + 1
    if next_index >= frame.shape[0]:
        return None
    row = [_cell_text(value).lower() for value in frame.iloc[next_index].tolist()]
    unit_like = sum(1 for value in row if value in UNIT_TOKENS or value.startswith("(") or value.endswith(")"))
    return next_index if unit_like > 0 else None


def detect_data_start_row(
    frame: pd.DataFrame,
    header_row_index: int | None,
    unit_row_index: int | None,
) -> int | None:
    start = 0
    if unit_row_index is not None:
        start = unit_row_index + 1
    elif header_row_index is not None:
        start = header_row_index + 1
    for row_index in range(start, frame.shape[0]):
        numeric_count = sum(1 for value in frame.iloc[row_index].tolist() if _looks_numeric(_cell_text(value)))
        if numeric_count >= 2:
            return row_index
    return None


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _coerce_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _block_frame(frame: pd.DataFrame, block: SheetBlock) -> pd.DataFrame:
    return frame.iloc[
        block.range.start_row : block.range.end_row + 1,
        block.range.start_col : block.range.end_col + 1,
    ].reset_index(drop=True)


def _data_texts_for_column(block_frame: pd.DataFrame, block: SheetBlock, local_index: int) -> list[str]:
    start_row = block.data_start_row_index or 0
    return [
        text
        for value in block_frame.iloc[start_row:, local_index].tolist()
        if (text := _cell_text(value))
    ]


def _numeric_profile(values: list[str]) -> tuple[list[float], float, float, float]:
    numeric_values = [parsed for value in values if (parsed := _coerce_float(value)) is not None]
    numeric_ratio = len(numeric_values) / max(len(values), 1)
    unique_ratio = len(set(values)) / max(len(values), 1)
    monotonic_score = _monotonic_score(numeric_values)
    return numeric_values, numeric_ratio, unique_ratio, monotonic_score


def _monotonic_score(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    diffs = [right - left for left, right in zip(values, values[1:], strict=False) if right != left]
    if not diffs:
        return 0.0
    non_negative = sum(1 for value in diffs if value >= 0) / len(diffs)
    non_positive = sum(1 for value in diffs if value <= 0) / len(diffs)
    return max(non_negative, non_positive)


def _column_range(sheet_name: str, block: SheetBlock, local_index: int) -> DataStudioRange:
    return DataStudioRange(
        sheet_name=sheet_name,
        start_row=block.range.start_row,
        end_row=block.range.end_row,
        start_col=block.range.start_col + local_index,
        end_col=block.range.start_col + local_index,
    )


def _best_candidate_for_column(
    candidates: Iterable[FieldCandidate],
    *,
    kind: str,
    local_index: int,
    block: SheetBlock,
) -> FieldCandidate | None:
    matching: list[FieldCandidate] = []
    absolute_col = block.range.start_col + local_index
    for candidate in candidates:
        if candidate.kind != kind or candidate.range is None:
            continue
        if candidate.range.start_col == absolute_col and candidate.range.end_col == absolute_col:
            matching.append(candidate)
    if not matching:
        return None
    matching.sort(key=lambda item: (-item.confidence, item.label.lower(), item.id))
    return matching[0]


def infer_field_candidates(sheet_name: str, frame: pd.DataFrame, block: SheetBlock) -> list[FieldCandidate]:
    block_frame = _block_frame(frame, block)
    header_row = (
        [_cell_text(value) for value in block_frame.iloc[block.header_row_index].tolist()]
        if block.header_row_index is not None
        else []
    )
    unit_row = (
        [_cell_text(value) for value in block_frame.iloc[block.unit_row_index].tolist()]
        if block.unit_row_index is not None
        else []
    )
    candidates: list[FieldCandidate] = []
    emitted_ids: set[str] = set()

    def append_candidate(
        *,
        kind: str,
        local_index: int,
        label: str,
        confidence: float,
        rationale: str,
        unit_hint: str | None,
        sample_values: tuple[str, ...],
    ) -> None:
        candidate_id = f"{block.id}::{kind}_{local_index}"
        if candidate_id in emitted_ids:
            return
        emitted_ids.add(candidate_id)
        candidates.append(
            FieldCandidate(
                id=candidate_id,
                kind=kind,
                label=label,
                confidence=confidence,
                rationale=rationale,
                sheet_name=sheet_name,
                block_id=block.id,
                range=_column_range(sheet_name, block, local_index),
                sample_values=sample_values,
                unit_hint=unit_hint,
            )
        )

    for local_index in range(block_frame.shape[1]):
        header = header_row[local_index] if local_index < len(header_row) else ""
        header_display = header or f"Column {local_index + 1}"
        unit_hint = unit_row[local_index] if local_index < len(unit_row) and unit_row[local_index] else None
        data_values = _data_texts_for_column(block_frame, block, local_index)
        sample_values = tuple(data_values[:5])
        _, numeric_ratio, unique_ratio, monotonic_score = _numeric_profile(data_values)
        combined_hint_text = " ".join(part for part in [header, unit_hint or ""] if part)

        if _contains_hint(combined_hint_text, CURVE_X_HINTS):
            append_candidate(
                kind="curve_x",
                local_index=local_index,
                label=header_display,
                confidence=0.9,
                rationale="Column header and units look like an ordered X series.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )
        elif numeric_ratio >= 0.8 and monotonic_score >= 0.82 and unique_ratio >= 0.55:
            append_candidate(
                kind="curve_x",
                local_index=local_index,
                label=header_display,
                confidence=0.68,
                rationale="Column behaves like an ordered X series after the detected data start row.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )

        if _contains_hint(combined_hint_text, CURVE_Y_HINTS):
            append_candidate(
                kind="curve_y",
                local_index=local_index,
                label=header_display,
                confidence=0.9,
                rationale="Column header and units look like a response or Y field.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )
        elif numeric_ratio >= 0.8 and sample_values:
            append_candidate(
                kind="curve_y",
                local_index=local_index,
                label=header_display,
                confidence=0.62,
                rationale="Numeric column could act as the Y component of a curve pair.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )

        if _contains_hint(combined_hint_text, METRIC_HINTS):
            append_candidate(
                kind="metric",
                local_index=local_index,
                label=header_display,
                confidence=0.84,
                rationale="Column looks like a workbook metric.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )
        elif numeric_ratio >= 0.8 and monotonic_score < 0.82 and sample_values:
            append_candidate(
                kind="metric",
                local_index=local_index,
                label=header_display,
                confidence=0.54,
                rationale="Numeric column could be retained as a metric or summary field.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )

        if _contains_hint(combined_hint_text, METADATA_HINTS):
            append_candidate(
                kind="metadata",
                local_index=local_index,
                label=header_display,
                confidence=0.76,
                rationale="Column looks like metadata.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )
        elif sample_values and numeric_ratio <= 0.25:
            append_candidate(
                kind="metadata",
                local_index=local_index,
                label=header_display,
                confidence=0.56,
                rationale="Mostly text-like column could be preserved as metadata.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )

        if header:
            append_candidate(
                kind="header",
                local_index=local_index,
                label=header,
                confidence=0.55,
                rationale="Column is available for advanced template binding.",
                unit_hint=unit_hint,
                sample_values=sample_values,
            )

    if block.header_row_index is not None:
        candidates.append(
            FieldCandidate(
                id=f"{block.id}::header_row",
                kind="header_row",
                label=f"{sheet_name} header row",
                confidence=0.7,
                rationale="Likely header row for this data block.",
                sheet_name=sheet_name,
                block_id=block.id,
                range=DataStudioRange(
                    sheet_name=sheet_name,
                    start_row=block.range.start_row + block.header_row_index,
                    end_row=block.range.start_row + block.header_row_index,
                    start_col=block.range.start_col,
                    end_col=block.range.end_col,
                ),
            )
        )
    if block.unit_row_index is not None:
        candidates.append(
            FieldCandidate(
                id=f"{block.id}::unit_row",
                kind="unit_row",
                label=f"{sheet_name} unit row",
                confidence=0.64,
                rationale="Likely unit row for this data block.",
                sheet_name=sheet_name,
                block_id=block.id,
                range=DataStudioRange(
                    sheet_name=sheet_name,
                    start_row=block.range.start_row + block.unit_row_index,
                    end_row=block.range.start_row + block.unit_row_index,
                    start_col=block.range.start_col,
                    end_col=block.range.end_col,
                ),
            )
        )
    return candidates


def _candidate_sort_key(candidate: FieldCandidate) -> tuple[float, str, str]:
    return (-candidate.confidence, candidate.label.lower(), candidate.id)


def _display_label(candidate: FieldCandidate) -> str:
    if candidate.unit_hint:
        return f"{candidate.label} ({candidate.unit_hint})"
    return candidate.label


def _column_profiles(block_frame: pd.DataFrame, block: SheetBlock) -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    for local_index in range(block_frame.shape[1]):
        values = _data_texts_for_column(block_frame, block, local_index)
        _, numeric_ratio, unique_ratio, monotonic_score = _numeric_profile(values)
        profiles.append(
            {
                "local_index": local_index,
                "values": values,
                "numeric_ratio": numeric_ratio,
                "unique_ratio": unique_ratio,
                "monotonic_score": monotonic_score,
            }
        )
    return profiles


def _preview_range_for_candidate(candidate: FieldCandidate, *, role: str) -> PreviewRange | None:
    if candidate.range is None:
        return None
    return PreviewRange(
        sheet_name=candidate.sheet_name,
        block_id=candidate.block_id,
        start_row=candidate.range.start_row,
        end_row=candidate.range.end_row,
        start_col=candidate.range.start_col,
        end_col=candidate.range.end_col,
        role=role,
    )


def _build_structure_rows_suggestion(block: SheetBlock, candidates: list[FieldCandidate]) -> BindingSuggestion | None:
    structure_candidates = [
        candidate
        for candidate in candidates
        if candidate.kind in {"header_row", "unit_row"}
    ]
    if not structure_candidates:
        return None
    ordered = sorted(structure_candidates, key=_candidate_sort_key)
    preview_ranges = tuple(
        preview_range
        for candidate in ordered
        if (preview_range := _preview_range_for_candidate(
            candidate,
            role="header_row" if candidate.kind == "header_row" else "unit_row",
        )) is not None
    )
    summary_parts: list[str] = []
    if block.header_row_index is not None:
        summary_parts.append(f"Header Row {block.header_row_index + 1}")
    elif any(candidate.kind == "header_row" for candidate in ordered):
        summary_parts.append("Header Row")
    if block.unit_row_index is not None:
        summary_parts.append(f"Unit Row {block.unit_row_index + 1}")
    elif any(candidate.kind == "unit_row" for candidate in ordered):
        summary_parts.append("Unit Row")
    return BindingSuggestion(
        id=f"{block.id}::structure_rows",
        kind="structure_rows",
        title="Detected Structure",
        summary=" · ".join(summary_parts),
        sheet_name=block.sheet_name,
        block_id=block.id,
        candidate_ids=tuple(candidate.id for candidate in ordered),
        preview_ranges=preview_ranges,
        default_selected=True,
        rationale="Detected the table structure rows for this block.",
        confidence=max((candidate.confidence for candidate in ordered), default=None),
    )


def _build_curve_pair_suggestion(
    block: SheetBlock,
    block_frame: pd.DataFrame,
    candidates: list[FieldCandidate],
) -> BindingSuggestion | None:
    profiles = _column_profiles(block_frame, block)
    if len(profiles) < 2:
        return None
    candidate_pairs: list[tuple[float, FieldCandidate, FieldCandidate]] = []
    for left_profile in profiles:
        left_index = int(left_profile["local_index"])
        left_values = list(left_profile["values"])
        left_numeric_ratio = float(left_profile["numeric_ratio"])
        left_monotonic = float(left_profile["monotonic_score"])
        if left_numeric_ratio < 0.8 or len(left_values) < 3:
            continue
        x_candidate = _best_candidate_for_column(candidates, kind="curve_x", local_index=left_index, block=block)
        if x_candidate is None:
            continue
        for right_profile in profiles:
            right_index = int(right_profile["local_index"])
            if right_index <= left_index:
                continue
            right_values = list(right_profile["values"])
            right_numeric_ratio = float(right_profile["numeric_ratio"])
            if right_numeric_ratio < 0.8 or len(right_values) < 3:
                continue
            y_candidate = _best_candidate_for_column(candidates, kind="curve_y", local_index=right_index, block=block)
            if y_candidate is None:
                continue
            distance = right_index - left_index
            adjacency_bonus = 0.16 if distance == 1 else max(0.0, 0.1 - 0.03 * (distance - 1))
            same_block_bonus = 0.2
            structural_bonus = left_monotonic * 0.22
            score = (
                x_candidate.confidence
                + y_candidate.confidence
                + adjacency_bonus
                + same_block_bonus
                + structural_bonus
            )
            candidate_pairs.append((score, x_candidate, y_candidate))
    if not candidate_pairs:
        return None
    candidate_pairs.sort(key=lambda item: (-item[0], item[1].label.lower(), item[2].label.lower()))
    score, x_candidate, y_candidate = candidate_pairs[0]
    preview_ranges = tuple(
        preview_range
        for preview_range in (
            _preview_range_for_candidate(x_candidate, role="x"),
            _preview_range_for_candidate(y_candidate, role="y"),
        )
        if preview_range is not None
    )
    return BindingSuggestion(
        id=f"{block.id}::curve_pair::{x_candidate.id}::{y_candidate.id}",
        kind="curve_pair",
        title="Recommended Curve",
        summary=f"X: {_display_label(x_candidate)} · Y: {_display_label(y_candidate)}",
        sheet_name=block.sheet_name,
        block_id=block.id,
        candidate_ids=(x_candidate.id, y_candidate.id),
        preview_ranges=preview_ranges,
        default_selected=True,
        rationale="Recommended X/Y pair comes from the same numeric block with adjacent columns preferred.",
        confidence=min(0.99, score / 2.4),
    )


def _build_group_suggestion(
    *,
    block: SheetBlock,
    candidates: list[FieldCandidate],
    kind: str,
    title: str,
    role: str,
    excluded_candidate_ids: set[str] | None = None,
    default_selected: bool,
) -> BindingSuggestion | None:
    excluded_candidate_ids = excluded_candidate_ids or set()
    grouped = [
        candidate
        for candidate in sorted(candidates, key=_candidate_sort_key)
        if candidate.kind == kind and candidate.id not in excluded_candidate_ids
    ]
    if not grouped:
        return None
    selected = grouped[:3]
    preview_ranges = tuple(
        preview_range
        for candidate in selected
        if (preview_range := _preview_range_for_candidate(candidate, role=role)) is not None
    )
    return BindingSuggestion(
        id=f"{block.id}::{kind}_group",
        kind=f"{kind}_group",
        title=title,
        summary=", ".join(_display_label(candidate) for candidate in selected),
        sheet_name=block.sheet_name,
        block_id=block.id,
        candidate_ids=tuple(candidate.id for candidate in selected),
        preview_ranges=preview_ranges,
        default_selected=default_selected,
        rationale=f"Grouped {kind} columns from the same block.",
        confidence=max((candidate.confidence for candidate in selected), default=None),
    )


def build_binding_suggestions(
    sheet_name: str,
    frame: pd.DataFrame,
    block: SheetBlock,
    candidates: list[FieldCandidate],
) -> list[BindingSuggestion]:
    block_frame = _block_frame(frame, block)
    suggestions: list[BindingSuggestion] = []
    if structure_suggestion := _build_structure_rows_suggestion(block, candidates):
        suggestions.append(structure_suggestion)
    curve_suggestion = _build_curve_pair_suggestion(block, block_frame, candidates)
    if curve_suggestion is not None:
        suggestions.append(curve_suggestion)
    excluded_ids = set(curve_suggestion.candidate_ids if curve_suggestion is not None else ())
    if metric_suggestion := _build_group_suggestion(
        block=block,
        candidates=candidates,
        kind="metric",
        title="Recommended Metrics",
        role="metric",
        excluded_candidate_ids=excluded_ids,
        default_selected=True,
    ):
        suggestions.append(metric_suggestion)
    if metadata_suggestion := _build_group_suggestion(
        block=block,
        candidates=candidates,
        kind="metadata",
        title="Recommended Metadata",
        role="metadata",
        excluded_candidate_ids=set(),
        default_selected=True,
    ):
        suggestions.append(metadata_suggestion)
    suggestions.sort(
        key=lambda item: (
            not item.default_selected,
            {"curve_pair": 0, "structure_rows": 1, "metric_group": 2, "metadata_group": 3}.get(item.kind, 9),
            -(item.confidence or 0.0),
            item.title.lower(),
        )
    )
    return suggestions


def match_template(preview: RawFilePreview, template: TemplateDefinition) -> TemplateMatch | None:
    reasons: list[str] = []
    matched_sheets: list[str] = []
    score = 0.0
    preview_text = " ".join(
        _cell_text(value)
        for sheet in preview.sheets
        for row in sheet.sample_rows
        for value in row
        if _cell_text(value)
    ).lower()
    candidate_kinds = {candidate.kind for candidate in preview.field_candidates}
    file_suffix = preview.source_path.suffix.lower().lstrip(".")
    if template.file_types and file_suffix not in {item.lower() for item in template.file_types}:
        return None
    for condition in template.match_conditions:
        condition_score = 0.0
        text_hit = False
        if condition.sheet_name_contains:
            sheet_hits = [
                sheet.sheet_name
                for sheet in preview.sheets
                if any(keyword.lower() in sheet.sheet_name.lower() for keyword in condition.sheet_name_contains)
            ]
            if sheet_hits:
                condition_score += 0.25
                matched_sheets.extend(sheet_hits)
                reasons.append(f"Matched sheet hint: {', '.join(sorted(set(sheet_hits)))}.")
        if condition.text_contains:
            text_hits = [keyword for keyword in condition.text_contains if keyword.lower() in preview_text]
            if text_hits:
                text_hit = True
                condition_score += 0.45
                reasons.append(f"Matched text hints: {', '.join(text_hits[:4])}.")
        if condition.field_kinds:
            field_hits = [kind for kind in condition.field_kinds if kind in candidate_kinds]
            requires_text_hit = bool(condition.text_contains)
            if field_hits and (not requires_text_hit or text_hit):
                condition_score += 0.3
                reasons.append(f"Matched field candidates: {', '.join(field_hits)}.")
        score += condition_score
    if not template.match_conditions:
        return None
    if score <= 0:
        return None
    confidence = min(0.99, max(score, 0.1))
    minimum_score = max((condition.minimum_score for condition in template.match_conditions), default=0.0)
    if confidence < minimum_score:
        return None
    return TemplateMatch(
        template_id=template.id,
        label=template.label,
        family=template.family,
        confidence=confidence,
        reasons=tuple(dict.fromkeys(reasons)),
        matched_sheet_names=tuple(dict.fromkeys(matched_sheets)),
        auto_selected=confidence >= 0.75,
    )


def recommend_templates_for_preview(preview: RawFilePreview) -> tuple[TemplateMatch, ...]:
    ranked: list[tuple[TemplateMatch, bool]] = []
    for template in list_templates():
        match = match_template(preview, template)
        if match is None:
            continue
        ranked.append((match, template.builtin))
    ranked.sort(
        key=lambda item: (
            -item[0].confidence,
            item[1],  # Prefer user templates when confidence ties.
            item[0].label.lower(),
            item[0].template_id,
        )
    )
    return tuple(match for match, _builtin in ranked)


def preview_raw_file(path: str | Path) -> RawFilePreview:
    source_path = Path(path).expanduser()
    sheets, encoding, delimiter = read_preview_source(source_path)
    sheet_previews: list[RawSheetPreview] = []
    field_candidates: list[FieldCandidate] = []
    binding_suggestions: list[BindingSuggestion] = []
    frames_by_sheet: dict[str, pd.DataFrame] = {}
    for sheet_name, frame in sheets:
        frames_by_sheet[sheet_name] = frame
        blocks = detect_sheet_blocks(sheet_name, frame)
        sheet_previews.append(
            RawSheetPreview(
                sheet_name=sheet_name,
                row_count=frame.shape[0],
                col_count=frame.shape[1],
                sample_rows=tuple(tuple(value for value in row) for row in frame.head(16).itertuples(index=False)),
                blocks=blocks,
            )
        )
        for block in blocks:
            field_candidates.extend(infer_field_candidates(sheet_name, frame, block))
    candidates_by_block: dict[str, list[FieldCandidate]] = {}
    for candidate in field_candidates:
        if candidate.block_id is None:
            continue
        candidates_by_block.setdefault(candidate.block_id, []).append(candidate)
    for sheet in sheet_previews:
        frame = frames_by_sheet[sheet.sheet_name]
        for block in sheet.blocks:
            binding_suggestions.extend(
                build_binding_suggestions(
                    sheet.sheet_name,
                    frame,
                    block,
                    candidates_by_block.get(block.id, []),
                )
            )
    preview = RawFilePreview(
        source_path=source_path,
        file_type=source_path.suffix.lower().lstrip("."),
        encoding=encoding,
        delimiter=delimiter,
        sheet_names=tuple(sheet.sheet_name for sheet in sheet_previews),
        sheets=tuple(sheet_previews),
        field_candidates=tuple(field_candidates),
        binding_suggestions=tuple(binding_suggestions),
    )
    recommendations = recommend_templates_for_preview(preview)
    return replace(preview, recommended_template_ids=tuple(match.template_id for match in recommendations[:5]))


def preview_and_recommend(path: str | Path) -> tuple[RawFilePreview, tuple[TemplateMatch, ...]]:
    preview = preview_raw_file(path)
    return preview, recommend_templates_for_preview(preview)


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "detect_data_start_row",
    "detect_header_row",
    "detect_sheet_blocks",
    "infer_field_candidates",
    "match_template",
    "preview_and_recommend",
    "preview_raw_file",
    "read_preview_source",
    "recommend_templates_for_preview",
    "sniff_delimiter",
    "sniff_text_encoding",
]
