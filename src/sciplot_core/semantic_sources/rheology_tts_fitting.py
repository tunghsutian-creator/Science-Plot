"""Deterministic horizontal TTS overlap fitting and Arrhenius diagnostics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import linregress

_R = 8.31446261815324
_GRID_POINTS = 151
_MIN_OVERLAP_DECADES = 0.5


def _xy(
    block: dict[str, Any],
    modulus_keys: tuple[str, str] = ("storage_modulus_Pa", "loss_modulus_Pa"),
) -> tuple[np.ndarray, np.ndarray]:
    points = block["points"]
    order = np.argsort([p["omega_rad_s"] for p in points])
    x = np.log10([points[i]["omega_rad_s"] for i in order])
    y = np.log10(
        [[points[i][modulus_keys[0]], points[i][modulus_keys[1]]] for i in order]
    )
    return x, y


def _pair_residual(
    first: tuple[np.ndarray, np.ndarray],
    second: tuple[np.ndarray, np.ndarray],
    shift: float,
    channels: tuple[int, ...],
) -> tuple[np.ndarray, float]:
    x1, y1 = first
    x2, y2 = second
    x2 = x2 + shift
    lo, hi = max(x1[0], x2[0]), min(x1[-1], x2[-1])
    overlap = float(hi - lo)
    if overlap < _MIN_OVERLAP_DECADES:
        return np.full(
            (_GRID_POINTS, len(channels)), 1000.0 + _MIN_OVERLAP_DECADES - overlap
        ), overlap
    grid = np.linspace(lo, hi, _GRID_POINTS)
    residual = np.column_stack(
        [
            np.interp(grid, x2, y2[:, c]) - np.interp(grid, x1, y1[:, c])
            for c in channels
        ]
    )
    return residual, overlap


def _fit_shifts(
    blocks: list[dict[str, Any]],
    anchor: int,
    channels: tuple[int, ...],
    modulus_keys: tuple[str, str] = ("storage_modulus_Pa", "loss_modulus_Pa"),
) -> dict[str, Any]:
    data = [_xy(block, modulus_keys) for block in blocks]
    n = len(data)
    indices = [i for i in range(n) if i != anchor]
    initial = np.zeros(n)
    for i in indices:
        x1, _ = data[anchor]
        x2, _ = data[i]
        bounds = (
            float(x1[0] - x2[-1] + _MIN_OVERLAP_DECADES),
            float(x1[-1] - x2[0] - _MIN_OVERLAP_DECADES),
        )
        if bounds[0] >= bounds[1]:
            raise ValueError(
                "Frequency sweeps have insufficient range for TTS overlap fitting."
            )

        def objective(shift: float, selected_index: int = i) -> float:
            return float(
                np.mean(
                    _pair_residual(data[anchor], data[selected_index], shift, channels)[
                        0
                    ]
                    ** 2
                )
            )

        grid = np.linspace(*bounds, 201)
        best = int(np.argmin([objective(float(v)) for v in grid]))
        result = minimize_scalar(
            objective,
            bounds=(grid[max(best - 1, 0)], grid[min(best + 1, len(grid) - 1)]),
            method="bounded",
            options={"xatol": 1e-11},
        )
        initial[i] = result.x

    def expand(values: np.ndarray) -> np.ndarray:
        shifts = np.zeros(n)
        shifts[indices] = values
        return shifts

    def loss(values: np.ndarray) -> float:
        shifts = expand(values)
        return float(
            np.mean(
                [
                    np.mean(
                        _pair_residual(
                            data[i], data[j], shifts[j] - shifts[i], channels
                        )[0]
                        ** 2
                    )
                    for i in range(n)
                    for j in range(i + 1, n)
                ]
            )
        )

    optimization = minimize(
        loss,
        initial[indices],
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-12, "maxiter": 10000},
    )
    if not optimization.success:
        raise ValueError(f"TTS optimization failed: {optimization.message}")
    shifts = expand(optimization.x)
    diagnostics = []
    for i in range(n):
        for j in range(i + 1, n):
            residual, overlap = _pair_residual(
                data[i], data[j], shifts[j] - shifts[i], channels
            )
            if overlap < _MIN_OVERLAP_DECADES:
                raise ValueError(
                    "TTS optimum has insufficient overlap; no extrapolation performed."
                )
            diagnostics.append(
                {
                    "temperature_i_C": blocks[i]["nominal_temperature_C"],
                    "temperature_j_C": blocks[j]["nominal_temperature_C"],
                    "overlap_decades": overlap,
                    "rms_log10_modulus": float(np.sqrt(np.mean(residual**2))),
                    "per_channel_rms_log10_modulus": {
                        ("G_prime" if c == 0 else "G_double_prime"): float(
                            np.sqrt(np.mean(residual[:, k] ** 2))
                        )
                        for k, c in enumerate(channels)
                    },
                }
            )
    return {
        "log10_shifts": shifts.tolist(),
        "rms_log10_modulus": float(np.sqrt(optimization.fun)),
        "pair_diagnostics": diagnostics,
    }


def _normalize_postfit(
    temperatures: np.ndarray, shifts: list[float], reference: float
) -> tuple[np.ndarray, float]:
    """Set the arbitrary horizontal origin after unconstrained shift fitting."""
    regression = _regression(temperatures, np.asarray(shifts))
    predicted_ln = regression["intercept"] + regression[
        "slope_ln_aT_per_1000_over_K"
    ] * 1000.0 / (reference + 273.15)
    offset = float(predicted_ln / np.log(10.0))
    return np.asarray(shifts) - offset, offset


def _normalize(
    temperatures: np.ndarray, shifts: list[float], reference: float
) -> tuple[np.ndarray, float]:
    reciprocal = 1.0 / (temperatures + 273.15)
    target = 1.0 / (reference + 273.15)
    if not min(reciprocal) <= target <= max(reciprocal):
        raise ValueError(
            "Reference temperature must lie inside the measured nominal temperature range; no extrapolation is allowed."
        )
    order = np.argsort(reciprocal)
    offset = float(np.interp(target, reciprocal[order], np.asarray(shifts)[order]))
    return np.asarray(shifts) - offset, offset


def _regression(temperatures: np.ndarray, logs: np.ndarray) -> dict[str, Any]:
    if len(temperatures) < 3 or len(set(temperatures)) != len(temperatures):
        raise ValueError(
            "Arrhenius regression needs at least three distinct temperatures."
        )
    x = 1000.0 / (temperatures + 273.15)
    y = logs * np.log(10.0)
    fitted = linregress(x, y)
    predicted = fitted.intercept + fitted.slope * x
    return {
        "n_temperatures": len(temperatures),
        "Ea_app_kJ_mol": float(fitted.slope * _R),
        "Ea_fit_standard_error_kJ_mol": float(fitted.stderr * _R)
        if math.isfinite(fitted.stderr)
        else None,
        "slope_ln_aT_per_1000_over_K": float(fitted.slope),
        "intercept": float(fitted.intercept),
        "R_squared": float(fitted.rvalue**2) if math.isfinite(fitted.rvalue) else None,
        "rows": [
            {
                "temperature_C": float(t),
                "inverse_temperature_1000_K": float(xx),
                "ln_aT": float(yy),
                "ln_aT_fit": float(pred),
                "residual_ln_aT": float(yy - pred),
            }
            for t, xx, yy, pred in zip(temperatures, x, y, predicted, strict=True)
        ],
    }
