"""Compute spectral peaks, local peaks, terminal values, and peak magnitudes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np
from sciplot_core.materials_rules.tokens import (
    normalize_token,
)
from sciplot_core.materials_rules.metric_tables import (
    _metric,
    _read_labeled_paired_curve_series,
    _read_labeled_paired_curve_table,
)


def _ftir_peak_position_metrics(
    source_path: Path,
    *,
    metric_name: str = "observed_response_extremum_wavenumber_cm-1",
) -> list[dict[str, Any]]:
    """Report only a mode-explicit observed FTIR response extremum."""

    series = _read_labeled_paired_curve_series(source_path)
    rows: list[dict[str, Any]] = []
    for sample, y_header, data in series:
        finite = data.replace([np.inf, -np.inf], np.nan).dropna()
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if finite.empty:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    "cm^-1",
                    "skipped",
                    "No finite observed spectral response is available.",
                )
            )
            continue
        mode = normalize_token(y_header)
        if "transmittance" in mode or mode in {"t", "percentt"}:
            index = finite["y"].idxmin()
            reason = (
                "Observed wavenumber of the minimum finite transmittance response; "
                "this descriptive extremum makes no spectral-band or chemical "
                "assignment."
            )
        elif "absorbance" in mode:
            index = finite["y"].idxmax()
            reason = (
                "Observed wavenumber of the maximum finite absorbance response; "
                "this descriptive extremum makes no spectral-band or chemical "
                "assignment."
            )
        else:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    "cm^-1",
                    "skipped",
                    "Observed response extremum skipped because the response mode "
                    f"`{y_header}` is not explicitly Transmittance or Absorbance; "
                    "no spectral-band or chemical assignment is made.",
                )
            )
            continue
        rows.append(
            _metric(
                f"{metric_name}{suffix}",
                float(finite.loc[index, "x"]),
                "cm^-1",
                reason=reason,
            )
        )
    return rows or [
        _metric(
            metric_name,
            None,
            "cm^-1",
            "skipped",
            "No canonical paired observed spectral response is available.",
        )
    ]


def _interior_local_peak_position_metrics(
    source_path: Path,
    *,
    metric_name: str,
    x_unit: str,
    x_tokens: tuple[str, ...] = (),
    y_tokens: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(
        source_path,
        x_tokens=x_tokens,
        y_tokens=y_tokens,
    )
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values("x", kind="stable")
            .drop_duplicates(subset="x", keep="last")
            .reset_index(drop=True)
        )
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if len(finite) < 3:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    x_unit,
                    "skipped",
                    "No interior peak: at least three finite paired points are required.",
                )
            )
            continue
        y_values = finite["y"].to_numpy(dtype=float)
        local = (
            np.flatnonzero(
                (y_values[1:-1] >= y_values[:-2])
                & (y_values[1:-1] >= y_values[2:])
                & ((y_values[1:-1] > y_values[:-2]) | (y_values[1:-1] > y_values[2:]))
            )
            + 1
        )
        if local.size == 0:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    x_unit,
                    "skipped",
                    "No interior peak; the boundary maximum is not reported as a scattering peak.",
                )
            )
            continue
        peak_index = int(local[np.argmax(y_values[local])])
        rows.append(
            _metric(
                f"{metric_name}{suffix}",
                float(finite.iloc[peak_index]["x"]),
                x_unit,
                reason="Highest discrete interior local-intensity maximum; boundary maxima are excluded.",
            )
        )
    return rows or [
        _metric(
            metric_name,
            None,
            x_unit,
            "skipped",
            "No canonical paired scattering trace found.",
        )
    ]


def _terminal_y_metrics(
    source_path: Path,
    *,
    metric_name: str,
    y_unit: str,
    x_boundary: str,
    x_tokens: tuple[str, ...] = (),
    y_tokens: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(
        source_path,
        x_tokens=x_tokens,
        y_tokens=y_tokens,
    )
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values("x", kind="stable")
        )
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if finite.empty:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    y_unit,
                    "skipped",
                    "No finite curve found.",
                )
            )
            continue
        if x_boundary == "lowest":
            value = float(finite["y"].iloc[0])
            reason = "Storage modulus at the lowest finite frequency."
        elif x_boundary == "highest":
            value = float(finite["y"].iloc[-1])
            reason = "Storage modulus at the highest finite frequency."
        else:
            raise ValueError(f"Unsupported frequency boundary mode: {x_boundary}")
        rows.append(
            _metric(
                f"{metric_name}{suffix}",
                value,
                y_unit,
                reason=reason,
            )
        )
    return rows or [
        _metric(metric_name, None, y_unit, "skipped", "No finite curve found.")
    ]


def _peak_y_metrics(
    source_path: Path,
    *,
    metric_name: str,
    y_unit: str,
    magnitude: bool = False,
    x_tokens: tuple[str, ...] = (),
    y_tokens: tuple[str, ...] = (),
    reason: str = "",
) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(
        source_path,
        x_tokens=x_tokens,
        y_tokens=y_tokens,
    )
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = data.replace([np.inf, -np.inf], np.nan).dropna()
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if finite.empty:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    y_unit,
                    "skipped",
                    "No finite curve found.",
                )
            )
            continue
        value = float(finite["y"].abs().max() if magnitude else finite["y"].max())
        rows.append(
            _metric(
                f"{metric_name}{suffix}",
                value,
                y_unit,
                reason=reason,
            )
        )
    return rows or [
        _metric(metric_name, None, y_unit, "skipped", "No finite curve found.")
    ]
