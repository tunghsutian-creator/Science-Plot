"""Detect torque events and read curated or automatic torque series."""

from __future__ import annotations

import json
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
    _unit_for,
    _float,
)

from sciplot_core.semantic_sources.series_labels import (
    _intake_group_name,
)

from sciplot_core.semantic_sources.torque_event_selection import (
    _apply_torque_selection,
    _auto_torque_event_selection,
    _normalize_torque_unit,
)


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
    first_error: Exception | None = None
    try:
        raw = read_raw_table(source).dropna(axis=1, how="all")
        evidence = " ".join(
            str(value)
            for value in [
                *raw.columns.tolist(),
                *raw.iloc[:4].to_numpy().ravel().tolist(),
            ]
        )
        if "torque" in evidence.casefold() or "转矩" in evidence:
            return raw
    except Exception as exc:
        first_error = exc
    last_error: Exception | None = first_error
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "utf-16", "latin-1"):
        try:
            raw = pd.read_csv(source, sep="\t", header=None, encoding=encoding).dropna(
                axis=1, how="all"
            )
            evidence = " ".join(
                str(value) for value in raw.iloc[:4].to_numpy().ravel().tolist()
            )
            if "torque" in evidence.casefold() or "转矩" in evidence:
                return raw
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not read torque export {source}.") from last_error


def _read_torque_full_series(source: Path) -> CurveSeriesPayload:
    raw = _read_torque_table(source)
    header_index = 0
    x_index: int | None = None
    y_index: int | None = None
    header_candidates: list[tuple[int, list[object]]] = [(-1, raw.columns.tolist())]
    header_candidates.extend(
        (index, raw.iloc[index].tolist()) for index in range(min(8, raw.shape[0]))
    )
    for candidate_index, candidate_values in header_candidates:
        headers = [_clean_text(value) for value in candidate_values]
        try:
            candidate_x = _find_column(headers, ("index", "time", "时间"))
            candidate_y = _find_column(headers, ("screwtorque", "torque", "转矩"))
        except ValueError:
            continue
        header_index = candidate_index
        x_index = candidate_x
        y_index = candidate_y
        break
    if x_index is None or y_index is None:
        raise ValueError(
            f"Could not find Index/Time and Screw Torque columns in {source}."
        )
    unit_index = max(0, header_index + 1)
    units = (
        [_clean_text(value) for value in raw.iloc[unit_index].tolist()]
        if raw.shape[0] > unit_index
        else []
    )
    points: list[tuple[float, float]] = []
    for row_index in range(max(0, header_index + 1), raw.shape[0]):
        x_value = _float(raw.iat[row_index, x_index])
        y_value = _float(raw.iat[row_index, y_index])
        if x_value is not None and y_value is not None:
            points.append((x_value, y_value))
    if not points:
        raise ValueError(f"No numeric torque points found in {source}.")
    y_unit = _normalize_torque_unit(_unit_for(units, y_index, "N·m"))
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
    if curation is not None:
        selection = _torque_selection_for_source(
            source=source, series=full_series, curation=curation
        )
    else:
        candidate = _auto_torque_event_selection(full_series)
        if candidate.get("needs_human_review"):
            selection = {
                "sample": full_series.sample,
                "start_s": full_series.points[0][0],
                "end_s": full_series.points[-1][0],
                "time_zero": "start_s",
                "source": "full_curve_unconfirmed_event",
                "confidence": candidate.get("confidence", 0.0),
                "needs_human_review": True,
                "reason": (
                    "Automatic final-event detection was not confident, so SciPlot preserved the full curve "
                    "instead of silently trimming it."
                ),
                "automatic_candidate": candidate,
            }
        else:
            selection = candidate
    return _apply_torque_selection(full_series, selection)
