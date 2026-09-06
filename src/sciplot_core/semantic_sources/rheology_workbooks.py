"""Materialize normalized rheology comparison workbooks."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import pandas as pd


from sciplot_core.semantic_sources.models import (
    RheologySweepSample,
    _RHEOLOGY_SWEEP_METRICS,
)

from sciplot_core.semantic_sources.rheology_replicates import (
    _sheet_name,
)


def _sweep_comparison_frame_for_metrics(
    samples: list[RheologySweepSample],
    *,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
) -> pd.DataFrame:
    metric_keys = tuple(key for key, _label, _aliases, _unit in metrics)
    headers: list[object] = []
    sample_row: list[object] = []
    unit_row: list[object] = []
    max_rows = max(len(sample.rows) for sample in samples)
    for sample in samples:
        headers.append(sample.x_label)
        sample_row.append(sample.sample)
        unit_row.append(sample.x_unit)
        for key, label, _aliases, default_unit in metrics:
            headers.append(label)
            sample_row.append(sample.sample)
            unit_row.append(sample.metric_units.get(key, default_unit))
    rows: list[list[object]] = [headers, sample_row, unit_row]
    for point_index in range(max_rows):
        row: list[object] = []
        for sample in samples:
            if point_index < len(sample.rows):
                point = sample.rows[point_index]
                row.append(point.get("x", ""))
                row.extend(point.get(key, "") for key in metric_keys)
            else:
                row.extend([""] * (1 + len(metric_keys)))
        rows.append(row)
    return pd.DataFrame(rows)


def _sample_sweep_frame(
    sample: RheologySweepSample,
    *,
    metrics: tuple[
        tuple[str, str, tuple[str, ...], str], ...
    ] = _RHEOLOGY_SWEEP_METRICS,
) -> pd.DataFrame:
    headers = [sample.x_label, *[label for _key, label, _aliases, _unit in metrics]]
    units = [
        sample.x_unit,
        *[
            sample.metric_units.get(key, default_unit)
            for key, _label, _aliases, default_unit in metrics
        ],
    ]
    rows: list[list[object]] = [headers, units]
    for point in sample.rows:
        rows.append(
            [
                point.get("x", ""),
                *[point.get(key, "") for key, _label, _aliases, _unit in metrics],
            ]
        )
    return pd.DataFrame(rows)


def _write_rheology_sweep_comparison_workbook(
    samples: list[RheologySweepSample],
    output_path: Path,
    *,
    comparison_sheet: str,
    metrics: tuple[
        tuple[str, str, tuple[str, ...], str], ...
    ] = _RHEOLOGY_SWEEP_METRICS,
    source_replicates: list[RheologySweepSample] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{output_path.stem}-", suffix=".xlsx", dir=output_path.parent
    )
    os.close(descriptor)
    candidate = Path(name)
    try:
        _write_sweep_workbook(
            samples,
            candidate,
            comparison_sheet=comparison_sheet,
            metrics=metrics,
            source_replicates=source_replicates,
        )
        # Several figure tasks read this shared table. Excel ZIP timestamps and
        # core-property dates can change on each save even when every data and
        # presentation entry is identical. Keep the bytes already bound by the
        # earlier figures; the scientific source hash itself is never relaxed.
        if output_path.is_file() and _same_workbook_content(output_path, candidate):
            return
        if output_path.is_file():
            candidate.chmod(output_path.stat().st_mode & 0o777)
        with candidate.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(candidate, output_path)
    finally:
        candidate.unlink(missing_ok=True)


def _workbook_content(path: Path) -> tuple[tuple[str, bytes], ...]:
    parts: list[tuple[str, bytes]] = []
    with ZipFile(path) as archive:
        for member in archive.infolist():
            content = archive.read(member)
            if member.filename == "docProps/core.xml":
                properties = ElementTree.fromstring(content)
                for field in ("created", "modified"):
                    for timestamp in properties.findall(
                        f"{{http://purl.org/dc/terms/}}{field}"
                    ):
                        properties.remove(timestamp)
                content = ElementTree.tostring(properties)
            parts.append((member.filename, content))
    return tuple(sorted(parts))


def _same_workbook_content(previous: Path, current: Path) -> bool:
    try:
        return _workbook_content(previous) == _workbook_content(current)
    except (BadZipFile, ElementTree.ParseError):
        return False


def _write_sweep_workbook(
    samples: list[RheologySweepSample],
    output_path: Path,
    *,
    comparison_sheet: str,
    metrics: tuple[tuple[str, str, tuple[str, ...], str], ...],
    source_replicates: list[RheologySweepSample] | None,
) -> None:
    used_sheet_names: set[str] = set()
    with pd.ExcelWriter(output_path) as writer:
        _sweep_comparison_frame_for_metrics(samples, metrics=metrics).to_excel(
            writer,
            sheet_name=_sheet_name(comparison_sheet, used_sheet_names),
            header=False,
            index=False,
        )
        for sample in samples:
            _sample_sweep_frame(sample, metrics=metrics).to_excel(
                writer,
                sheet_name=_sheet_name(sample.sample, used_sheet_names),
                header=False,
                index=False,
            )
        for replicate_index, sample in enumerate(source_replicates or [], start=1):
            _sample_sweep_frame(sample, metrics=metrics).to_excel(
                writer,
                sheet_name=_sheet_name(
                    f"Raw_{replicate_index}_{sample.sample}", used_sheet_names
                ),
                header=False,
                index=False,
            )
