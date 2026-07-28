"""Detect and coalesce rheology sweep replicate groups."""

from __future__ import annotations

import math
import re
from pathlib import Path
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
)


from sciplot_core.semantic_sources.models import (
    RheologySweepSample,
)

from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_frequency_comparison_samples,
    _read_rheology_temperature_comparison_samples,
)


def _normalized_replicate_mode(value: object) -> str:
    token = _clean_text(value).casefold()
    aliases = {
        "": "mean",
        "average": "mean",
        "avg": "mean",
        "best": "representative",
        "all": "individual",
    }
    token = aliases.get(token, token)
    return token if token in {"mean", "representative", "individual"} else "mean"


def _terminal_storage(sample: RheologySweepSample) -> float | None:
    points = [
        (row["x"], row["storage_modulus"])
        for row in sample.rows
        if "x" in row and "storage_modulus" in row
    ]
    if not points:
        return None
    return max(points, key=lambda item: item[0])[1]


def _mean_replicate_sample(samples: list[RheologySweepSample]) -> RheologySweepSample:
    representative = samples[0]
    metric_keys = sorted(
        {key for sample in samples for row in sample.rows for key in row if key != "x"}
    )
    x_values = sorted(
        {row["x"] for sample in samples for row in sample.rows if "x" in row}
    )
    metric_units: dict[str, str] = {}
    for sample in samples:
        for key, unit in sample.metric_units.items():
            metric_units.setdefault(key, unit)
    rows: list[dict[str, float]] = []
    for x_value in x_values:
        row: dict[str, float] = {"x": x_value}
        for key in metric_keys:
            values = [
                metric_value
                for sample in samples
                for point in sample.rows
                if point.get("x") == x_value
                for metric_value in [point.get(key)]
                if metric_value is not None and math.isfinite(metric_value)
            ]
            if values:
                row[key] = sum(values) / len(values)
        if len(row) > 1:
            rows.append(row)
    return RheologySweepSample(
        sample=representative.sample,
        source=representative.source,
        x_label=representative.x_label,
        x_unit=representative.x_unit,
        metric_units=metric_units,
        rows=tuple(rows),
        interval_count=max(sample.interval_count for sample in samples),
        selected_interval_index=representative.selected_interval_index,
        interval_selection_policy=representative.interval_selection_policy,
        source_x_unit=representative.source_x_unit,
        x_conversion=representative.x_conversion,
        metric_conversions=representative.metric_conversions,
    )


def _representative_replicate_sample(
    samples: list[RheologySweepSample],
) -> RheologySweepSample:
    terminal_values = [
        value for sample in samples if (value := _terminal_storage(sample)) is not None
    ]
    if not terminal_values:
        return max(samples, key=lambda sample: (len(sample.rows), sample.source.name))
    ordered = sorted(terminal_values)
    median = ordered[len(ordered) // 2]

    def score(sample: RheologySweepSample) -> tuple[int, float, str]:
        terminal = _terminal_storage(sample)
        distance = abs((terminal if terminal is not None else median) - median)
        return (-len(sample.rows), distance, sample.source.name)

    return min(samples, key=score)


def _coalesce_replicate_sweep_samples(
    samples: list[RheologySweepSample],
    *,
    replicate_mode: object = None,
) -> list[RheologySweepSample]:
    mode = _normalized_replicate_mode(replicate_mode)
    if mode == "individual":
        return samples
    grouped: dict[str, list[RheologySweepSample]] = {}
    order: list[str] = []
    for sample in samples:
        key = _clean_text(sample.sample) or sample.source.stem
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(sample)
    coalesced: list[RheologySweepSample] = []
    for key in order:
        group = grouped[key]
        if len(group) == 1:
            coalesced.append(group[0])
        elif mode == "representative":
            coalesced.append(_representative_replicate_sample(group))
        else:
            coalesced.append(_mean_replicate_sample(group))
    return coalesced


def is_rheology_frequency_comparison_dir(source: str | Path) -> bool:
    path = Path(source).expanduser()
    if not path.is_dir():
        return False
    return (
        len(
            _read_rheology_frequency_comparison_samples(
                path,
                strict_scope=False,
            )
        )
        >= 2
    )


def is_rheology_temperature_comparison_dir(source: str | Path) -> bool:
    path = Path(source).expanduser()
    if not path.is_dir():
        return False
    text = path.as_posix().casefold()
    if "/temp/" not in text and "temperature" not in text and "温度" not in text:
        return False
    return (
        len(
            _read_rheology_temperature_comparison_samples(
                path,
                strict_scope=False,
            )
        )
        >= 2
    )


def _sheet_name(value: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]+", "_", value).strip() or "Sample"
    base = cleaned[:31]
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = f"{base[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate
