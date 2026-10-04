"""Temperature-resolved diagnostics for empirical horizontal TTS."""

from __future__ import annotations

import math
from copy import deepcopy

from sciplot_core.policy import DEFAULT_PALETTE_COLORS


def supplemental_figures(analysis: dict) -> list[dict]:
    # Local helper imports avoid making the main plan and supplement cyclic.
    from sciplot_core.workflow.rheology_tts_plot_helpers import curve, panel, frequency_panel

    tts = analysis["tts_samples"]
    omega = "Angular frequency, ω (rad s^{-1})"
    reduced = "Reduced frequency, a_{T}ω (rad s^{-1})"
    figures = []

    def page(identifier, panels, columns=3):
        result = []
        for i, item in enumerate(panels):
            copy = deepcopy(item)
            copy["rect_mm"] = [80 * (i % columns), 80 * (i // columns), 80, 80]
            result.append(copy)
        figures.append({"id": identifier, "width_mm": 80 * columns,
                        "height_mm": 80 * math.ceil(len(result) / columns), "panels": result})

    page("SI_01_Complex_viscosity_210C", [frequency_panel(analysis["frequency_samples"], polymer, f"p{i}", viscosity=True)
         for i, polymer in enumerate(("HDPE", "LDPE"))], columns=2)
    unshifted, shifted, shifts, vgp = [], [], [], []
    for i, sample in enumerate(tts):
        raw_curves, master_curves, phase_curves = [], [], []
        for j, (block, master) in enumerate(zip(sample["blocks"], sample["master_curves"], strict=True)):
            color = DEFAULT_PALETTE_COLORS[j % len(DEFAULT_PALETTE_COLORS)]
            temperature = master["nominal_temperature_C"]
            label = f"{temperature:g} °C"
            for metric, style in (("storage_modulus_Pa", "solid"), ("loss_modulus_Pa", "dash")):
                raw_curves.append(curve(label if style == "solid" else "",
                    [p["omega_rad_s"] for p in block["points"]], [p[metric] for p in block["points"]],
                    color, line_style=style, marker="none"))
                master_curves.append(curve(label if style == "solid" else "",
                    [p["omega_reduced_rad_s"] for p in master["points"]], [p[metric] for p in master["points"]],
                    color, line_style="none", marker="circle", marker_size=2.5,
                    marker_fill=color if style == "solid" else "none"))
            phase_curves.append(curve(label,
                [math.hypot(p["storage_modulus_Pa"], p["loss_modulus_Pa"]) for p in block["points"]],
                [math.degrees(math.atan2(p["loss_modulus_Pa"], p["storage_modulus_Pa"])) for p in block["points"]],
                color, marker="none"))
        title = sample["sample_id"]
        unshifted.append(panel(f"p{i}", title, omega, "G′, G″ (Pa)", raw_curves,
            xscale="log", yscale="log", notes=[{"text": "Solid: G′   Dashed: G″", "x": .43, "y": .04}]))
        rms = sample["diagnostics"]["rms_log10_modulus"]
        shifted.append(panel(f"p{i}", title, reduced, "G′, G″ (Pa)", master_curves, xscale="log", yscale="log",
            notes=[{"text": f"Joint RMS: {rms:.3f} dex", "x": .43, "y": .04},
                   {"text": "Filled: G′; open: G″", "x": .43, "y": .09}]))
        vgp.append(panel(f"p{i}", title, "Complex modulus, |G*| (Pa)", "Phase angle, δ (°)", phase_curves,
            xscale="log", y_min=0, y_max=90, legend="lower_left"))
        rows = sample["shifts"]
        x = [1000 / (r["nominal_temperature_C"] + 273.15) for r in rows]
        curves = []
        for key, label, color, marker in (("log10_aT", "Joint G′ + G″", DEFAULT_PALETTE_COLORS[0], "circle"),
             ("G_prime_only_log10_aT", "G′ only", DEFAULT_PALETTE_COLORS[1], "square"),
             ("G_double_prime_only_log10_aT", "G″ only", DEFAULT_PALETTE_COLORS[2], "triangle")):
            curves.append(curve(label, x, [r[key] for r in rows], color, marker=marker, marker_size=3))
        shifts.append(panel(f"p{i}", title, "1000/T (K^{-1})", "log_{10} a_{T}", curves))
    page("SI_02_Original_temperature_sweeps", unshifted)
    page("SI_03_Joint_TTS_both_moduli", shifted)
    page("SI_04_Shift_factor_channel_sensitivity", shifts)
    page("SI_05_Van_Gurp_Palmen", vgp)
    keys = [(None, "Joint, full window"), ("G_prime_only_sensitivity", "G′ only"),
            ("G_double_prime_only_sensitivity", "G″ only"),
            ("common_window_refit_150_210_C", "Joint, 150–210 °C"),
            ("measured_mean_temperature_sensitivity", "Joint, measured T")]
    curves = []
    for index, (key, label) in enumerate(keys):
        values = [(s["arrhenius"] if key is None else s["arrhenius"][key])["Ea_app_kJ_mol"] for s in tts]
        curves.append(curve(label, [1, 2, 3, 4, 5], values, DEFAULT_PALETTE_COLORS[index],
            marker=("circle", "square", "triangle", "diamond", "cross")[index], marker_size=3,
            line_style="none"))
    labels = [("H" if s["polymer"] == "HDPE" else "L") + f'{s["udc_wt_percent"]:g}' for s in tts]
    p = panel("p0", "Activation-energy sensitivity", "Formulation (UDC wt%)", "E_{a,app} (kJ mol^{-1})", curves,
        x_ticks=[1, 2, 3, 4, 5], x_tick_labels=labels, x_min=.3, x_max=5.7, y_min=20, y_max=115)
    diagnostics = [curve("Log-modulus RMS", [1, 2, 3, 4, 5],
        [s["diagnostics"]["rms_log10_modulus"] for s in tts], DEFAULT_PALETTE_COLORS[1], marker="circle", line_style="none"),
        curve("Max. channel shift difference", [1, 2, 3, 4, 5],
        [s["diagnostics"]["max_channel_shift_difference_decades"] for s in tts], DEFAULT_PALETTE_COLORS[2], marker="square", line_style="none")]
    q = panel("p1", "Horizontal-superposition diagnostics", "Formulation (UDC wt%)", "Deviation (decades)", diagnostics,
        x_ticks=[1, 2, 3, 4, 5], x_tick_labels=labels, x_min=.3, x_max=5.7, y_min=0, y_max=.65,
        notes=[{"text": "No strict TTS certification", "x": .03, "y": .04}])
    page("SI_06_Activation_energy_and_TTS_sensitivity", [p, q], columns=2)
    return figures


def separate_supplemental_figures(analysis: dict) -> list[dict]:
    """Independent original and reduced channels; one polymer per native file."""
    from sciplot_core.workflow.rheology_tts_plot_helpers import (
        MODULI, OMEGA, REDUCED, INV_T, curve, panel, independent_figure, sample_stem,
        separate_frequency_panel,
    )

    figures = []
    for polymer in ("HDPE", "LDPE"):
        fs = sorted((s for s in analysis["frequency_samples"] if s["polymer"] == polymer),
                    key=lambda s: s["udc_wt_percent"])
        figures.append(independent_figure(f"SI_Complex_viscosity_{polymer}_210C",
            separate_frequency_panel(fs, polymer, "complex_viscosity_Pa_s", "η*"),
            polymer, "complex_viscosity_Pa_s", "original_210C_acquisition"))
    for sample in analysis["tts_samples"]:
        polymer, stem, title = sample["polymer"], sample_stem(sample), sample["sample_id"]
        for metric_name, raw_metric, reduced_metric, symbol in MODULI:
            original, reduced = [], []
            for index, (block, master) in enumerate(zip(sample["blocks"], sample["master_curves"], strict=True)):
                color = DEFAULT_PALETTE_COLORS[index % len(DEFAULT_PALETTE_COLORS)]
                label = f'{master["temperature_C"]:.1f} °C'
                original.append(curve(label, [p["omega_rad_s"] for p in block["points"]],
                    [p[raw_metric] for p in block["points"]], color))
                reduced.append(curve(label, [p["omega_reduced_rad_s"] for p in master["points"]],
                    [p[reduced_metric] for p in master["points"]], color))
            for kind, curves, xaxis, ylabel, quantity, basis in (
                ("Original", original, OMEGA, f"{symbol} (Pa)", raw_metric, "original_temperature_acquisition"),
                ("TTS", reduced, REDUCED, f"{symbol}_{{red}} (Pa)", reduced_metric, "temperature_reduced_master_coordinates"),
            ):
                item = panel("graph1", f'{title}: {"raw" if kind == "Original" else "reduced"} {symbol}',
                             xaxis, ylabel, curves, xscale="log", yscale="log", legend="lower_right")
                figures.append(independent_figure(f"SI_{kind}_{stem}_{metric_name}", item, polymer, quantity, basis))
        phase = []
        for index, block in enumerate(sample["blocks"]):
            phase.append(curve(f'{block["actual_temperature_C"]["mean"]:.1f} °C',
                [math.hypot(p["storage_modulus_Pa"], p["loss_modulus_Pa"]) for p in block["points"]],
                [math.degrees(math.atan2(p["loss_modulus_Pa"], p["storage_modulus_Pa"])) for p in block["points"]],
                DEFAULT_PALETTE_COLORS[index % len(DEFAULT_PALETTE_COLORS)]))
        legend = "upper_left" if max(value for entry in phase for value in entry["y"]) < 50 else "lower_left"
        item = panel("graph1", f"{title}: phase angle", "Complex modulus, |G*| (Pa)",
                     "Phase angle, δ (°)", phase, xscale="log", y_min=0, y_max=90,
                     y_ticks=[0, 30, 60, 90], legend=legend)
        figures.append(independent_figure(f"SI_Van_Gurp_Palmen_{stem}", item, polymer,
                       "phase_angle_degrees", "original_temperature_acquisition"))
        rows = sample["shifts"]
        x = [1000 / (r["temperature_C"] + 273.15) for r in rows]
        curves = []
        for index, (key, label) in enumerate((
            ("log10_aT", "Joint fit"), ("G_prime_only_log10_aT", "G′ fit"),
            ("G_double_prime_only_log10_aT", "G″ fit"),
        )):
            curves.append(curve(label, x, [r[key] for r in rows], DEFAULT_PALETTE_COLORS[index]))
        item = panel("graph1", f"{title}: shift factors", INV_T, "log_{10} a_{T}", curves)
        figures.append(independent_figure(f"SI_Shift_channels_{stem}", item, polymer,
                       "log10_aT", "corrected_joint_and_channel_specific_shifts"))
    for polymer in ("HDPE", "LDPE"):
        samples = sorted((s for s in analysis["tts_samples"] if s["polymer"] == polymer),
                         key=lambda s: s["udc_wt_percent"])
        figures.extend(_separate_polymer_diagnostics(samples, polymer))
    return figures


def _separate_polymer_diagnostics(samples: list[dict], polymer: str) -> list[dict]:
    from sciplot_core.workflow.rheology_tts_plot_helpers import curve, panel, independent_figure

    amounts = [s["udc_wt_percent"] for s in samples]
    keys = [(None, "Joint fit"), ("G_prime_only_sensitivity", "G′ fit"),
            ("G_double_prime_only_sensitivity", "G″ fit"),
            ("common_window_refit_150_210_C", "Joint, 150–210 °C"),
            ("nominal_temperature_sensitivity", "Joint, nominal T"),
            ("legacy", "Uncorrected, nominal T")]
    curves = []
    for index, (key, label) in enumerate(keys):
        values = [(s["legacy_comparison"]["arrhenius"] if key == "legacy" else
                   s["arrhenius"] if key is None else s["arrhenius"][key])["Ea_app_kJ_mol"] for s in samples]
        curves.append(curve(label, amounts, values, DEFAULT_PALETTE_COLORS[index]))
    ymax = math.ceil(max(value for entry in curves for value in entry["y"]) * 1.8 / 20) * 20
    item = panel("graph1", f"{polymer}: E_{{a}} sensitivity", "UDC content (wt%)", "E_{a,app} (kJ mol^{-1})",
        curves, x_ticks=amounts, x_min=min(amounts) - .6, x_max=max(amounts) + .6,
        y_min=0, y_max=ymax, y_ticks=list(range(0, int(ymax) + 1, 40)))
    energy = independent_figure(f"SI_Ea_sensitivity_{polymer}", item, polymer, "Ea_app_kJ_mol",
                               "explicit_corrected_and_legacy_sensitivity_fits", wide=True)
    curves = []
    for index, (key, label) in enumerate((
        ("rms_log10_modulus", "Log-modulus RMS"),
        ("max_channel_shift_difference_decades", "Max. channel shift difference"),
    )):
        curves.append(curve(label, amounts, [s["diagnostics"][key] for s in samples],
                            DEFAULT_PALETTE_COLORS[index + 1]))
    ymax = math.ceil(max(value for entry in curves for value in entry["y"]) * 1.45 * 10) / 10 or .1
    tick_step = .1 if ymax <= .3 else .2 if ymax <= 1 else .5
    item = panel("graph1", f"{polymer}: TTS diagnostics", "UDC content (wt%)", "Deviation (decades)",
        curves, x_ticks=amounts, x_min=min(amounts) - .6, x_max=max(amounts) + .6,
        y_min=0, y_max=ymax, y_ticks=[round(i * tick_step, 2) for i in range(int(ymax / tick_step) + 1)])
    diagnostics = independent_figure(f"SI_TTS_diagnostics_{polymer}", item, polymer, "deviation_decades",
                                    "corrected_joint_TTS_diagnostics", wide=True)
    return [energy, diagnostics]
