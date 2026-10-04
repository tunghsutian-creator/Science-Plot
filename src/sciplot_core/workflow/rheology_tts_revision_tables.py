"""Inspectable tables, methods and local index for corrected rheology TTS."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from sciplot_core.workflow.rheology_tts_tables import write_csv

_CORRECTION = "G_reduced(Pa) = G_raw(Pa) * (T_ref_C + 273.15) / (T_point_C + 273.15)"
_REFERENCES = (
    ("Meng et al. (2022), Rheology of vitrimers", "https://doi.org/10.1038/s41467-022-33321-w"),
    ("Edera et al. (2024), Resolving the relaxation complexity of vitrimers", "https://doi.org/10.1016/j.polymer.2024.126916"),
    ("Costa Cornellà et al. (2024), Controlling the Relaxation Dynamics of Polymer Networks", "https://doi.org/10.1002/adma.202407663"),
)
_GROUPS = (("core", "Core figures"), ("summary", "Activation-energy summaries"),
           ("SI", "Supporting figures and diagnostics"))


def _figure_group(figure: dict) -> str:
    return "SI" if figure["id"].startswith("SI_") else "summary" if figure["id"].startswith("Ea_app_") else "core"


def _identity(sample: dict) -> dict:
    return {key: sample.get(key, "") for key in ("sample_id", "polymer", "udc_wt_percent")}


def _temperatures(block: dict) -> dict:
    actual = block.get("actual_temperature_C") or {}
    return {f"actual_temperature_{key}_C": actual.get(key, "") for key in ("mean", "min", "max")}


def _selection_row(block: dict, sample: dict, role: str, hashes: dict) -> dict:
    rows = block.get("source_rows", [p["source_row"] for p in block.get("points", [])])
    nominal = block.get("nominal_temperature_C")
    if nominal is None:
        nominal = sample.get("temperature_C", "")
    return {
        **_identity(sample), "analysis_role": role, "selected": role != "unselected_interval",
        "source": block["source"], "source_sha256": hashes.get(block["source"], ""),
        "original_test": block["test"], "original_result": block["result"],
        "header_row_0based": block["header_row"],
        "data_start_row_0based": block.get("data_start_row", ""),
        "data_end_row_0based_exclusive": block.get("data_end_row", ""),
        "source_rows_0based": ";".join(str(row) for row in rows),
        "point_count": block["point_count"],
        "nominal_temperature_C": nominal,
        **_temperatures(block),
        "temperature_evidence": sample.get("temperature_evidence", "original Result label and Temperature column"),
        "selection_reason": block.get("reason", "Explicit sample/Test selection; all selected points retained."),
        "original_units_json": json.dumps(block.get("units", {}), ensure_ascii=False, sort_keys=True),
    }


def _factor_rows(sample: dict) -> list[dict]:
    reference = sample["reference"]
    result = []
    for block, shift in zip(sample["blocks"], sample["shifts"], strict=True):
        if block["nominal_temperature_C"] != shift["nominal_temperature_C"]:
            raise ValueError("Shift/block temperature identity differs; no table alignment was inferred.")
        factors = [p["modulus_correction_factor"] for p in block["points"]]
        row = {
            **_identity(sample), "source": block["source"], "original_test": block["test"],
            "original_result": block["result"], "nominal_temperature_C": shift["nominal_temperature_C"],
            **_temperatures(block), "shift_temperature_C": shift["temperature_C"],
            "point_count": block["point_count"],
            "reference_temperature_C": reference["temperature_C"],
            "normalization": reference["normalization"],
            "reference_outside_measured_mean_range": reference["extrapolated_reference"],
            "removed_log10_shift_offset": reference["removed_log10_shift_offset"],
            "correction_factor_min": min(factors), "correction_factor_max": max(factors),
            "correction_factor_mean": sum(factors) / len(factors),
            "modulus_correction_formula": _CORRECTION,
            "density_assumption": "constant density; no measured density correction",
            "sample_joint_rms_log10_modulus": sample["diagnostics"]["rms_log10_modulus"],
        }
        row.update({key: value for key, value in shift.items() if not isinstance(value, (dict, list))})
        result.append(row)
    return result


def _fit_rows(sample: dict) -> list[dict]:
    primary = sample["arrhenius"]
    variants = [("corrected_joint_actual_temperature", primary, "actual block mean", "pointwise Tref/T", sample["diagnostics"])]
    variants.extend((key, value, value.get("temperature_basis", "nominal Result label" if key == "nominal_temperature_sensitivity" else "actual block mean"), "pointwise Tref/T", {})
                    for key, value in primary.items() if isinstance(value, dict))
    legacy = sample.get("legacy_comparison")
    if legacy:
        variants.append(("legacy_joint_nominal_temperature_no_correction", legacy["arrhenius"],
                         "nominal Result label", "none (bT = 1)", legacy["diagnostics"]))
    result = []
    for name, fit, temperature_basis, correction, diagnostics in variants:
        temps = [row["temperature_C"] for row in fit.get("rows", [])]
        row = {
            **_identity(sample), "fit_variant": name,
            "available": fit.get("available", "Ea_app_kJ_mol" in fit),
            "temperature_basis": temperature_basis, "modulus_correction": correction,
            "temperature_min_C": min(temps) if temps else "", "temperature_max_C": max(temps) if temps else "",
            "temperatures_C": ";".join(format(t, ".12g") for t in temps),
            "reference_temperature_C": sample["reference"]["temperature_C"],
            "primary_reference_outside_measured_mean_range": sample["reference"]["extrapolated_reference"],
            "reference_outside_fit_temperature_range": (not min(temps) <= sample["reference"]["temperature_C"] <= max(temps)) if temps else "",
            "shift_normalization": ("arbitrary numerical anchor; only slope compared" if name == "common_window_refit_150_210_C"
                                    else "legacy reciprocal nominal-temperature interpolation" if name.startswith("legacy_")
                                    else "postfit Arrhenius prediction at reference using actual mean temperatures"),
            "sample_joint_rms_log10_modulus": diagnostics.get("rms_log10_modulus", ""),
            "max_channel_shift_difference_decades": diagnostics.get("max_channel_shift_difference_decades", ""),
            "Ea_scope": "overall/apparent rheological activation energy; not intrinsic bond exchange",
            "uncertainty_scope": "regression fit SE only; no specimen replicate uncertainty",
        }
        row.update({key: value for key, value in fit.items() if not isinstance(value, (dict, list))})
        if "Ea_app_kJ_mol" in fit:
            row["Ea_difference_from_corrected_joint_kJ_mol"] = fit["Ea_app_kJ_mol"] - primary["Ea_app_kJ_mol"]
        result.append(row)
    return result


def write_revision_tables(analysis: dict, destination: Path) -> dict[str, str]:
    """Write Tables A/B/C without re-reading sources or recomputing the analysis."""
    hashes = {source["path"]: source["sha256"] for source in analysis["sources"]}
    selection = [_selection_row(s["block"], s, "frequency_sweep", hashes) for s in analysis["frequency_samples"]]
    selection.extend(_selection_row(block, sample, "TTS_sweep", hashes)
                     for sample in analysis["tts_samples"] for block in sample["blocks"])
    selection.extend(_selection_row(block, {}, "unselected_interval", hashes) for block in analysis["excluded_blocks"])
    factors = [row for sample in analysis["tts_samples"] for row in _factor_rows(sample)]
    fits = [row for sample in analysis["tts_samples"] for row in _fit_rows(sample)]
    pairs = []
    for sample in analysis["tts_samples"]:
        for pair in sample["diagnostics"]["pair_diagnostics"]:
            row = {**_identity(sample), **{k: v for k, v in pair.items() if not isinstance(v, (dict, list))}}
            row.update({f"{key}_rms_log10_modulus": value
                        for key, value in pair.get("per_channel_rms_log10_modulus", {}).items()})
            pairs.append(row)
    tables = {"Table_A_Source_selection": selection, "Table_B_Shift_factors_and_diagnostics": factors,
              "Table_B2_Temperature_pair_diagnostics": pairs, "Table_C_Apparent_activation_energy": fits}
    for name, rows in tables.items():
        write_csv(destination / f"{name}.csv", rows)
    return {name: str(destination / f"{name}.csv") for name, rows in tables.items() if rows}


def _figure_files(delivery: Path, spec: dict) -> list[dict]:
    files = [path for path in delivery.rglob("*") if path.is_file()]
    rows = []
    for figure in spec["figures"]:
        identifier = figure["id"]
        names = {identifier + suffix for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png", ".vsz", ".csv")}
        caption = figure.get("caption") or " / ".join(p.get("title", p["id"]) for p in figure["panels"])
        for path in sorted((p for p in files if p.name in names), key=lambda p: p.as_posix()):
            rows.append({"figure_id": identifier, "group": _figure_group(figure), "caption": caption,
                         "path": path.relative_to(delivery).as_posix(), "format": path.suffix.lstrip(".")})
    return rows


def _captions(analysis: dict, spec: dict) -> str:
    lines = ["INDEPENDENT FIGURES — CAPTIONS", ""]
    for group, heading in _GROUPS:
        figures = [figure for figure in spec["figures"] if _figure_group(figure) == group]
        lines.extend((f"{heading} ({len(figures)})", ""))
        for figure in figures:
            title = figure.get("caption") or " / ".join(p.get("title", p["id"]) for p in figure["panels"])
            lines.extend((figure["id"], title, ""))
    lines.extend((
        "Frequency sweeps: original G′ and G″ at nominal 210 °C; colors identify UDC wt%.",
        "The FS210 file has no measured-temperature column. It is separate from the TTS series.",
        "tanδ is G″/G′ at the original 0.1 rad s−1 point; the reference is tanδ = 1.",
        "Complex viscosity is sqrt(G′²+G″²)/ω in Pa s, computed from original moduli.",
        "TTS: original frequencies shifted by independently fitted aT; moduli reduced pointwise",
        "by Tref[K]/Tpoint[K], assuming constant density. Both modulus channels share each aT.",
        "The target reference is 210 °C, normalized only after fitting by the free-intercept",
        "Arrhenius prediction at that temperature. No reference sweep or new point is invented.",
        "Arrhenius: symbols are fitted shifts versus 1000/Tmean[K]; lines are regressions.",
        "Ea,app is an overall/apparent rheological activation energy. It is not an intrinsic",
        "bond-exchange energy. Table C identifies the fitted temperature windows and sensitivity.",
        "The common-window refit selects actual block means in 150–210 °C; temperature grids",
        "are not identical between formulations. Full-window energies use different ranges.",
        "Diagnostic curves retain original temperature identities. RMS log-modulus residuals",
        "and G′/G″ shift differences quantify fitting mismatch, not experimental replicate error.",
        "van Gurp–Palmen plots use raw |G*| and phase angle atan2(G″,G′), without Tref/T",
        "rescaling of |G*|. Noncollapse alone does not establish failure of corrected TTS.",
        "Superposition does not by itself establish a unique relaxation mechanism or strict TTS.",
        "No unobserved terminal crossover or intrinsic exchange rate is extrapolated.", "",
        "Reference normalization outside measured mean-temperature range:",
    ))
    flagged = [s["sample_id"] for s in analysis["tts_samples"] if s["reference"]["extrapolated_reference"]]
    lines.append(", ".join(flagged) if flagged else "None.")
    return "\n".join(lines) + "\n"


_FIELDS = """TABLE FIELD DICTIONARY

Table A — source selection and interval metadata
sample_id/polymer/udc_wt_percent: explicit display/formulation identity, not inferred crosslink density.
original_test/original_result: original instrument identity and condition strings.
source/source_sha256: original input path and byte fingerprint.
selected/analysis_role/selection_reason: membership and reason; unselected rows are metadata only.
header_row/data_start_row/source_rows: zero-based original table positions.
data_end_row_0based_exclusive: first row after the interval. point_count: original acquisition count.
nominal_temperature_C: original Result label, or explicit request for the FS210 sweep.
actual_temperature_mean/min/max_C: original measured point-temperature summary; blank if absent.
original_units_json: original instrument unit fields. No unselected measurement values are exported.

Table B — factors and diagnostics, one row per selected TTS interval
shift_temperature_C: arithmetic mean of original point temperatures, used for Arrhenius regression.
modulus_correction_factor: dimensionless multiplier G_reduced/G_raw, pointwise Tref[K]/Tpoint[K].
correction_factor_min/max/mean: range and arithmetic mean of these per-point factors.
aT/log10_aT/ln_aT: normalized horizontal factor and its base-10/natural logarithms; ωreduced = aT*ω.
independent_*shift: numerical joint-overlap shift before reference normalization; its origin is arbitrary.
removed_log10_shift_offset: predicted log10 shift at Tref, subtracted uniformly after independent fitting.
G_prime_only/G_double_prime_only: separate-channel shift sensitivity, not separate measurements.
channel_shift_difference_decades: difference between normalized channel-specific log10 factors.
sample_joint_rms_log10_modulus: whole-sample shared-shift fit mismatch, repeated for context.
reference_outside_measured_mean_range: target reference outside min/max actual block means.

Table B2 — unordered temperature-pair overlap diagnostics
temperature_i/j_C: original nominal temperatures; actual_mean_temperature_i/j_C: measured block means.
overlap_decades: fitted common log10-frequency range; no modulus extrapolation.
rms_log10_modulus and per-channel RMS: residual scale in decades, not a standard error.

Table C — post-fit Arrhenius models and method sensitivity
fit_variant/temperature_basis/modulus_correction: explicit analysis choice for each row.
temperatures_C/min/max/n_temperatures: temperatures entering that regression, not new observations.
primary_reference_outside_measured_mean_range: full corrected dataset's actual-temperature flag.
reference_outside_fit_temperature_range: target outside this row's fitted temperature range/basis.
Ea_app_kJ_mol: overall/apparent rheological activation energy, kJ mol−1.
slope_ln_aT_per_1000_over_K: slope against 1000/T[K]; Ea_app = slope*8.31446261815324.
intercept: free intercept of ln(aT) = intercept + slope*(1000/T); see shift_normalization for its origin.
R_squared: ordinary linear-regression coefficient of determination.
Ea_fit_standard_error_kJ_mol: conditional regression SE; excludes specimen variation and model choice.
Ea_difference_from_corrected_joint_kJ_mol: signed difference from this sample's corrected primary fit.
available/reason: availability of a sensitivity estimate. Blank values are absent, not zero.
shift_basis: whether complete-range shifts were subsetted or shifts were independently refitted.

Plotted coordinates and analysis.json retain raw and corrected fields separately.
storage_modulus_Pa/loss_modulus_Pa are raw source-derived values in Pa.
storage_modulus_reduced_Pa/loss_modulus_reduced_Pa apply the declared pointwise correction.
omega_rad_s is original angular frequency; omega_reduced_rad_s is aT*omega_rad_s.
source_row identifies the unchanged original acquisition row. Point order is preserved.
Figure_file_manifest.csv group: core = main requested curves; summary = Ea bar summaries;
SI = supporting curves and diagnostics. The revision contains 12 core, 2 summary and 36 SI figures.
"""


def write_revision_methods(delivery: Path, analysis: dict, spec: dict) -> None:
    """Write reviewable methods and an offline index linking only existing files."""
    delivery.mkdir(parents=True, exist_ok=True)
    flagged = [s["sample_id"] for s in analysis["tts_samples"] if s["reference"]["extrapolated_reference"]]
    counts = {group: sum(_figure_group(figure) == group for figure in spec["figures"]) for group, _ in _GROUPS}
    readme = """UDC RHEOLOGY — REVISED INDEPENDENT FIGURES

Open index.html for the independent figure files, editable VSZs and data tables.
Original inputs remain unchanged outside this dedicated delivery folder.
The core set is frequency sweeps (four), tanδ (two), TTS (four) and Arrhenius (two).
Ea bar summaries and supporting diagnostics are separate from the core figure set.
正文优先使用 12 张核心图；2 张活化能汇总图和 36 张补充/诊断图单独分类。
Visible editable/*.vsz files are the visual authority. Use the supplied figure
launchers to open them in the SciPlot-supplied Veusz editor. Save and close the
native editor, then use Update_exports.command to refresh the exact saved exports.

Method change / 方法变更
Old analysis: nominal temperatures, raw moduli, horizontal shifts only (bT = 1).
Revised analysis: original point temperatures reduce both moduli by
G_reduced = G_raw * Tref[K]/Tpoint[K], with constant density explicitly assumed.
The arithmetic mean measured temperature of each block enters the Arrhenius fit.
新方法逐点使用实测温度进行 Tref/T 模量修正，并明确采用密度不变假设；
移位因子的温度坐标及 Arrhenius 回归使用每段实测温度均值。
原始数值与修正数值分别保留，未将单独的 FS210 数据拼接进 TTS。

One aT per block is fitted jointly to G′ and G″ on overlapping log-frequency grids.
Each unordered temperature pair and modulus channel has equal weight; interpolated
grid points define the objective and are not independent experimental observations.
Interpolation occurs only within measured overlap. No original points are averaged,
removed, or replaced by fitted values. Original sweep identities remain separate.

Shifts are fitted independently of an Arrhenius law. A subsequent free-intercept
regression uses ln(shift) versus 1000/Tmean[K]. Subtracting its prediction at 210 °C
defines aT(210 °C)=1 for the fitted reference relation; this constant normalization
does not change slope, residuals or fit quality and does not fabricate a 210 °C point.
This extrapolates only the normalization where the reference lies beyond measured
block means; it does not justify extrapolation of moduli or a relaxation time.

Ea,app [kJ/mol] = slope * R, R = 8.31446261815324 J mol−1 K−1 for x=1000/T[K].
Table C reports full-window, separate-channel, restricted-window and old-method
comparisons. The common-window refit uses actual means in 150–210 °C and independently
refits shifts in that subset. It is not an exactly temperature-matched experiment.
Reported fit SE is conditional regression precision, not replicate uncertainty.

Scientific boundary / 解释边界
Ea,app is overall/apparent rheological activation energy, not intrinsic bond exchange.
The correction assumes constant density; no density-versus-temperature data were supplied.
The data may depart from a shared shift of both moduli. A constructed superposition
does not prove thermorheological simplicity, dynamic-bond identity, a gel point,
or a new relaxation-spectrum peak. No unmeasured terminal crossover is asserted.
表观流变活化能具有方法和温度窗口依赖性，不能直接解释为动态键交换的本征活化能。
低频弹性贡献增强与长寿命约束相容；这些流变图本身不能独立证明唯一分子机制。

Selection and provenance
FS210 is assigned nominal 210 °C from the explicit request; it lacks measured T.
Original Test names and any explicit display aliases are recorded in Table A.
All selected measurement points are retained. Unselected intervals, including any
unrelated one-point block, are recorded with original row indices and exclusion reason
as metadata only; their measurement values are not exported as selected observations.
Raw status strings are retained without an invented interpretation or automatic cutoff.

Native dataset/export QA verifies source binding and delivered numerical fidelity;
it does not certify experimental validity or journal acceptance.
"""
    readme += f"\nFile groups: {counts['core']} core figures; {counts['summary']} activation-energy summaries; {counts['SI']} supporting figures and diagnostics.\n"
    spans = [b["actual_temperature_C"]["max"] - b["actual_temperature_C"]["min"]
             for sample in analysis["tts_samples"] for b in sample["blocks"]]
    if spans:
        readme += (f"Largest recorded within-sweep temperature span: {max(spans):.3g} °C. "
                   "Representing each sweep with one horizontal factor at its measured mean is an approximation.\n")
    readme += "\nReference outside measured mean-temperature range: " + (", ".join(flagged) or "none") + ".\n"
    readme += "\nMethodological references\n" + "\n".join(f"{title}\n{url}" for title, url in _REFERENCES)
    readme += "\n\nAnalysis method contract\n" + json.dumps(analysis["method"], ensure_ascii=False, indent=2) + "\n"
    (delivery / "README.txt").write_text(readme, encoding="utf-8")
    (delivery / "Figure_captions.txt").write_text(_captions(analysis, spec), encoding="utf-8")
    (delivery / "Table_fields.txt").write_text(_FIELDS, encoding="utf-8")
    figures = _figure_files(delivery, spec)
    write_csv(delivery / "data/Figure_file_manifest.csv", figures)
    sections = []
    for group, heading in _GROUPS:
        rows = []
        for figure in (f for f in spec["figures"] if _figure_group(f) == group):
            links = " · ".join(f'<a href="{quote(r["path"], safe="/")}">{html.escape(r["format"].upper())}</a>'
                               for r in figures if r["figure_id"] == figure["id"])
            title = figure.get("caption") or " / ".join(p.get("title", p["id"]) for p in figure["panels"])
            rows.append(f'<tr><td>{html.escape(figure["id"])}</td><td>{html.escape(title)}</td><td>{links or "Not exported"}</td></tr>')
        sections.append(f'<h2>{heading} ({counts[group]})</h2><table><tr><th>Figure</th><th>Content</th><th>Files</th></tr>' + "\n".join(rows) + "</table>")
    all_files = sorted(p.relative_to(delivery).as_posix() for p in delivery.rglob("*") if p.is_file() and p.name != "index.html")
    listing = "\n".join(f'<li><a href="{quote(path, safe="/")}">{html.escape(path)}</a></li>' for path in all_files)
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><title>UDC rheology figures</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{max-width:1120px;margin:40px auto;padding:0 24px;font:16px/1.55 system-ui;color:#20313c;background:#fafbfc}
h1{font-size:30px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;text-align:left;border-bottom:1px solid #d8e1e7}
a{color:#005d83}small{color:#586b78}li{overflow-wrap:anywhere}summary{cursor:pointer;font-weight:600}
</style><h1>UDC rheology — independent figures</h1>
<p>Source-bound raw and corrected data, editable native files, and inspectable methods.</p>
<p><a href="README.txt">Methods / 方法</a> · <a href="Figure_captions.txt">Captions</a> ·
<a href="Table_fields.txt">Table fields</a> · <a href="data/Figure_file_manifest.csv">Figure file manifest</a></p>
<p><small>Pointwise Tref/T modulus correction assumes constant density. Ea,app describes the specified overall rheological fit.</small></p>"""
    page += "\n".join(sections) + "<details><summary>Every delivered file</summary><ul>" + listing + "</ul></details></html>\n"
    (delivery / "index.html").write_text(page, encoding="utf-8")


__all__ = ["write_revision_tables", "write_revision_methods"]
