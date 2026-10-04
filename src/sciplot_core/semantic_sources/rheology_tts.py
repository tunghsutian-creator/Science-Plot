"""Source-bound, horizontal-only rheological time-temperature superposition.

This analysis owner preserves every selected acquisition point. Interpolation is
confined to the overlap objective; delivered master coordinates remain shifted
original frequencies. It neither certifies thermorheological simplicity nor
identifies a molecular bond-exchange activation energy.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from sciplot_core.semantic_sources.rheology_tts_source import read_tts_blocks
from sciplot_core.semantic_sources.rheology_tts_corrected import (
    CORRECTED_OPTIONS,
    analyze_corrected_sample,
    corrected_method_fields,
    resolved_analysis_options,
)
from sciplot_core.semantic_sources.rheology_tts_fitting import (
    _GRID_POINTS,
    _MIN_OVERLAP_DECADES,
    _fit_shifts,
    _normalize,
    _regression,
)


def _analyze_sample(
    selection: dict[str, Any], blocks: list[dict[str, Any]], reference: float
) -> dict[str, Any]:
    if len(blocks) < 3 or any(b["point_count"] < 3 for b in blocks):
        raise ValueError(
            "TTS requires at least three temperatures and three points per selected interval."
        )
    if any(
        b["nominal_temperature_C"] is None or b["actual_temperature_C"] is None
        for b in blocks
    ):
        raise ValueError(
            "TTS requires explicit FS temperature labels and measured Celsius temperature columns."
        )
    blocks = sorted(blocks, key=lambda b: b["nominal_temperature_C"], reverse=True)
    temps = np.array([b["nominal_temperature_C"] for b in blocks])
    if any(t <= -273.15 for t in temps) or any(
        b["actual_temperature_C"]["min"] <= -273.15 for b in blocks
    ):
        raise ValueError("Original TTS temperatures must be above absolute zero.")
    if len(set(temps)) != len(temps):
        raise ValueError(
            "Duplicate selected nominal temperatures require an explicit replicate policy; none was assumed."
        )
    anchor = int(np.argmin(abs(temps - reference)))
    fit = _fit_shifts(blocks, anchor, (0, 1))
    gp_fit = _fit_shifts(blocks, anchor, (0,))
    gpp_fit = _fit_shifts(blocks, anchor, (1,))
    logs, offset = _normalize(temps, fit["log10_shifts"], reference)
    gp_logs, _ = _normalize(temps, gp_fit["log10_shifts"], reference)
    gpp_logs, _ = _normalize(temps, gpp_fit["log10_shifts"], reference)
    regression = _regression(temps, logs)
    actual = np.array([b["actual_temperature_C"]["mean"] for b in blocks])
    regression["measured_mean_temperature_sensitivity"] = _regression(actual, logs)
    regression["G_prime_only_sensitivity"] = _regression(temps, gp_logs)
    regression["G_double_prime_only_sensitivity"] = _regression(temps, gpp_logs)
    common = (temps >= 150) & (temps <= 210)
    regression["common_nominal_window_150_210_C"] = (
        _regression(temps[common], logs[common])
        if sum(common) >= 3
        else {
            "available": False,
            "reason": "Fewer than three nominal temperatures in the 150-210 C window.",
        }
    )
    regression["common_nominal_window_150_210_C"]["shift_basis"] = (
        "Subset of shifts fitted over the complete selected temperature range."
    )
    if sum(common) >= 3:
        restricted_blocks = [
            block for block, selected in zip(blocks, common, strict=True) if selected
        ]
        restricted = _fit_shifts(restricted_blocks, 0, (0, 1))
        regression["common_window_refit_150_210_C"] = _regression(
            temps[common], np.asarray(restricted["log10_shifts"])
        )
        regression["common_window_refit_150_210_C"]["shift_basis"] = (
            "Horizontal shifts independently refitted using only nominal temperatures in 150-210 C; shift origin does not affect Ea."
        )
    shifts = [
        {
            "nominal_temperature_C": float(t),
            "actual_temperature_C": b["actual_temperature_C"],
            "log10_aT": float(s),
            "ln_aT": float(s * np.log(10)),
            "aT": float(10**s),
            "G_prime_only_log10_aT": float(sp),
            "G_double_prime_only_log10_aT": float(spp),
            "channel_shift_difference_decades": float(sp - spp),
        }
        for t, b, s, sp, spp in zip(temps, blocks, logs, gp_logs, gpp_logs, strict=True)
    ]
    master = [
        {
            "nominal_temperature_C": float(t),
            "aT": float(10**s),
            "source": b["source"],
            "test": b["test"],
            "result": b["result"],
            "points": [
                dict(p, omega_reduced_rad_s=p["omega_rad_s"] * float(10**s))
                for p in b["points"]
            ],
        }
        for t, b, s in zip(temps, blocks, logs, strict=True)
    ]
    return {
        "sample_id": selection["sample_id"],
        "polymer": selection["polymer"],
        "udc_wt_percent": selection["udc_wt_percent"],
        "source": selection["tts_source"],
        "selected_test": selection["tts_test"],
        "blocks": blocks,
        "reference": {
            "nominal_temperature_C": reference,
            "measured_nominal_reference_available": bool(reference in temps),
            "normalization": "measured_nominal_reference"
            if reference in temps
            else "linear_interpolation_of_log_aT_in_reciprocal_nominal_temperature",
            "numerical_anchor_temperature_C": float(temps[anchor]),
            "removed_log10_shift_offset": offset,
        },
        "shifts": shifts,
        "master_curves": master,
        "arrhenius": regression,
        "diagnostics": {
            "rms_log10_modulus": fit["rms_log10_modulus"],
            "pair_diagnostics": fit["pair_diagnostics"],
            "max_channel_shift_difference_decades": float(
                np.max(abs(gp_logs - gpp_logs))
            ),
            "strict_TTS_certified": False,
            "spectrum_inversion_performed": False,
        },
    }


def analyze_tts_request(request: dict[str, Any]) -> dict[str, Any]:
    """Analyze explicitly named original sweeps; return JSON-safe provenance/data.

    Required request: version=1, reference_temperature_C, frequency_source,
    frequency_temperature_C, samples. Each sample selects sample_id/polymer/
    udc_wt_percent/frequency_test and optionally tts_source + tts_test. A filename
    never overrides a Test header; aliases are an explicit request declaration.
    """
    if request.get("version") != 1:
        raise ValueError("TTS request version must be 1.")
    options = resolved_analysis_options(request)
    corrected_method = options == CORRECTED_OPTIONS
    reference = float(request["reference_temperature_C"])
    frequency_temp = float(request["frequency_temperature_C"])
    if not all(math.isfinite(t) and t > -273.15 for t in (reference, frequency_temp)):
        raise ValueError("Temperatures must be finite and above absolute zero.")
    selections = request["samples"]
    if not selections or len({s["sample_id"] for s in selections}) != len(selections):
        raise ValueError("TTS sample IDs must be nonempty and unique.")
    if len({s["frequency_test"] for s in selections}) != len(selections):
        raise ValueError(
            "One original frequency Test cannot represent multiple sample identities."
        )
    paths = [str(Path(request["frequency_source"]).expanduser().resolve())]
    paths += [
        str(Path(s["tts_source"]).expanduser().resolve())
        for s in selections
        if "tts_source" in s
    ]
    sources = {p: read_tts_blocks(p) for p in dict.fromkeys(paths)}
    frequency_source = sources[paths[0]]
    frequency_samples = []
    tts_samples = []
    selected_keys: set[tuple[str, int]] = set()
    for selection in selections:
        amount = float(selection["udc_wt_percent"])
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("UDC content must be finite and nonnegative.")
        fs = [
            b
            for b in frequency_source["blocks"]
            if b["test"] == selection["frequency_test"]
        ]
        if len(fs) != 1:
            raise ValueError(
                f"Frequency Test {selection['frequency_test']!r} must identify exactly one original interval."
            )
        block = fs[0]
        selected_keys.add((block["source"], block["header_row"]))
        target = [
            p
            for p in block["points"]
            if math.isclose(p["omega_rad_s"], 0.1, rel_tol=1e-12, abs_tol=0)
        ]
        frequency_samples.append(
            {
                "sample_id": selection["sample_id"],
                "polymer": selection["polymer"],
                "udc_wt_percent": amount,
                "temperature_C": frequency_temp,
                "temperature_evidence": "explicit_request",
                "block": block,
                "at_0_1_rad_s": target[0] if len(target) == 1 else None,
            }
        )
        if "tts_source" in selection:
            path = str(Path(selection["tts_source"]).expanduser().resolve())
            bs = [
                b for b in sources[path]["blocks"] if b["test"] == selection["tts_test"]
            ]
            for b in bs:
                selected_keys.add((b["source"], b["header_row"]))
            legacy = _analyze_sample(selection, bs, reference)
            tts_samples.append(
                analyze_corrected_sample(selection, bs, reference, legacy)
                if corrected_method
                else legacy
            )
    excluded = [
        {
            "source": b["source"],
            "test": b["test"],
            "result": b["result"],
            "header_row": b["header_row"],
            "point_count": b["point_count"],
            "reason": "Original Test/interval is outside the explicit requested sample selection; source bytes retained.",
        }
        for source in sources.values()
        for b in source["blocks"]
        if (b["source"], b["header_row"]) not in selected_keys
    ]
    if corrected_method:
        original_blocks = {
            (b["source"], b["header_row"]): b
            for source in sources.values()
            for b in source["blocks"]
        }
        for entry in excluded:
            block = original_blocks[(entry["source"], entry["header_row"])]
            entry.update(
                data_start_row=block["data_start_row"],
                data_end_row=block["data_end_row"],
                source_rows=[p["source_row"] for p in block["points"]],
                nominal_temperature_C=block["nominal_temperature_C"],
                actual_temperature_C=block["actual_temperature_C"],
            )
    # Rehash after all numerical work to keep analysis bound to current originals.
    for path, source in sources.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Source changed during TTS analysis: {path}")
    result = {
        "version": 1,
        "analysis_kind": "horizontal_only_rheology_tts",
        "sources": [
            {k: v for k, v in s.items() if k != "blocks"} for s in sources.values()
        ],
        "frequency_samples": frequency_samples,
        "tts_samples": tts_samples,
        "excluded_blocks": excluded,
        "method": {
            "shift_convention": "omega_reduced = omega * aT",
            "reference_temperature_C": reference,
            "temperature_basis": "nominal Result label; measured mean sensitivity reported separately",
            "vertical_shifts": False,
            "objective": "Equal weight per unordered temperature pair and per G_prime/G_double_prime channel; mean squared log10 modulus residual on overlapping log-frequency grids.",
            "overlap_grid_points": _GRID_POINTS,
            "minimum_overlap_decades": _MIN_OVERLAP_DECADES,
            "interpolation": "Piecewise linear in log10(omega), log10(G), confined to pair overlap; no extrapolation.",
            "optimizer": "Deterministic bounded pairwise initialization then global Nelder-Mead; xatol=1e-10, fatol=1e-12.",
            "master_data": "Every selected original point, in original acquisition order; frequencies only multiplied by fitted aT.",
            "arrhenius": "OLS ln(aT) = slope * (1000/T_K) + intercept; Ea_app [kJ/mol] = R * slope; intercept free.",
            "uncertainty": "OLS slope standard error describes fit only; no replicate, measurement or specimen uncertainty is estimated.",
            "complex_viscosity": "hypot(G_prime,G_double_prime)/omega in Pa s; Im(Complex Viscosity) is never substituted.",
            "point_exclusions": "None within explicitly selected intervals.",
            "spectrum_inversion": "Not performed; joint-channel TTS assumptions require independent validation.",
        },
        "warnings": [
            "A visually shifted curve and a high Arrhenius R_squared do not establish strict TTS.",
            "Apparent overall rheological activation energies are not intrinsic bond-exchange activation energies.",
            "Frequency-source 210 C scans remain separate from nominal 210 C TTS acquisitions.",
            "Original torque, strain and status fields are retained without instrument-specific validity exclusions.",
            "Full-range Ea comparisons span different temperature intervals; common-window and measured-temperature sensitivities are included.",
        ],
    }
    if corrected_method:
        result["analysis_kind"] = "temperature_reduced_rheology_tts"
        result["method"].update(corrected_method_fields())
        result["warnings"].extend(
            [
                "The Tref_K/Tpoint_K modulus correction assumes constant density; no density correction was measured.",
                "A postfit Arrhenius reference convention is not a measured 210 C sweep. Extrapolated references are flagged per sample.",
            ]
        )
    return result


__all__ = ["analyze_tts_request", "read_tts_blocks"]
