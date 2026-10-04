from __future__ import annotations

import copy
import csv
from pathlib import Path

import pytest

from sciplot_core.workflow.rheology_tts_revision_tables import (
    write_revision_methods,
    write_revision_tables,
)


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def analysis():
    block = {
        "source": "/original.csv", "test": "Original Test", "result": "FS 210 °C",
        "header_row": 3, "data_start_row": 6, "data_end_row": 8, "point_count": 2,
        "nominal_temperature_C": 210, "actual_temperature_C": {"mean": 208.5, "min": 208, "max": 209},
        "units": {"Temperature": "[°C]", "Storage Modulus": "[Pa]"},
        "points": [{"source_row": 6, "omega_rad_s": 1, "storage_modulus_Pa": 20,
                    "modulus_correction_factor": 1.01},
                   {"source_row": 7, "omega_rad_s": .1, "storage_modulus_Pa": 10,
                    "modulus_correction_factor": 1.02}],
    }
    fit = {"n_temperatures": 3, "Ea_app_kJ_mol": 65, "Ea_fit_standard_error_kJ_mol": 2,
           "slope_ln_aT_per_1000_over_K": 7.8, "intercept": -16.1, "R_squared": .99,
           "rows": [{"temperature_C": t} for t in (208.5, 191, 171)]}
    primary = copy.deepcopy(fit)
    primary["nominal_temperature_sensitivity"] = {**fit, "Ea_app_kJ_mol": 63,
                                                  "rows": [{"temperature_C": t} for t in (210, 190, 170)]}
    primary["common_window_refit_150_210_C"] = {**fit, "Ea_app_kJ_mol": 64,
                                               "shift_basis": "Independent subset refit."}
    primary["unavailable_sensitivity"] = {"available": False, "reason": "Too few temperatures."}
    diagnostics = {"rms_log10_modulus": .03, "max_channel_shift_difference_decades": .1,
                   "pair_diagnostics": [{"temperature_i_C": 210, "temperature_j_C": 190,
                                         "actual_mean_temperature_i_C": 208.5,
                                         "actual_mean_temperature_j_C": 191,
                                         "overlap_decades": 2.4, "rms_log10_modulus": .03,
                                         "per_channel_rms_log10_modulus": {"G_prime": .04, "G_double_prime": .02}}]}
    sample = {"sample_id": "LDPE-Control", "polymer": "LDPE", "udc_wt_percent": 0,
              "blocks": [block], "reference": {"temperature_C": 210, "normalization": "arrhenius_postfit",
                                                 "extrapolated_reference": True, "removed_log10_shift_offset": .02},
              "shifts": [{"temperature_C": 208.5, "nominal_temperature_C": 210,
                          "actual_temperature_C": block["actual_temperature_C"],
                          "independent_log10_shift": 0, "independent_ln_shift": 0,
                          "log10_aT": -.02, "ln_aT": -.046, "aT": .955,
                          "channel_shift_difference_decades": .1}],
              "arrhenius": primary, "diagnostics": diagnostics,
              "legacy_comparison": {"arrhenius": {**fit, "Ea_app_kJ_mol": 57}, "diagnostics": diagnostics}}
    frequency = copy.deepcopy(block)
    frequency.update(nominal_temperature_C=None, actual_temperature_C=None, test="FS-only")
    return {"sources": [{"path": "/original.csv", "sha256": "sourcehash"}],
            "method": {"reference_temperature_C": 210, "analysis_options": {"modulus_correction": "Tref_over_T"}},
            "frequency_samples": [{"sample_id": "LDPE-Control", "polymer": "LDPE", "udc_wt_percent": 0,
                                   "temperature_C": 210, "temperature_evidence": "explicit_request", "block": frequency}],
            "tts_samples": [sample],
            "excluded_blocks": [{"source": "/original.csv", "test": "Unrelated LDPE-6UDC",
                                 "result": "FS 210 °C", "header_row": 11,
                                 "data_start_row": 14, "data_end_row": 15, "source_rows": [14],
                                 "point_count": 1, "nominal_temperature_C": 210,
                                 "actual_temperature_C": {"mean": 210.2, "min": 210.2, "max": 210.2},
                                 "reason": "Outside explicit Test selection."}]}


def test_tables_preserve_exclusion_metadata_without_exporting_measurements(tmp_path, analysis):
    before = copy.deepcopy(analysis)
    paths = write_revision_tables(analysis, tmp_path)
    rows = _read(Path(paths["Table_A_Source_selection"]))
    assert len(rows) == 3
    assert rows[0]["nominal_temperature_C"] == "210"
    assert rows[0]["actual_temperature_mean_C"] == ""
    excluded = rows[-1]
    assert excluded["selected"] == "False"
    assert excluded["source_rows_0based"] == "14"
    assert excluded["data_end_row_0based_exclusive"] == "15"
    assert excluded["selection_reason"] == "Outside explicit Test selection."
    assert excluded["source_sha256"] == "sourcehash"
    assert not any("modulus" in key or "omega" in key for key in excluded)
    assert analysis == before


def test_factor_table_records_pointwise_factor_and_independent_shift(tmp_path, analysis):
    paths = write_revision_tables(analysis, tmp_path)
    row = _read(Path(paths["Table_B_Shift_factors_and_diagnostics"]))[0]
    assert float(row["correction_factor_min"]) == 1.01
    assert float(row["correction_factor_max"]) == 1.02
    assert float(row["correction_factor_mean"]) == pytest.approx(1.015)
    assert row["shift_temperature_C"] == "208.5"
    assert row["independent_log10_shift"] == "0"
    assert row["log10_aT"] == "-0.02"
    assert row["reference_outside_measured_mean_range"] == "True"
    pair = _read(Path(paths["Table_B2_Temperature_pair_diagnostics"]))[0]
    assert pair["temperature_i_C"] == "210"
    assert pair["actual_mean_temperature_i_C"] == "208.5"
    assert pair["G_prime_rms_log10_modulus"] == "0.04"


def test_fit_variants_preserve_temperature_basis_and_missingness(tmp_path, analysis):
    paths = write_revision_tables(analysis, tmp_path)
    rows = {r["fit_variant"]: r for r in _read(Path(paths["Table_C_Apparent_activation_energy"]))}
    actual = rows["corrected_joint_actual_temperature"]
    nominal = rows["nominal_temperature_sensitivity"]
    legacy = rows["legacy_joint_nominal_temperature_no_correction"]
    assert actual["temperature_max_C"] == "208.5"
    assert nominal["temperature_max_C"] == "210"
    assert nominal["temperature_basis"] == "nominal Result label"
    assert actual["primary_reference_outside_measured_mean_range"] == "True"
    assert actual["reference_outside_fit_temperature_range"] == "True"
    assert nominal["reference_outside_fit_temperature_range"] == "False"
    assert nominal["Ea_difference_from_corrected_joint_kJ_mol"] == "-2"
    assert legacy["modulus_correction"] == "none (bT = 1)"
    assert legacy["Ea_difference_from_corrected_joint_kJ_mol"] == "-8"
    assert rows["common_window_refit_150_210_C"]["shift_normalization"].startswith("arbitrary")
    assert rows["unavailable_sensitivity"]["available"] == "False"
    assert rows["unavailable_sensitivity"]["Ea_app_kJ_mol"] == ""


def test_tables_reject_misaligned_shift_temperature(tmp_path, analysis):
    analysis["tts_samples"][0]["shifts"][0]["nominal_temperature_C"] = 200
    with pytest.raises(ValueError, match="temperature identity"):
        write_revision_tables(analysis, tmp_path)
    assert not list(tmp_path.iterdir())


def test_index_links_only_existing_exact_figure_files_and_escapes_text(tmp_path, analysis):
    for name in ("panels/Plot A.pdf", "panels/Plot A_extra.pdf", "editable/Plot A.vsz", "data/Plot A.csv"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("fixture")
    spec = {"figures": [{"id": "Plot A", "panels": [{"id": "one", "title": "G′ < sample & value"}]}]}
    write_revision_methods(tmp_path, analysis, spec)
    manifest = _read(tmp_path / "data/Figure_file_manifest.csv")
    assert len(manifest) == 3
    assert not any("extra" in row["path"] for row in manifest)
    page = (tmp_path / "index.html").read_text()
    assert 'href="panels/Plot%20A.pdf"' in page
    assert "G′ &lt; sample &amp; value" in page
    assert "panels/Plot%20A_extra.pdf" in page  # Complete inventory includes every current file.
    assert "_300dpi.tiff" not in page  # No nonexistent export links.
    assert "LDPE-Control" in (tmp_path / "README.txt").read_text()
    assert "constant density" in (tmp_path / "Figure_captions.txt").read_text()


def test_reporting_separates_core_summary_and_supporting_figure_groups(tmp_path, analysis):
    spec = {"figures": [{"id": name, "panels": [{"id": "graph1", "title": name}]}
                        for name in ("FS_HDPE_Gprime_210C", "Ea_app_HDPE", "SI_TTS_diagnostics_HDPE")]}
    for figure in spec["figures"]:
        (tmp_path / (figure["id"] + ".pdf")).write_text("fixture")
    write_revision_methods(tmp_path, analysis, spec)
    manifest = _read(tmp_path / "data/Figure_file_manifest.csv")
    assert {row["figure_id"]: row["group"] for row in manifest} == {
        "FS_HDPE_Gprime_210C": "core", "Ea_app_HDPE": "summary", "SI_TTS_diagnostics_HDPE": "SI"}
    page = (tmp_path / "index.html").read_text()
    assert page.index("Core figures (1)") < page.index("Activation-energy summaries (1)") < page.index("Supporting figures and diagnostics (1)")
    captions = (tmp_path / "Figure_captions.txt").read_text()
    assert "Core figures (1)" in captions
    assert "Activation-energy summaries (1)" in captions
    assert "Supporting figures and diagnostics (1)" in captions
