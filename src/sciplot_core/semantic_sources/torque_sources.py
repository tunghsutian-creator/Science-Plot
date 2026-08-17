"""Read full or explicitly curated torque series."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
)

from sciplot_core.source_tables import (
    read_raw_table,
)

from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _find_column,
    _float,
)

from sciplot_core.semantic_sources.series_labels import (
    _intake_group_name,
)

from sciplot_core.semantic_sources.torque_event_selection import (
    _apply_torque_selection,
    _normalize_torque_unit,
)


_HEADER_UNIT_RE = re.compile(r"(?:\(([^()]*)\)|\[([^\[\]]*)\])\s*$")


def _header_unit(value: object) -> str:
    match = _HEADER_UNIT_RE.search(_clean_text(value))
    if match is None:
        return ""
    return _clean_text(next(group for group in match.groups() if group is not None))


def _required_torque_unit(
    *,
    header: str,
    adjacent: object,
    axis: str,
    source: Path,
) -> tuple[str, str]:
    header_value = _header_unit(header)
    if header_value:
        return header_value, "detected_from_header"
    adjacent_value = _clean_text(adjacent).strip("[]() ")
    if not adjacent_value or _float(adjacent_value) is not None:
        raise ValueError(
            f"Torque {axis} unit is missing in {source}; use an explicit header "
            "unit or adjacent unit row."
        )
    return adjacent_value, "detected_from_adjacent_unit_row"


def _torque_time_conversion(
    source_unit: str,
    *,
    source: Path,
) -> tuple[float, str]:
    token = re.sub(r"[.\s_-]+", "", source_unit.casefold())
    conversions = {
        "s": (1.0, "identity"),
        "sec": (1.0, "identity"),
        "second": (1.0, "identity"),
        "seconds": (1.0, "identity"),
        "min": (60.0, "minute_to_second"),
        "minute": (60.0, "minute_to_second"),
        "minutes": (60.0, "minute_to_second"),
        "h": (3600.0, "hour_to_second"),
        "hr": (3600.0, "hour_to_second"),
        "hour": (3600.0, "hour_to_second"),
        "hours": (3600.0, "hour_to_second"),
    }
    conversion = conversions.get(token)
    if conversion is None:
        raise ValueError(
            f"Unsupported torque time unit {source_unit!r} in {source}; "
            "expected explicit s, min, or h evidence."
        )
    return conversion


def _torque_unit_conversion(
    source_unit: str,
    *,
    source: Path,
) -> tuple[str, float, str]:
    canonical = _normalize_torque_unit(source_unit)
    if canonical != "N·m":
        raise ValueError(
            f"Unsupported torque response unit {source_unit!r} in {source}; "
            "expected an explicit N·m identity alias."
        )
    return canonical, 1.0, "identity"


def _torque_source_files(source: Path) -> list[Path]:
    suffixes = {".txt", ".csv", ".tsv"}
    if source.is_file() and source.suffix.lower() in suffixes:
        return [source]
    if not source.is_dir():
        return []
    return sorted(
        (
            path
            for path in source.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes
        ),
        key=lambda path: path.name,
    )


def _read_torque_table(source: Path) -> pd.DataFrame:
    raw = read_raw_table(source).dropna(axis=1, how="all")
    evidence = " ".join(
        str(value)
        for value in [
            *raw.columns.tolist(),
            *raw.iloc[:4].to_numpy().ravel().tolist(),
        ]
    )
    if "torque" not in evidence.casefold() and "转矩" not in evidence:
        raise ValueError(f"Could not find torque evidence in {source}.")
    return raw


def _read_torque_full_series(source: Path) -> CurveSeriesPayload:
    raw = _read_torque_table(source)
    header_index = 0
    x_index: int | None = None
    y_index: int | None = None
    x_header = ""
    y_header = ""
    header_candidates: list[tuple[int, list[object]]] = [(-1, raw.columns.tolist())]
    header_candidates.extend(
        (index, raw.iloc[index].tolist()) for index in range(min(8, raw.shape[0]))
    )
    for candidate_index, candidate_values in header_candidates:
        headers = [_clean_text(value) for value in candidate_values]
        try:
            candidate_x = _find_column(headers, ("time", "时间"))
            candidate_y = _find_column(headers, ("screwtorque", "torque", "转矩"))
        except ValueError:
            continue
        header_index = candidate_index
        x_index = candidate_x
        y_index = candidate_y
        x_header = headers[x_index]
        y_header = headers[y_index]
        break
    if x_index is None or y_index is None:
        raise ValueError(
            f"Could not find explicit Time and Screw Torque columns in {source}; "
            "Index alone is not time evidence."
        )
    unit_index = max(0, header_index + 1)
    units = (
        [_clean_text(value) for value in raw.iloc[unit_index].tolist()]
        if raw.shape[0] > unit_index
        else []
    )
    adjacent_x_unit = units[x_index] if x_index < len(units) else ""
    adjacent_y_unit = units[y_index] if y_index < len(units) else ""
    source_x_unit, x_unit_detection = _required_torque_unit(
        header=x_header,
        adjacent=adjacent_x_unit,
        axis="time",
        source=source,
    )
    x_factor, x_method = _torque_time_conversion(source_x_unit, source=source)
    source_y_unit, y_unit_detection = _required_torque_unit(
        header=y_header,
        adjacent=adjacent_y_unit,
        axis="response",
        source=source,
    )
    y_unit, y_factor, y_method = _torque_unit_conversion(
        source_y_unit,
        source=source,
    )
    points: list[tuple[float, float]] = []
    for row_index in range(max(0, header_index + 1), raw.shape[0]):
        x_value = _float(raw.iat[row_index, x_index])
        y_value = _float(raw.iat[row_index, y_index])
        if x_value is not None and y_value is not None:
            points.append((x_value * x_factor, y_value * y_factor))
    if not points:
        raise ValueError(f"No numeric torque points found in {source}.")
    sample = source.stem
    intake_group = _intake_group_name(sample)
    if intake_group is not None:
        sample = intake_group
    return CurveSeriesPayload(
        sample=sample,
        x_label="Time",
        x_unit="s",
        y_label="Screw torque",
        y_unit=y_unit,
        points=tuple(points),
        diagnostics={
            "source_file": str(source.resolve()),
            "source_x_header": x_header,
            "source_y_header": y_header,
            "x_unit_conversion": {
                "source_unit": source_x_unit,
                "canonical_unit": "s",
                "factor": x_factor,
                "method": x_method,
                "unit_detection": x_unit_detection,
            },
            "y_unit_conversion": {
                "source_unit": source_y_unit,
                "canonical_unit": "N·m",
                "factor": y_factor,
                "method": y_method,
                "unit_detection": y_unit_detection,
            },
        },
    )


def _load_torque_curation(curation_path: str | Path | None) -> dict[str, Any] | None:
    if curation_path is None:
        return None
    path = Path(curation_path).expanduser()
    if not path.exists():
        raise ValueError(f"Torque curation file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Torque curation file must contain a JSON object.")
    return payload


def _torque_selection_for_source(
    *,
    source: Path,
    series: CurveSeriesPayload,
    curation: dict[str, Any] | None,
) -> dict[str, Any]:
    if curation is not None:
        resolved = str(source.expanduser().resolve())
        source_name = source.name
        for item in curation.get("samples", []):
            if not isinstance(item, dict):
                continue
            item_source = str(item.get("source_path") or "")
            item_sample = str(item.get("sample") or "")
            if (
                item_source == resolved
                or Path(item_source).name == source_name
                or item_sample == series.sample
            ):
                return item
    return {
        "sample": series.sample,
        "start_s": series.points[0][0],
        "end_s": series.points[-1][0],
        "time_zero": "absolute",
        "source": "full_curve",
        "confidence": 100.0,
        "needs_human_review": False,
        "reason": "Using the full torque curve; event trimming requires an explicit curation file.",
    }


def _read_torque_series(
    source: Path, *, curation: dict[str, Any] | None = None
) -> CurveSeriesPayload:
    full_series = _read_torque_full_series(source)
    selection = _torque_selection_for_source(
        source=source,
        series=full_series,
        curation=curation,
    )
    diagnostics = dict(full_series.diagnostics or {})
    selection = {
        **selection,
        "x_unit_conversion": diagnostics["x_unit_conversion"],
        "y_unit_conversion": diagnostics["y_unit_conversion"],
    }
    if curation is None:
        return CurveSeriesPayload(
            sample=full_series.sample,
            x_label=full_series.x_label,
            x_unit=full_series.x_unit,
            y_label=full_series.y_label,
            y_unit=full_series.y_unit,
            points=full_series.points,
            diagnostics={
                **(full_series.diagnostics or {}),
                "event_selection": selection,
                "source_point_count": len(full_series.points),
                "selected_point_count": len(full_series.points),
            },
        )
    return _apply_torque_selection(full_series, selection)
