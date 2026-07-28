"""Compute rheology, tensile, creep, and torque analysis metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from sciplot_core.materials_rules.models import (
    ELONGATION_AT_BREAK_METRIC,
    LEGACY_STRAIN_AT_BREAK_METRIC,
    ELONGATION_AT_BREAK_IQR_METRIC,
)

from sciplot_core.materials_rules.metric_tables import (
    _metric,
    _read_labeled_paired_curve_table,
    _read_paired_curve_table,
    tensile_curve_metric_values,
)


def _interpolated_threshold_time(
    data: pd.DataFrame, threshold: float = 0.5
) -> float | None:
    below = data[data["y"] <= threshold]
    if below.empty:
        return None
    index = int(below.index[0])
    if index == 0:
        return float(data.loc[index, "x"])
    x0, y0 = float(data.loc[index - 1, "x"]), float(data.loc[index - 1, "y"])
    x1, y1 = float(data.loc[index, "x"]), float(data.loc[index, "y"])
    if y1 == y0:
        return x1
    return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)


def _stress_relaxation_metrics(processed_source: Path) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(
        processed_source,
        y_tokens=("normalized stress", "normalized modulus", "stress", "modulus"),
    )
    if not series:
        return [
            _metric(
                "final_normalized_value",
                None,
                "sigma/sigma0",
                "skipped",
                "No normalized curve found.",
            )
        ]
    rows: list[dict[str, Any]] = []
    multiple = len(series) > 1
    for sample, data in series:
        finite = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values("x", kind="stable")
            .drop_duplicates(subset="x", keep="last")
            .reset_index(drop=True)
        )
        suffix = f"[{sample}]" if multiple else ""
        if finite.empty:
            reason = "No finite normalized values found in this canonical pair."
            rows.append(
                _metric(
                    f"final_normalized_value{suffix}",
                    None,
                    "sigma/sigma0",
                    "skipped",
                    reason,
                )
            )
            rows.append(_metric(f"t50_s{suffix}", None, "s", "skipped", reason))
            continue
        final_value = float(finite["y"].iloc[-1])
        peak_index = int(finite["y"].idxmax())
        post_peak = finite.iloc[peak_index:].reset_index(drop=True)
        post_peak_values = post_peak["y"].to_numpy(dtype=float)
        threshold_sides = post_peak_values > 0.5
        threshold_crossing_count = int(
            np.count_nonzero(threshold_sides[:-1] != threshold_sides[1:])
        )
        t50 = (
            _interpolated_threshold_time(post_peak, 0.5)
            if threshold_crossing_count == 1
            else None
        )
        rows.append(
            _metric(f"final_normalized_value{suffix}", final_value, "sigma/sigma0")
        )
        if threshold_crossing_count == 0:
            t50_reason = "Post-maximum curve has no unique crossing of 0.5."
        elif threshold_crossing_count > 1:
            t50_reason = (
                "Post-maximum curve crosses 0.5 more than once; t50 is "
                "not reported for a noisy or non-monotonic trace."
            )
        elif t50 is None:
            t50_reason = "Post-maximum curve never reached 0.5."
        else:
            t50_reason = ""
        rows.append(
            _metric(
                f"t50_s{suffix}",
                t50,
                "s",
                "ok" if t50 is not None else "skipped",
                t50_reason,
            )
        )
    return rows


def _creep_metrics(processed_source: Path) -> list[dict[str, Any]]:
    frames = _read_paired_curve_table(processed_source)
    if not frames:
        return [
            _metric(
                "final_compliance", None, "1/Pa", "skipped", "No creep curve found."
            )
        ]
    return [
        _metric("final_compliance", float(frames[0]["y"].iloc[-1]), "1/Pa"),
        _metric(
            "recovery_ratio",
            None,
            "fraction",
            "skipped",
            "Recovery segment not detected.",
        ),
    ]


def _tensile_summary_metrics(summary_source: Path) -> list[dict[str, Any]]:
    summary = pd.read_csv(summary_source)
    if (
        ELONGATION_AT_BREAK_METRIC not in summary.columns
        and LEGACY_STRAIN_AT_BREAK_METRIC in summary.columns
    ):
        summary[ELONGATION_AT_BREAK_METRIC] = summary[LEGACY_STRAIN_AT_BREAK_METRIC]
    required = {
        "sample",
        "strength_MPa",
        ELONGATION_AT_BREAK_METRIC,
        "modulus_MPa",
        "toughness_MJ_m3",
    }
    if not required <= set(summary.columns):
        return []
    samples = [
        str(value) for value in summary["sample"].dropna().drop_duplicates().tolist()
    ]
    rows: list[dict[str, Any]] = []
    metric_contract = (
        ("strength_MPa", "MPa", "strength_iqr_MPa"),
        (ELONGATION_AT_BREAK_METRIC, "%", ELONGATION_AT_BREAK_IQR_METRIC),
        ("modulus_MPa", "MPa", "modulus_iqr_MPa"),
        ("toughness_MJ_m3", "MJ/m3", "toughness_iqr_MJ_m3"),
    )
    for sample in samples:
        group = summary[summary["sample"].astype(str) == sample]
        suffix = "" if len(samples) == 1 else f"[{sample}]"
        rows.append(_metric(f"replicate_count{suffix}", int(len(group)), "count"))
        for metric_name, unit, iqr_name in metric_contract:
            values = (
                pd.to_numeric(group[metric_name], errors="coerce")
                .dropna()
                .to_numpy(dtype=float)
            )
            if values.size == 0:
                rows.append(
                    _metric(
                        f"{metric_name}{suffix}",
                        None,
                        unit,
                        "skipped",
                        "No finite replicate metric.",
                    )
                )
                rows.append(
                    _metric(
                        f"{iqr_name}{suffix}",
                        None,
                        unit,
                        "skipped",
                        "No finite replicate metric.",
                    )
                )
                continue
            reason = f"Median of {values.size} retained raw specimen value(s)."
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    float(np.median(values)),
                    unit,
                    reason=reason,
                )
            )
            if values.size >= 2:
                iqr = float(np.quantile(values, 0.75) - np.quantile(values, 0.25))
                rows.append(_metric(f"{iqr_name}{suffix}", iqr, unit))
            else:
                rows.append(
                    _metric(
                        f"{iqr_name}{suffix}",
                        None,
                        unit,
                        "skipped",
                        "At least two specimens are required for an IQR.",
                    )
                )
    return rows


def _tensile_metrics(processed_source: Path) -> list[dict[str, Any]]:
    summary_source = processed_source.with_name(f"{processed_source.stem}_summary.csv")
    if summary_source.exists():
        summary_rows = _tensile_summary_metrics(summary_source)
        if summary_rows:
            return summary_rows
    frames = _read_paired_curve_table(processed_source)
    rows: list[dict[str, Any]] = []
    if not frames:
        return [
            _metric("strength_MPa", None, "MPa", "skipped", "No tensile curve found.")
        ]
    data = frames[0].replace([np.inf, -np.inf], np.nan).dropna()
    values = tensile_curve_metric_values(
        list(zip(data["x"].astype(float), data["y"].astype(float), strict=True)),
        x_unit="%",
    )
    modulus = float(values["modulus_MPa"])
    toughness = float(values["toughness_MJ_m3"])
    modulus_status = "ok" if np.isfinite(modulus) else "skipped"
    modulus_reason = (
        ""
        if modulus_status == "ok"
        else "Low-strain fit did not have enough distinct finite points."
    )
    rows.extend(
        [
            _metric("strength_MPa", float(values["strength_MPa"]), "MPa"),
            _metric(
                ELONGATION_AT_BREAK_METRIC,
                float(values[ELONGATION_AT_BREAK_METRIC]),
                "%",
            ),
            _metric(
                "modulus_MPa",
                modulus if modulus_status == "ok" else None,
                "MPa",
                modulus_status,
                modulus_reason,
            ),
            _metric(
                "toughness_MJ_m3",
                toughness if np.isfinite(toughness) else None,
                "MJ/m3",
                "ok" if np.isfinite(toughness) else "skipped",
                ""
                if np.isfinite(toughness)
                else "Curve did not contain two points before break.",
            ),
        ]
    )
    return rows


def _torque_metrics(processed_source: Path) -> list[dict[str, Any]]:
    raw = pd.read_csv(processed_source, header=None)
    rows: list[dict[str, Any]] = []
    if raw.shape[0] < 4:
        return [
            _metric(
                "selected_event_mean_torque_Nm_by_sample",
                None,
                "N·m",
                "skipped",
                "No selected torque event found.",
            )
        ]
    for col in range(0, raw.shape[1] - 1, 2):
        sample = str(raw.iat[2, col]).strip() or f"series_{col // 2 + 1}"
        values = pd.to_numeric(raw.iloc[3:, col + 1], errors="coerce").dropna()
        metric_name = f"selected_event_mean_torque_Nm[{sample}]"
        if values.empty:
            rows.append(
                _metric(
                    metric_name,
                    None,
                    "N·m",
                    "skipped",
                    "No finite torque values found.",
                )
            )
        else:
            rows.append(_metric(metric_name, float(values.mean()), "N·m"))
    return rows or [
        _metric(
            "selected_event_mean_torque_Nm_by_sample",
            None,
            "N·m",
            "skipped",
            "No selected torque event found.",
        )
    ]
