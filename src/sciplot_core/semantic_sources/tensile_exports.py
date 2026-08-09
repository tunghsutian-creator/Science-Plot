"""Read tensile instrument exports without reducing specimen curves."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any
from sciplot_core.foundation.text_files import (
    decode_text as _decode_text,
)
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)
from sciplot_core.materials_rules import (
    ELONGATION_AT_BREAK_METRIC,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.classification import (
    is_tensile_export_dir,
    tensile_export_sample_name,
    tensile_export_csv_files,
)

from sciplot_core.semantic_sources.table_scanning import (
    _find_column,
    _unit_for,
    _float,
    _scan_curve_series_source,
)

from sciplot_core.semantic_sources.series_labels import _with_series_sample


def _reported_tensile_metrics(
    lines: list[str], *, stop_index: int | None
) -> dict[str, Any]:
    upper_bound = stop_index if stop_index is not None else len(lines)
    candidates: list[tuple[list[str], list[str], list[str]]] = []
    for header_index in range(upper_bound):
        line = lines[header_index]
        if "," not in line:
            continue
        headers = [_clean_text(value) for value in next(csv.reader([line]))]
        evidence = " ".join(headers).casefold()
        if not any(
            token in evidence
            for token in ("拉伸应力", "拉伸应变", "模量", "tensile stress", "modulus")
        ):
            continue
        units = (
            [
                _clean_text(value)
                for value in next(csv.reader([lines[header_index + 1]]))
            ]
            if header_index + 1 < upper_bound
            else []
        )
        values: list[str] = []
        for row_index in range(header_index + 2, upper_bound):
            if not lines[row_index].strip():
                continue
            values = [
                _clean_text(value) for value in next(csv.reader([lines[row_index]]))
            ]
            break
        if values:
            candidates.append((headers, units, values))

    reported: dict[str, Any] = {}
    metric_headers: dict[str, str] = {}
    for headers, _units, values in candidates:

        def value_for(
            candidate_headers: list[str],
            candidate_values: list[str],
            predicate: Any,
        ) -> tuple[float | None, str | None]:
            compact_headers = [
                re.sub(r"\s+", "", header.casefold()) for header in candidate_headers
            ]
            for column, compact in enumerate(compact_headers):
                if not predicate(compact):
                    continue
                value = _float(
                    candidate_values[column] if column < len(candidate_values) else None
                )
                if value is not None:
                    return value, candidate_headers[column]
            return None, None

        strength, strength_header = value_for(
            headers,
            values,
            lambda header: (
                ("拉伸应力" in header and "最大值" in header)
                or (
                    "tensilestress" in header
                    and any(token in header for token in ("maximum", "maxforce"))
                )
            ),
        )
        if strength is None:
            strength, strength_header = value_for(
                headers,
                values,
                lambda header: (
                    ("拉伸应力" in header and "断裂" in header)
                    or ("tensilestress" in header and "break" in header)
                ),
            )
        strain, strain_header = value_for(
            headers,
            values,
            lambda header: (
                ("拉伸应变" in header and "断裂" in header)
                or ("tensilestrain" in header and "break" in header)
            ),
        )
        modulus, modulus_header = value_for(
            headers,
            values,
            lambda header: (
                ("模量" in header and "最大值斜率" not in header)
                or ("modulus" in header and "maximumslope" not in header)
            ),
        )
        for metric_name, value, header in (
            ("strength_MPa", strength, strength_header),
            (ELONGATION_AT_BREAK_METRIC, strain, strain_header),
            ("modulus_MPa", modulus, modulus_header),
        ):
            if value is not None and metric_name not in reported:
                reported[metric_name] = value
                if header:
                    metric_headers[metric_name] = header
    if metric_headers:
        reported["reported_metric_headers"] = metric_headers
    return reported


def _read_tensile_export_series(source: Path) -> CurveSeriesPayload:
    text = _decode_tensile_export_text(source)
    lines = text.splitlines()
    header_indexes = [
        index
        for index, line in enumerate(lines)
        if "拉伸应变" in line and "拉伸应力" in line and "," in line
    ]
    section_two_index = next(
        (index for index, line in enumerate(lines) if _token(line) == "结果表格2"),
        None,
    )
    reported = _reported_tensile_metrics(lines, stop_index=section_two_index)
    if section_two_index is not None:
        preferred = [index for index in header_indexes if index > section_two_index]
        header_indexes = [
            *preferred,
            *[index for index in header_indexes if index not in preferred],
        ]
    for header_index in header_indexes:
        headers = next(csv.reader([lines[header_index]]))
        units = (
            next(csv.reader([lines[header_index + 1]]))
            if header_index + 1 < len(lines)
            else []
        )
        x_index = _find_column(headers, ("拉伸应变", "strain"))
        y_index = _find_column(headers, ("拉伸应力", "stress"))
        points: list[tuple[float, float]] = []
        for line in lines[header_index + 2 :]:
            if not line.strip():
                if points:
                    break
                continue
            row = next(csv.reader([line]))
            x_value = _float(row[x_index] if x_index < len(row) else None)
            y_value = _float(row[y_index] if y_index < len(row) else None)
            if x_value is not None and y_value is not None:
                points.append((x_value, y_value))
        if len(points) < 2:
            continue
        return CurveSeriesPayload(
            sample=source.stem,
            x_label="Tensile strain",
            x_unit=_unit_for(units, x_index, "%"),
            y_label="Tensile stress",
            y_unit=_unit_for(units, y_index, "MPa"),
            points=tuple(points),
            diagnostics={
                **reported,
                "source_file": str(source),
            },
        )
    raise ValueError(f"Could not find a multi-point tensile curve table in {source}.")


def _decode_tensile_export_text(source: Path) -> str:
    text = _decode_text(source)
    if _looks_like_tensile_export_text(text):
        return text
    payload = source.read_bytes()
    for encoding in ("gb18030", "gbk", "utf-8-sig", "utf-8", "latin-1"):
        try:
            candidate = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _looks_like_tensile_export_text(candidate):
            return candidate
    return text


def _looks_like_tensile_export_text(text: str) -> bool:
    lowered = text.casefold()
    return (
        ("拉伸应变" in text and "拉伸应力" in text)
        or ("tensile strain" in lowered and "stress" in lowered)
        or "结果表格" in text
    )


def _tensile_export_files(input_path: Path) -> list[Path]:
    if is_tensile_export_dir(input_path):
        return tensile_export_csv_files(input_path)
    if input_path.is_dir():
        return sorted(
            (
                path
                for path in input_path.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".csv"
            ),
            key=lambda path: path.as_posix().casefold(),
        )
    return [input_path]


def _read_tensile_export_series_list(source: Path) -> list[CurveSeriesPayload]:
    if source.is_file():
        structured = _scan_curve_series_source(
            source,
            x_aliases=("strain", "拉伸应变"),
            y_aliases=("stress", "σ", "sigma", "拉伸应力", "应力"),
            x_label="Tensile strain",
            y_label="Tensile stress",
            default_x_unit="%",
            default_y_unit="MPa",
            sample_prefix=source.stem,
        )
        if structured:
            resolved_source = str(source.resolve())
            return [
                CurveSeriesPayload(
                    sample=series.sample,
                    x_label=series.x_label,
                    x_unit=series.x_unit,
                    y_label=series.y_label,
                    y_unit=series.y_unit,
                    points=series.points,
                    diagnostics={
                        **(series.diagnostics or {}),
                        "source_file": resolved_source,
                    },
                )
                for series in structured
            ]
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    direct_export_group = (
        tensile_export_sample_name(source) if is_tensile_export_dir(source) else ""
    )
    for path in _tensile_export_files(source):
        try:
            series = _read_tensile_export_series(path)
            if direct_export_group and "__" not in series.sample:
                series = _with_series_sample(
                    series, f"{direct_export_group}__{series.sample}"
                )
            series_list.append(series)
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(
            f"No tensile CSV exports found under {source}. {detail}".strip()
        )
    return series_list
