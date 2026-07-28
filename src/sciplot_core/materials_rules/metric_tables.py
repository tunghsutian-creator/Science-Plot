"""Read normalized curve tables and compute reusable curve-level metric values."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from sciplot_core.materials_rules.tokens import (
    normalize_token,
    _metric_header_matches,
)

from sciplot_core.materials_rules.unit_formatting import (
    format_unit_label,
)

from sciplot_core.materials_rules.models import (
    ELONGATION_AT_BREAK_METRIC,
    LEGACY_STRAIN_AT_BREAK_METRIC,
)
from sciplot_core.source_tables import read_raw_table


def _write_metrics_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ("metric", "value", "unit", "status", "reason")
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _metric(
    metric: str,
    value: float | str | None,
    unit: str = "",
    status: str = "ok",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": "" if value is None else value,
        "unit": format_unit_label(unit),
        "status": status,
        "reason": reason,
    }


def _read_labeled_paired_curve_series(
    path: Path,
    *,
    x_tokens: tuple[str, ...] = (),
    y_tokens: tuple[str, ...] = (),
) -> list[tuple[str, str, pd.DataFrame]]:
    raw = read_raw_table(path)
    if raw.shape[0] < 4:
        return []
    if x_tokens:
        x_columns = [
            column
            for column in range(raw.shape[1])
            if _metric_header_matches(raw.iat[0, column], x_tokens)
        ]
        y_columns = [
            column
            for column in range(raw.shape[1])
            if _metric_header_matches(raw.iat[0, column], y_tokens)
        ]
        pairs = [
            (
                max(candidate for candidate in x_columns if candidate < y_column),
                y_column,
            )
            for y_column in y_columns
            if any(candidate < y_column for candidate in x_columns)
        ]
    else:
        pairs = [(column, column + 1) for column in range(0, raw.shape[1] - 1, 2)]
    series: list[tuple[str, str, pd.DataFrame]] = []
    for x_column, y_column in pairs:
        y_header = str(raw.iat[0, y_column]).strip()
        if y_tokens and not _metric_header_matches(y_header, y_tokens):
            continue
        data = (
            raw.iloc[3:, [x_column, y_column]]
            .apply(pd.to_numeric, errors="coerce")
            .dropna()
        )
        if not data.empty:
            data.columns = ["x", "y"]
            first_pair = tuple(
                str(raw.iat[1, index]).strip() for index in (x_column, y_column)
            )
            second_pair = tuple(
                str(raw.iat[2, index]).strip() for index in (x_column, y_column)
            )
            first_is_sample = bool(first_pair[0]) and normalize_token(
                first_pair[0]
            ) == normalize_token(first_pair[1])
            second_is_sample = bool(second_pair[0]) and normalize_token(
                second_pair[0]
            ) == normalize_token(second_pair[1])
            if first_is_sample and not second_is_sample:
                sample = first_pair[0]
            else:
                # The canonical four-row CSV contract stores unit then sample.
                # This also gives a deterministic fallback for legacy tables
                # whose two metadata rows cannot be distinguished safely.
                sample = second_pair[0]
            if not sample or sample.casefold() == "nan":
                sample = f"series_{len(series) + 1}"
            series.append((sample, y_header, data.reset_index(drop=True)))
    return series


def _read_labeled_paired_curve_table(
    path: Path,
    *,
    x_tokens: tuple[str, ...] = (),
    y_tokens: tuple[str, ...] = (),
) -> list[tuple[str, pd.DataFrame]]:
    return [
        (sample, frame)
        for sample, _y_header, frame in _read_labeled_paired_curve_series(
            path,
            x_tokens=x_tokens,
            y_tokens=y_tokens,
        )
    ]


def _read_paired_curve_table(path: Path) -> list[pd.DataFrame]:
    return [frame for _sample, frame in _read_labeled_paired_curve_table(path)]


def tensile_curve_metric_values(
    points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    *,
    x_unit: str = "%",
    reported: dict[str, float] | None = None,
) -> dict[str, float | str]:
    """Return publication-safe tensile metrics from one engineering curve.

    Instrument-reported strength, break strain, and the programmed low-strain
    modulus take precedence when present.  Derived modulus values convert
    percent strain to a unitless fraction, and toughness is reported as
    MJ/m3 rather than the intermediate MPa-percent integral.
    """

    data = pd.DataFrame(points, columns=["strain", "stress"])
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    if data.empty:
        raise ValueError(
            "A tensile metric calculation needs at least one finite stress-strain point."
        )
    data = data.sort_values("strain", kind="stable").drop_duplicates(
        subset="strain", keep="last"
    )
    reported = reported or {}

    reported_strength = reported.get("strength_MPa")
    strength = (
        float(reported_strength)
        if reported_strength is not None and np.isfinite(float(reported_strength))
        else float(data["stress"].max())
    )
    strength_source = (
        "instrument_report" if reported_strength is not None else "curve_maximum"
    )

    reported_break = reported.get(ELONGATION_AT_BREAK_METRIC)
    if reported_break is None:
        reported_break = reported.get(LEGACY_STRAIN_AT_BREAK_METRIC)
    elongation_at_break = (
        float(reported_break)
        if reported_break is not None and np.isfinite(float(reported_break))
        else float(data["strain"].iloc[-1])
    )
    break_source = (
        "instrument_report" if reported_break is not None else "curve_terminal_point"
    )

    unit_token = str(x_unit or "%").strip().casefold()
    strain_is_percent = "%" in unit_token or "percent" in unit_token
    strain_fraction_factor = 0.01 if strain_is_percent else 1.0
    fit_low, fit_high = (0.05, 0.25) if strain_is_percent else (0.0005, 0.0025)
    fit = data[(data["strain"] >= fit_low) & (data["strain"] <= fit_high)]
    if len(fit) < 2 or fit["strain"].nunique() < 2:
        fit = data[(data["strain"] >= 0.0) & (data["strain"] <= fit_high)]
    if len(fit) < 2 or fit["strain"].nunique() < 2:
        fit = data.iloc[: min(25, len(data))]
    derived_modulus = float("nan")
    if len(fit) >= 2 and fit["strain"].nunique() >= 2:
        try:
            slope = float(
                np.polyfit(
                    fit["strain"].to_numpy(dtype=float),
                    fit["stress"].to_numpy(dtype=float),
                    deg=1,
                )[0]
            )
            derived_modulus = slope / strain_fraction_factor
        except (ValueError, np.linalg.LinAlgError):
            derived_modulus = float("nan")
    reported_modulus = reported.get("modulus_MPa")
    modulus = (
        float(reported_modulus)
        if reported_modulus is not None and np.isfinite(float(reported_modulus))
        else derived_modulus
    )
    modulus_source = (
        "instrument_report_0.05_to_0.25_percent"
        if reported_modulus is not None
        else "curve_fit"
    )

    clipped = data[data["strain"] <= elongation_at_break].copy()
    after_break = data[data["strain"] > elongation_at_break]
    if (
        not clipped.empty
        and not after_break.empty
        and float(clipped["strain"].iloc[-1]) < elongation_at_break
    ):
        left = clipped.iloc[-1]
        right = after_break.iloc[0]
        x0, y0 = float(left["strain"]), float(left["stress"])
        x1, y1 = float(right["strain"]), float(right["stress"])
        if x1 > x0:
            y_break = y0 + (elongation_at_break - x0) * (y1 - y0) / (x1 - x0)
            clipped = pd.concat(
                [
                    clipped,
                    pd.DataFrame([{"strain": elongation_at_break, "stress": y_break}]),
                ],
                ignore_index=True,
            )
    if len(clipped) >= 2:
        toughness = float(
            np.trapezoid(
                clipped["stress"].to_numpy(dtype=float),
                clipped["strain"].to_numpy(dtype=float) * strain_fraction_factor,
            )
        )
    else:
        toughness = float("nan")

    if (
        reported_break is not None
        and float(data["strain"].iloc[-1]) >= elongation_at_break
    ):
        toughness_source = "curve_integral_to_reported_break"
    elif reported_break is not None:
        toughness_source = "curve_integral_over_available_excerpt_before_reported_break"
    else:
        toughness_source = "curve_integral"

    return {
        "strength_MPa": strength,
        "strength_source": strength_source,
        ELONGATION_AT_BREAK_METRIC: elongation_at_break,
        "elongation_at_break_source": break_source,
        "modulus_MPa": modulus,
        "modulus_source": modulus_source,
        "toughness_MJ_m3": toughness,
        "toughness_source": toughness_source,
    }
