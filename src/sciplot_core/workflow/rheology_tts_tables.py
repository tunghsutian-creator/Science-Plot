"""Transparent tables and human-readable methods for a TTS analysis suite."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_plot_tables(spec: dict, destination: Path) -> None:
    for figure in spec["figures"]:
        rows = []
        for panel in figure["panels"]:
            for index, curve in enumerate(panel["series"]):
                rows.extend({
                    "panel": panel["id"], "curve": index,
                    "series": curve.get("label", ""),
                    "point_index": i, "x": x, "y": y,
                    "x_axis": panel["x_label"], "y_axis": panel["y_label"],
                    **({"y_error": curve["error_values"][i]} if curve.get("error_values") else {}),
                } for i, (x, y) in enumerate(zip(curve["x"], curve["y"], strict=True)))
        write_csv(destination / f'{figure["id"]}.csv', rows)


def write_methods(destination: Path, analysis: dict) -> None:
    text = """UDC RHEOLOGY FIGURE SUITE

Start with Figure_X_UDC_Rheology.pdf (vector) or its 300 dpi TIFF.
Separate panels are in panels/; temperature-resolved and sensitivity figures
are in SI/. Original instrument CSV files remain outside this folder unchanged.

Open_in_SciPlot.command opens the native Veusz editor supplied with SciPlot.
For this multi-panel analysis route, the editable VSZ is the visual authority.
Double-click a figure-specific launcher to edit another panel. Save in the editor,
close it, then use Update_exports.command to export the exact saved documents.
The ordinary browser canvas is not the editor for these multi-panel documents.

Scientific scope
The frequency sweeps are assigned nominal 210 C from the user's explicit request
and the FS210 file identity; that file does not contain a temperature column.
TTS uses the separate temperature-sweep files, not a splice with FS210.
LDPE 1 in LDPE-Control.csv is mapped to LDPE-Control by the explicit filename
and sample mapping. The unrelated one-point LDPE-6UDC block in HDPE-Control.csv
is preserved in the raw file and listed as unselected analysis evidence.

All selected measurement points are retained. Frequency-sweep tan(delta) is
computed as G''/G'; complex viscosity is sqrt(G'^2+G''^2)/omega in Pa s.
Lines between measured points are visual guides. No replicate uncertainty is
invented. Concentration is formulation wt% UDC, not measured crosslink density.

TTS is empirical horizontal superposition, with omega_reduced = aT * omega
and bT = 1. The same aT is fitted jointly to G' and G'' in log space, using
overlapping frequency intervals without extrapolating modulus values. Original
point order and values remain in the data tables. Interpolation is used only
inside the overlap fitting objective, not to replace measured master-curve points.
For 2UDC, 210 C is a virtual normalization interpolated between the 200 and
220 C shift factors in reciprocal absolute temperature; no 210 C sweep is invented.
Result-label nominal temperatures define the primary fit. Actual measured means
and ranges are retained and actual-mean-temperature sensitivity is reported.

Arrhenius regression uses ln(aT) = intercept + (Ea_app/R)*(1/T), T in kelvin.
Thus when x = 1000/T, Ea_app (kJ mol^-1) = slope * R (J mol^-1 K^-1).
The intercept is fitted freely. R = 8.31446261815324 J mol^-1 K^-1.
Full temperature windows differ among samples; common-window fits and separate
G'-only/G''-only fits are sensitivity analyses, not independent measurements.
No error bars are claimed as experimental replicate confidence intervals.

Horizontal superposition is imperfect, particularly where G' and G'' require
different shifts. The master curves do not establish thermorheological simplicity.
No arbitrary vertical shift or point removal is used to improve apparent collapse.
The apparent rheological activation energy is protocol- and fitting-dependent,
and must not be described as an intrinsic bond-exchange activation energy.
Network-like long-time constraints and enhanced apparent temperature sensitivity
are compatible with dynamic-network participation, but these figures alone do
not prove a unique molecular mechanism or a new resolved relaxation mode.
No relaxation spectrum is asserted: the observed superposition/channel mismatch
makes a pooled inverse spectrum insufficiently justified for assigning new peaks.
No unobserved terminal crossover or relaxation time is extrapolated.

Evidence
data/ contains exact plotted coordinates, derived metrics, and the full numerical
analysis with source hashes, original row selections, fit settings and diagnostics.
Methods and figure captions describe the finite frequency and temperature windows.
QA verifies saved native datasets and export identity; it does not certify
experimental validity or journal acceptance.
"""
    destination.write_text(text + "\nAnalysis method contract:\n" + json.dumps(analysis.get("method", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    caption = """Figure X. UDC-dependent viscoelastic response and empirical temperature superposition.
(a,b) Storage and loss moduli of HDPE and LDPE at nominal 210 °C, respectively.
Colors indicate 0, 2, 4, and 6 wt% UDC; solid and dashed curves represent G′
and G″. (c) G″/G′ at the measured angular frequency of 0.1 rad s−1. The dashed
horizontal line marks tan δ = 1. (d) Empirical horizontal superpositions of G′
for selected formulations, referenced to nominal 210 °C. Filled circles and
open diamonds denote HDPE and LDPE, respectively. Every original measured point
is shown. A single aT per temperature was fitted jointly to G′ and G″, with
bT = 1. The 2UDC reference at 210 °C is a normalization interpolated between
the 200 and 220 °C shifts. (e) Independently fitted ln aT versus reciprocal
absolute nominal temperature, with free-intercept linear regressions. Symbols
show fitted shifts; lines show regression predictions. (f) Apparent rheological
activation energies from the slopes in (e). H and L denote HDPE and LDPE; the
number denotes UDC wt%. The full fitted windows are 150–210 °C for the Controls
and HDPE-6UDC, and 140–240 °C for the 2UDC formulations. No experimental
replicate uncertainty is implied. Departures from shared horizontal
superposition, channel sensitivity and common-window refits are reported in SI.
These energies characterize the specified macroscopic rheological fit and are
not intrinsic bond-exchange activation energies.

Supporting figures
SI 01: Complex viscosity computed from the measured 210 °C moduli.
SI 02: All original temperature sweeps, with no omitted selected points.
SI 03: Both moduli after the same joint shifts; filled/open symbols are G′/G″.
SI 04: Joint versus channel-specific shift-factor sensitivity.
SI 05: van Gurp–Palmen plots of phase angle versus complex modulus.
SI 06: Activation-energy sensitivity and horizontal-superposition diagnostics.
The 150–210 °C sensitivity refits TTS within the nominal window; 2UDC supplies
160, 180 and 200 °C sweeps inside it. This is not an exactly matched-temperature
experiment. RMS log-modulus mismatch and channel shift difference are distinct
diagnostics, both expressed in decades; neither is a replicate error bar.

Interpretation supported by this dataset
UDC increases the low-frequency elastic contribution within the measured window.
Empirical horizontal shifts show a composition-dependent temperature sensitivity,
with departures from strict horizontal superposition. These observations are
consistent with additional long-lived constraints; they do not isolate intrinsic
bond-exchange kinetics or establish a uniquely resolved new relaxation mode.

Methodological references
Meng et al., Rheology of vitrimers, Nature Communications 13, 5753 (2022).
https://doi.org/10.1038/s41467-022-33321-w
Edera et al., Resolving the relaxation complexity of vitrimers: Time-temperature
superpositions of a time-temperature non-equivalent system, Polymer 299 (2024).
https://doi.org/10.1016/j.polymer.2024.126916
Costa Cornellà et al., Controlling the Relaxation Dynamics of Polymer Networks
by Combining Associative and Dissociative Dynamic Covalent Bonds (2024).
https://doi.org/10.1002/adma.202407663
"""
    destination.with_name("Figure_captions_and_interpretation.txt").write_text(caption, encoding="utf-8")
