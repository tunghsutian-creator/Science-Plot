"""Figure plans derived only from the source-bound TTS analysis payload."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sciplot_core.rheology_tts_style import upgrade_tts_presentation
from sciplot_core.workflow.rheology_tts_tables import write_csv

from sciplot_core.workflow.rheology_tts_plot_helpers import (
    COLORS, _color, curve, panel, frequency_panel, master_panel, arrhenius_panel,
)


def build_tts_figures(analysis: dict, layout: str = "legacy") -> dict:
    fs, tts = analysis["frequency_samples"], analysis["tts_samples"]
    expected_fs = {(p, w) for p in ("HDPE", "LDPE") for w in (0, 2, 4, 6)}
    expected_tts = {("HDPE", 0), ("HDPE", 2), ("HDPE", 6), ("LDPE", 0), ("LDPE", 2)}
    if (len(fs) != 8 or len(tts) != 5
        or {(s["polymer"], s["udc_wt_percent"]) for s in fs} != expected_fs
        or {(s["polymer"], s["udc_wt_percent"]) for s in tts} != expected_tts
        or analysis["method"]["reference_temperature_C"] != 210
        or any(s["temperature_C"] != 210 for s in fs)):
        raise ValueError("This explicit publication plan requires the documented HDPE/LDPE UDC sample set and nominal 210 C reference; no samples are inferred or padded.")
    if layout == "separate_polymer_modulus":
        return _separate_figure_plan(analysis)
    if layout != "legacy":
        raise ValueError(f"Unknown TTS figure layout: {layout}")
    a = frequency_panel(fs, "HDPE", "a")
    b = frequency_panel(fs, "LDPE", "b")
    tan = []
    for polymer, color, marker in (("HDPE", COLORS[2], "circle"), ("LDPE", COLORS[4], "square")):
        values = sorted((s for s in fs if s["polymer"] == polymer), key=lambda s: s["udc_wt_percent"])
        tan.append(curve(polymer, [s["udc_wt_percent"] for s in values],
            [s["at_0_1_rad_s"]["tan_delta"] for s in values], color, marker=marker, marker_size=3.2))
    c = panel("c", "c  Long-time viscoelastic balance", "UDC content (wt%)", "tan δ = G″/G′", tan,
        yscale="log", x_min=-.3, x_max=6.3, y_min=.2, y_max=20, x_ticks=[0, 2, 4, 6],
        reference_lines=[{"axis": "y", "value": 1, "style": "dash"}],
        notes=[{"text": "210 °C; ω = 0.1 rad s^{-1}", "x": .04, "y": .04}])
    d = master_panel(tts, "d", "d  Empirical TTS superposition")
    e = arrhenius_panel(tts, "e", "e  Apparent temperature activation")
    bars, labels, notes = [], [], []
    for i, s in enumerate(tts):
        ea = s["arrhenius"]["Ea_app_kJ_mol"]
        bars.append(curve("", [i + 1], [ea], _color(s), kind="bar", bar_width=.62))
        labels.append(("H" if s["polymer"] == "HDPE" else "L") + f'{s["udc_wt_percent"]:g}')
        notes.append({"text": f"{ea:.1f}", "x": (i + 1 - .3) / 5.4 - .035, "y": ea / 100 + .035})
    f = panel("f", "f  Apparent rheological E_{a}", "Formulation (UDC wt%)", "E_{a,app} (kJ mol^{-1})", bars,
        x_min=.3, x_max=5.7, y_min=0, y_max=100, y_ticks=[0, 20, 40, 60, 80, 100], x_ticks=[1, 2, 3, 4, 5], x_tick_labels=labels,
        legend=False, notes=notes + [{"text": "H: HDPE   L: LDPE", "x": .04, "y": .90}])
    main = []
    for i, item in enumerate((a, b, c, d, e, f)):
        copy = deepcopy(item)
        copy["rect_mm"] = [80 * (i % 3), 80 * (i // 3), 80, 80]
        main.append(copy)
    figures = [{"id": "Figure_X_UDC_Rheology", "width_mm": 240, "height_mm": 160, "panels": main}]
    for item in (a, b, c, d, e, f):
        figures.append({"id": f'Panel_{item["id"]}', "width_mm": 80, "height_mm": 80, "panels": [item]})
    for polymer in ("HDPE", "LDPE"):
        subset = [s for s in tts if s["polymer"] == polymer]
        for kind, item in (("d", master_panel(subset, "d", f'd  {polymer} empirical TTS')),
                           ("e", arrhenius_panel(subset, "e", f'e  {polymer} Arrhenius'))):
            figures.append({"id": f"Panel_{kind}_{polymer}", "width_mm": 80, "height_mm": 80, "panels": [item]})
    from sciplot_core.workflow.rheology_tts_supplement import supplemental_figures
    figures.extend(supplemental_figures(analysis))
    return {"version": 1, "source_binding": {"sources": analysis["sources"]},
            "transform_ledger": analysis["method"], "figures": figures}


def _separate_figure_plan(analysis: dict) -> dict:
    from sciplot_core.workflow.rheology_tts_plot_helpers import (
        MODULI, independent_figure, separate_frequency_panel, separate_master_panel,
        separate_arrhenius_panel, separate_energy_panel,
    )
    from sciplot_core.workflow.rheology_tts_supplement import separate_supplemental_figures

    expected_options = {"temperature_basis": "measured_mean", "modulus_correction": "Tref_over_T",
                        "reference_normalization": "arrhenius_postfit"}
    if (analysis.get("analysis_kind") != "temperature_reduced_rheology_tts"
            or analysis["method"].get("analysis_options") != expected_options):
        raise ValueError("Separate-polymer/modulus revision requires the measured-temperature, Tref/T reduced-modulus analysis contract.")
    figures = []
    for polymer in ("HDPE", "LDPE"):
        fs = sorted((s for s in analysis["frequency_samples"] if s["polymer"] == polymer),
                    key=lambda s: s["udc_wt_percent"])
        tts = sorted((s for s in analysis["tts_samples"] if s["polymer"] == polymer),
                     key=lambda s: s["udc_wt_percent"])
        if any(sample["at_0_1_rad_s"] is None for sample in fs):
            raise ValueError("Separate tan delta plots require exactly one original 0.1 rad/s point per sample.")
        for name, raw_metric, reduced_metric, symbol in MODULI:
            if any(reduced_metric not in p for s in tts for b in s["master_curves"] for p in b["points"]):
                raise ValueError("Separate corrected TTS plots require explicitly temperature-reduced moduli; raw moduli are not substituted.")
            figures.append(independent_figure(f"FS_{polymer}_{name}_210C",
                separate_frequency_panel(fs, polymer, raw_metric, symbol), polymer,
                raw_metric, "original_210C_acquisition"))
            figures.append(independent_figure(f"TTS_{polymer}_{name}_210C",
                separate_master_panel(tts, polymer, reduced_metric, symbol), polymer,
                reduced_metric, "temperature_reduced_master_coordinates"))
        values = [s["at_0_1_rad_s"]["tan_delta"] for s in fs]
        tan = panel("graph1", f"{polymer}: tan δ at 0.1 rad s^{{-1}}", "UDC content (wt%)", "tan δ",
            [curve(polymer, [s["udc_wt_percent"] for s in fs], values, COLORS[2])],
            x_ticks=[0, 2, 4, 6], x_min=-.3, x_max=6.3, yscale="log", legend=False,
            y_min=min(min(values), 1) / 1.4, y_max=max(max(values), 1) * 1.4,
            reference_lines=[{"axis": "y", "value": 1, "style": "dash"}])
        figures.append(independent_figure(f"Tan_delta_{polymer}_0p1rad_s", tan, polymer,
                       "loss_factor", "original_210C_acquisition"))
        figures.append(independent_figure(f"Arrhenius_{polymer}",
            separate_arrhenius_panel(tts, polymer), polymer, "ln_aT",
            "corrected_joint_shifts_actual_mean_temperature"))
        figures.append(independent_figure(f"Ea_app_{polymer}",
            separate_energy_panel(tts, polymer), polymer, "Ea_app_kJ_mol",
            "corrected_joint_shifts_actual_mean_temperature"))
    figures.extend(separate_supplemental_figures(analysis))
    return upgrade_tts_presentation({"version": 1, "figure_layout": "separate_polymer_modulus",
            "source_binding": {"sources": analysis["sources"]},
            "transform_ledger": analysis["method"], "figures": figures})


def write_analysis_tables(analysis: dict, destination: Path) -> None:
    low, raw, shifts, energy, masters, residuals = [], [], [], [], [], []
    for s in analysis["frequency_samples"]:
        low.append({"sample": s["sample_id"], "udc_wt_percent": s["udc_wt_percent"], **s["at_0_1_rad_s"]})
        raw.extend({"sample": s["sample_id"], "source": s["block"]["source"], **p} for p in s["block"]["points"])
    for s in analysis["tts_samples"]:
        for r in s["shifts"]:
            shifts.append({"sample": s["sample_id"], **{k: v for k, v in r.items() if not isinstance(v, dict)},
                           **{f"actual_temperature_C_{k}": v for k, v in r["actual_temperature_C"].items()}})
        fit = s["arrhenius"]
        row = {"sample": s["sample_id"], **{k: v for k, v in fit.items() if not isinstance(v, (dict, list))},
               **{k: v for k, v in s["diagnostics"].items() if not isinstance(v, (dict, list))}}
        for key, value in fit.items():
            if isinstance(value, dict):
                row.update({f"{key}_{k}": v for k, v in value.items() if not isinstance(v, (dict, list))})
        energy.append(row)
        residuals.extend({"sample": s["sample_id"], **r} for r in fit["rows"])
        for block in s["master_curves"]:
            masters.extend({"sample": s["sample_id"], "nominal_temperature_C": block["nominal_temperature_C"],
                            "aT": block["aT"], **p} for p in block["points"])
    for name, rows in (("Low_frequency_summary", low), ("Frequency_210C_all_points", raw),
                       ("Shift_factors", shifts), ("Activation_energy_sensitivity", energy),
                       ("Master_curves_all_points", masters), ("Arrhenius_regression", residuals)):
        write_csv(destination / f"{name}.csv", rows)
