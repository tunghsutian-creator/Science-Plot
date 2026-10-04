"""Measured-temperature TTS with explicit constant-density modulus reduction."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from sciplot_core.semantic_sources.rheology_tts_fitting import (
    _fit_shifts,
    _normalize_postfit,
    _regression,
)

_REDUCED_KEYS = ("storage_modulus_reduced_Pa", "loss_modulus_reduced_Pa")
LEGACY_OPTIONS = {
    "temperature_basis": "nominal",
    "modulus_correction": "none",
    "reference_normalization": "reciprocal_temperature_interpolation",
}
CORRECTED_OPTIONS = {
    "temperature_basis": "measured_mean",
    "modulus_correction": "Tref_over_T",
    "reference_normalization": "arrhenius_postfit",
}


def resolved_analysis_options(request: dict[str, Any]) -> dict[str, str]:
    supplied = request.get("analysis_options")
    if supplied is None:
        return dict(LEGACY_OPTIONS)
    if not isinstance(supplied, dict) or supplied not in (
        LEGACY_OPTIONS,
        CORRECTED_OPTIONS,
    ):
        raise ValueError(
            "analysis_options must specify either the complete legacy nominal/no-correction/interpolation method or measured_mean/Tref_over_T/arrhenius_postfit method."
        )
    return dict(supplied)


def _correct_blocks(
    blocks: list[dict[str, Any]], reference: float
) -> list[dict[str, Any]]:
    if len(blocks) < 3 or any(b["point_count"] < 3 for b in blocks):
        raise ValueError(
            "TTS requires at least three temperatures and three points per selected interval."
        )
    if any(
        b["nominal_temperature_C"] is None or b["actual_temperature_C"] is None
        for b in blocks
    ):
        raise ValueError(
            "Corrected TTS requires explicit nominal labels and measured Celsius temperatures."
        )
    if len({b["nominal_temperature_C"] for b in blocks}) != len(blocks):
        raise ValueError(
            "Duplicate selected nominal temperatures require an explicit replicate policy."
        )
    corrected = []
    for block in sorted(
        blocks, key=lambda b: b["actual_temperature_C"]["mean"], reverse=True
    ):
        points = []
        for point in block["points"]:
            temperature = point["temperature_C"]
            if not math.isfinite(temperature) or temperature <= -273.15:
                raise ValueError(
                    "Measured temperatures must be finite and above absolute zero."
                )
            factor = (reference + 273.15) / (temperature + 273.15)
            points.append(
                dict(
                    point,
                    modulus_correction_factor=factor,
                    storage_modulus_reduced_Pa=point["storage_modulus_Pa"] * factor,
                    loss_modulus_reduced_Pa=point["loss_modulus_Pa"] * factor,
                )
            )
        corrected.append(
            dict(
                block,
                points=points,
                temperature_C=block["actual_temperature_C"]["mean"],
            )
        )
    if len({b["temperature_C"] for b in corrected}) != len(corrected):
        raise ValueError(
            "Measured sweep mean temperatures must be distinct for Arrhenius regression."
        )
    return corrected


def _window_sensitivity(
    blocks: list[dict[str, Any]], temperatures: np.ndarray, logs: np.ndarray
) -> dict[str, Any]:
    select = (temperatures >= 150) & (temperatures <= 210)
    if sum(select) < 3:
        return {
            "available": False,
            "reason": "Fewer than three measured sweep mean temperatures in 150-210 C.",
        }
    restricted = [block for block, keep in zip(blocks, select, strict=True) if keep]
    fit = _fit_shifts(restricted, 0, (0, 1), _REDUCED_KEYS)
    result = _regression(temperatures[select], np.asarray(fit["log10_shifts"]))
    result.update(
        temperature_basis="measured_mean",
        modulus_correction="Tref_over_T",
        shift_basis="Independent corrected-modulus TTS refit using only measured sweep mean temperatures in 150-210 C; arbitrary shift origin does not affect Ea.",
    )
    return result


def analyze_corrected_sample(
    selection: dict[str, Any],
    blocks: list[dict[str, Any]],
    reference: float,
    legacy: dict[str, Any],
) -> dict[str, Any]:
    corrected = _correct_blocks(blocks, reference)
    temperatures = np.array([b["temperature_C"] for b in corrected])
    nominal = np.array([b["nominal_temperature_C"] for b in corrected])
    anchor = int(np.argmin(abs(temperatures - reference)))
    fit = _fit_shifts(corrected, anchor, (0, 1), _REDUCED_KEYS)
    gp_fit = _fit_shifts(corrected, anchor, (0,), _REDUCED_KEYS)
    gpp_fit = _fit_shifts(corrected, anchor, (1,), _REDUCED_KEYS)
    logs, offset = _normalize_postfit(temperatures, fit["log10_shifts"], reference)
    gp_logs, gp_offset = _normalize_postfit(
        temperatures, gp_fit["log10_shifts"], reference
    )
    gpp_logs, gpp_offset = _normalize_postfit(
        temperatures, gpp_fit["log10_shifts"], reference
    )
    regression = _regression(temperatures, logs)
    regression.update(
        temperature_basis="measured_mean", modulus_correction="Tref_over_T"
    )
    regression["nominal_temperature_sensitivity"] = _regression(nominal, logs)
    regression["G_prime_only_sensitivity"] = _regression(temperatures, gp_logs)
    regression["G_double_prime_only_sensitivity"] = _regression(temperatures, gpp_logs)
    common = (temperatures >= 150) & (temperatures <= 210)
    regression["common_actual_window_150_210_C"] = (
        _regression(temperatures[common], logs[common])
        if sum(common) >= 3
        else {
            "available": False,
            "reason": "Fewer than three measured mean temperatures in 150-210 C.",
        }
    )
    regression["common_actual_window_150_210_C"]["shift_basis"] = (
        "Subset of corrected shifts fitted across the full temperature range."
    )
    regression["common_window_refit_150_210_C"] = _window_sensitivity(
        corrected, temperatures, logs
    )
    shifts = []
    master = []
    for index, (block, temperature, value, gp, gpp) in enumerate(
        zip(corrected, temperatures, logs, gp_logs, gpp_logs, strict=True)
    ):
        original_shift = fit["log10_shifts"][index]
        shifts.append(
            {
                "temperature_C": float(temperature),
                "nominal_temperature_C": block["nominal_temperature_C"],
                "actual_temperature_C": block["actual_temperature_C"],
                "log10_aT": float(value),
                "ln_aT": float(value * np.log(10)),
                "aT": float(10**value),
                "independent_log10_shift": original_shift,
                "independent_ln_shift": float(original_shift * np.log(10)),
                "G_prime_only_log10_aT": float(gp),
                "G_double_prime_only_log10_aT": float(gpp),
                "channel_shift_difference_decades": float(gp - gpp),
            }
        )
        master.append(
            {
                "temperature_C": float(temperature),
                "nominal_temperature_C": block["nominal_temperature_C"],
                "aT": float(10**value),
                "source": block["source"],
                "test": block["test"],
                "result": block["result"],
                "points": [
                    dict(
                        point,
                        omega_reduced_rad_s=point["omega_rad_s"] * float(10**value),
                    )
                    for point in block["points"]
                ],
            }
        )
    # Residual pairs retain nominal identifiers and explicitly add actual means.
    actual_by_nominal = dict(zip(nominal, temperatures, strict=True))
    pairs = [
        dict(
            pair,
            actual_mean_temperature_i_C=float(
                actual_by_nominal[pair["temperature_i_C"]]
            ),
            actual_mean_temperature_j_C=float(
                actual_by_nominal[pair["temperature_j_C"]]
            ),
        )
        for pair in fit["pair_diagnostics"]
    ]
    legacy_summary = {
        "temperature_basis": "nominal",
        "modulus_correction": "none",
        "reference_normalization": "reciprocal_temperature_interpolation",
        "arrhenius": legacy["arrhenius"],
        "diagnostics": legacy["diagnostics"],
        "shifts": legacy["shifts"],
        "reference": legacy["reference"],
    }
    return {
        "sample_id": selection["sample_id"],
        "polymer": selection["polymer"],
        "udc_wt_percent": selection["udc_wt_percent"],
        "source": selection["tts_source"],
        "selected_test": selection["tts_test"],
        "blocks": corrected,
        "reference": {
            "temperature_C": reference,
            "nominal_temperature_C": reference,
            "normalization": "arrhenius_postfit",
            "measured_reference_available": bool(np.any(temperatures == reference)),
            "measured_nominal_reference_available": bool(reference in nominal),
            "extrapolated_reference": bool(
                reference < min(temperatures) or reference > max(temperatures)
            ),
            "actual_mean_temperature_range_C": [
                float(min(temperatures)),
                float(max(temperatures)),
            ],
            "numerical_anchor_temperature_C": float(temperatures[anchor]),
            "numerical_anchor_nominal_temperature_C": float(nominal[anchor]),
            "removed_log10_shift_offset": offset,
            "G_prime_only_removed_log10_shift_offset": gp_offset,
            "G_double_prime_only_removed_log10_shift_offset": gpp_offset,
            "convention": "Independent shifts are fitted first; subsequent free-intercept Arrhenius prediction at Tref sets their common origin. This does not impose an Arrhenius slope during TTS fitting or claim a measurement at Tref.",
        },
        "modulus_reduction": {
            "formula": "G_reduced = G_measured * Tref_K / Tpoint_K",
            "temperature_basis": "original per-point measured Celsius temperature converted to Kelvin",
            "density_assumption": "rho(Tref)/rho(T) = 1 because no density measurements are supplied; this is an explicit constant-density approximation.",
            "fitted_vertical_shifts": False,
        },
        "shifts": shifts,
        "master_curves": master,
        "arrhenius": regression,
        "legacy_comparison": legacy_summary,
        "diagnostics": {
            "rms_log10_modulus": fit["rms_log10_modulus"],
            "pair_diagnostics": pairs,
            "max_channel_shift_difference_decades": float(
                np.max(abs(gp_logs - gpp_logs))
            ),
            "strict_TTS_certified": False,
            "spectrum_inversion_performed": False,
            "point_rows_excluded": [],
            "modulus_basis": "temperature_reduced",
        },
    }


def corrected_method_fields() -> dict[str, Any]:
    return {
        "temperature_basis": "Measured sweep mean temperatures for Arrhenius and reference normalization; original per-point temperatures for modulus correction.",
        "analysis_options": dict(CORRECTED_OPTIONS),
        "vertical_shifts": False,
        "fitted_vertical_shifts": False,
        "modulus_correction": {
            "formula": "G_reduced = G_measured * Tref_K / Tpoint_K",
            "factor_field": "modulus_correction_factor",
            "density_ratio_assumed": 1.0,
            "density_assumption": "Constant density; no density data were supplied. No additional empirical vertical shift is fitted.",
        },
        "master_data": "Every selected raw acquisition point and original modulus retained; reduced modulus fields multiply each raw modulus by its recorded per-point Tref_K/Tpoint_K factor, and reduced frequency is omega*aT.",
        "reference_normalization": "Independently fitted shifts followed by free-intercept OLS; subtract predicted ln(aT) at 210 C. Reference extrapolation outside measured sweep means is explicitly flagged per sample.",
        "arrhenius": "After unconstrained overlap fitting, OLS ln(aT) = slope*(1000/Tmean_K)+intercept. A common postfit shift-origin change sets the predicted ln(aT) at Tref to zero without changing slope or residuals. Ea_app [kJ/mol] = R*slope.",
        "interpolation": "Log-modulus interpolation is confined to measured-frequency overlap; no modulus/frequency extrapolation. Only the subsequent Arrhenius reference convention may extrapolate temperature, with explicit flags.",
    }
