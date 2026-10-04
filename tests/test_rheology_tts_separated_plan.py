"""Independent figures retain polymer, modulus and temperature-reduction identity."""

from copy import deepcopy

import pytest

from sciplot_core.policy import DEFAULT_FIGURE_SIZE
from sciplot_core.rheology_tts_spec import compile_tts_spec
from sciplot_core.rheology_tts_style import upgrade_tts_presentation
from sciplot_core.studio_render.value_parsing import _size_mm
from sciplot_core.workflow.rheology_tts_figures import build_tts_figures


def _analysis():
    frequency, tts = [], []
    for polymer in ("HDPE", "LDPE"):
        for amount in (0, 2, 4, 6):
            values = [{"omega_rad_s": x, "storage_modulus_Pa": 20 + x + amount,
                       "loss_modulus_Pa": 50 + x + amount, "complex_viscosity_Pa_s": 10 + x,
                       "tan_delta": 2.5} for x in (10, 1, .1)]
            frequency.append({"sample_id": f"{polymer}-{amount}UDC", "polymer": polymer,
                "udc_wt_percent": amount, "temperature_C": 210, "at_0_1_rad_s": values[-1],
                "block": {"points": values}})
            if amount not in ((0, 2, 6) if polymer == "HDPE" else (0, 2)):
                continue
            blocks, masters, shifts, rows = [], [], [], []
            for temp in (210, 190, 170):
                actual = temp + .2
                factor = 483.15 / (actual + 273.15)
                points = [dict(p, temperature_C=actual) for p in values]
                blocks.append({"points": points, "actual_temperature_C": {"mean": actual}})
                masters.append({"temperature_C": actual, "nominal_temperature_C": temp,
                    "points": [dict(p, omega_reduced_rad_s=p["omega_rad_s"] * 2,
                        storage_modulus_reduced_Pa=p["storage_modulus_Pa"] * factor,
                        loss_modulus_reduced_Pa=p["loss_modulus_Pa"] * factor) for p in points]})
                shifts.append({"temperature_C": actual, "nominal_temperature_C": temp,
                    "log10_aT": .1, "G_prime_only_log10_aT": .11, "G_double_prime_only_log10_aT": .09})
                rows.append({"inverse_temperature_1000_K": 1000 / (actual + 273.15), "ln_aT": .23,
                             "ln_aT_fit": .22})
            arrhenius = {"Ea_app_kJ_mol": 40 + amount, "rows": rows}
            for name in ("G_prime_only_sensitivity", "G_double_prime_only_sensitivity",
                         "common_window_refit_150_210_C", "nominal_temperature_sensitivity"):
                arrhenius[name] = {"Ea_app_kJ_mol": 42 + amount}
            tts.append({"sample_id": f"{polymer}-{amount}UDC", "polymer": polymer,
                "udc_wt_percent": amount, "blocks": blocks, "master_curves": masters,
                "shifts": shifts, "arrhenius": arrhenius,
                "legacy_comparison": {"arrhenius": {"Ea_app_kJ_mol": 38 + amount}},
                "diagnostics": {"rms_log10_modulus": .03, "max_channel_shift_difference_decades": .2}})
    return {"frequency_samples": frequency, "tts_samples": tts, "sources": [],
            "analysis_kind": "temperature_reduced_rheology_tts",
            "method": {"reference_temperature_C": 210, "analysis_options": {
                "temperature_basis": "measured_mean", "modulus_correction": "Tref_over_T",
                "reference_normalization": "arrhenius_postfit"}}}


def test_every_delivery_is_one_graph_and_one_polymer_on_standard_frames():
    spec = build_tts_figures(_analysis(), layout="separate_polymer_modulus")
    assert len(spec["figures"]) == 50
    assert len([f for f in spec["figures"] if not f["id"].startswith("SI_")]) == 14
    assert len({f["id"] for f in spec["figures"]}) == 50
    width, height = _size_mm(DEFAULT_FIGURE_SIZE)
    for figure in spec["figures"]:
        assert len(figure["panels"]) == 1
        assert figure["polymer"] in ("HDPE", "LDPE")
        assert figure["polymer"] in figure["id"]
        assert figure["panels"][0]["standard_frame"] is True
        if "sensitivity" not in figure["id"] and "diagnostics" not in figure["id"]:
            assert [figure["width_mm"], figure["height_mm"]] == [width, height]
        for axis in ("x", "y"):
            panel = figure["panels"][0]
            assert all(panel[f"{axis}_min"] <= value <= panel[f"{axis}_max"]
                       for series in panel["series"] for value in series[axis])


@pytest.mark.parametrize("name,raw,reduced", [
    ("Gprime", "storage_modulus_Pa", "storage_modulus_reduced_Pa"),
    ("Gdoubleprime", "loss_modulus_Pa", "loss_modulus_reduced_Pa"),
])
def test_moduli_are_separate_and_master_values_are_the_corrected_original_points(name, raw, reduced):
    analysis = _analysis()
    figures = {f["id"]: f for f in build_tts_figures(analysis, "separate_polymer_modulus")["figures"]}
    for polymer in ("HDPE", "LDPE"):
        fs = [s for s in analysis["frequency_samples"] if s["polymer"] == polymer]
        actual = figures[f"FS_{polymer}_{name}_210C"]["panels"][0]["series"]
        assert [c["y"] for c in actual] == [[p[raw] for p in s["block"]["points"]] for s in fs]
        tts = [s for s in analysis["tts_samples"] if s["polymer"] == polymer]
        blocks = [b for s in tts for b in s["master_curves"]]
        actual = figures[f"TTS_{polymer}_{name}_210C"]["panels"][0]["series"]
        assert [c["y"] for c in actual] == [[p[reduced] for p in b["points"]] for b in blocks]
        assert [c["x"] for c in actual] == [[p["omega_reduced_rad_s"] for p in b["points"]] for b in blocks]


def test_si_shift_x_uses_actual_mean_temperature_and_original_moduli_remain_raw():
    analysis = _analysis()
    figures = {f["id"]: f for f in build_tts_figures(analysis, "separate_polymer_modulus")["figures"]}
    shift = figures["SI_Shift_channels_HDPE_Control"]["panels"][0]["series"][0]
    rows = analysis["tts_samples"][0]["shifts"]
    assert shift["x"] == [1000 / (r["temperature_C"] + 273.15) for r in rows]
    original = figures["SI_Original_HDPE_Control_Gprime"]["panels"][0]["series"]
    assert [c["y"] for c in original] == [[p["storage_modulus_Pa"] for p in b["points"]]
        for b in analysis["tts_samples"][0]["blocks"]]
    assert original[0]["label"] == "210.2 °C"


@pytest.mark.parametrize("failure", ["contract", "reduced_missing", "low_frequency_missing", "sample_missing"])
def test_new_plan_does_not_silently_fallback_or_invent_missing_data(failure):
    analysis = deepcopy(_analysis())
    if failure == "contract":
        analysis["analysis_kind"] = "horizontal_only_rheology_tts"
    elif failure == "reduced_missing":
        del analysis["tts_samples"][0]["master_curves"][0]["points"][0]["storage_modulus_reduced_Pa"]
    elif failure == "low_frequency_missing":
        analysis["frequency_samples"][0]["at_0_1_rad_s"] = None
    else:
        analysis["frequency_samples"].pop()
    with pytest.raises(ValueError):
        build_tts_figures(analysis, "separate_polymer_modulus")


def test_unknown_layout_is_rejected():
    with pytest.raises(ValueError, match="Unknown TTS figure layout"):
        build_tts_figures(_analysis(), "invented_layout")


def test_legacy_layout_keeps_existing_composite_and_metric_selection():
    analysis = _analysis()
    for sample in analysis["tts_samples"]:
        sample["arrhenius"]["measured_mean_temperature_sensitivity"] = {"Ea_app_kJ_mol": 41}
    result = build_tts_figures(analysis)
    assert len(result["figures"]) == 17
    assert result["figures"][0]["id"] == "Figure_X_UDC_Rheology"
    assert len(result["figures"][0]["panels"]) == 6
    assert result["figures"][0]["panels"][0]["y_label"] == "G′, G″ (Pa)"


def test_all_fifty_plans_have_program_roles_and_no_hardcoded_marker_suppression():
    spec = build_tts_figures(_analysis(), "separate_polymer_modulus")
    compiled = compile_tts_spec(spec)
    measured = master = 0
    for figure in compiled["figures"]:
        for series in figure["panels"][0]["series"]:
            assert "unresolved_series" not in series["encoding"]["sources"].values()
            if series["role"] == "measured_curve":
                measured += 1
                assert series["marker"] != "none" and series["encoding"]["line"]["visible"]
            if series["role"] == "master_points":
                master += 1
                assert series["marker"] == "circle" and not series["encoding"]["line"]["visible"]
    assert measured and master
    assert upgrade_tts_presentation(spec) == spec


def test_historical_upgrade_is_presentation_only_and_validates_known_scientific_identity():
    spec = build_tts_figures(_analysis(), "separate_polymer_modulus")
    legacy = deepcopy(spec)
    legacy.pop("presentation_policy")
    presentation_fields = ("role", "template_id", "series_id", "semantic_id", "presentation_provenance")
    for figure in legacy["figures"]:
        panel = figure["panels"][0]
        panel.pop("template_id")
        for series in panel["series"]:
            for key in presentation_fields:
                series.pop(key)
            series.update(marker="none", marker_size=2.5, line_style="solid")
    old = deepcopy(legacy)
    upgraded = upgrade_tts_presentation(legacy)
    assert legacy == old and upgraded == spec
    legacy["figures"][0]["quantity"] = "loss_modulus_Pa"
    with pytest.raises(ValueError, match="metric/data-basis"):
        upgrade_tts_presentation(legacy)
