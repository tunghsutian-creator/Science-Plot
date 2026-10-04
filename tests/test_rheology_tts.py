"""Scientific guarantees for the source-bound horizontal TTS owner."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from sciplot_core.semantic_sources.rheology_tts import (
    analyze_tts_request,
    read_tts_blocks,
)

R = 8.31446261815324


def _block(
    test: str,
    temperature: float,
    *,
    ea_gp: float = 80000,
    ea_gpp: float = 80000,
    point_count: int = 16,
    frequency_scan: bool = False,
    shift_ln: float | None = None,
) -> str:
    omega = np.logspace(2, -1, point_count)
    ln_gp = (
        ea_gp / R * (1 / (temperature + 273.15) - 1 / 483.15)
        if shift_ln is None
        else shift_ln
    )
    ln_gpp = (
        ea_gpp / R * (1 / (temperature + 273.15) - 1 / 483.15)
        if shift_ln is None
        else shift_ln
    )
    result = "Frequency sweep 1" if frequency_scan else f"FS {temperature:g} °C"
    lines = [
        f"Test:\t{test}",
        "",
        f"Result:\t{result}",
        "",
        f"Interval and data points:\t1\t{point_count}",
        "Interval data:\tPoint No.\tTemperature\tAngular Frequency\tStorage Modulus\tLoss Modulus\tShear Strain\tTorque\tStatus\tIm(Complex Viscosity)",
        "\t\t\t\t\t\t\t\t\t",
        "\t\t[°C]\t[rad/s]\t[Pa]\t[Pa]\t[%]\t[mN·m]\t\t[mPa·s]",
    ]
    for i, w in enumerate(omega):
        gp = 100 * (w * math.exp(ln_gp)) ** 0.9
        gpp = 60 * (w * math.exp(ln_gpp)) ** 0.6
        lines.append(
            f"\t{i + 1}\t{temperature + 0.2}\t{w:.15g}\t{gp:.15g}\t{gpp:.15g}\t1\t0.01\tWMa,TruStrain™\t{gp / w * 1000:.15g}"
        )
    return "\n".join(lines) + "\n\n"


def _request(
    tmp_path: Path,
    *,
    temperatures: tuple[int, ...] = (210, 190, 170, 150),
    ea_gp: float = 80000,
    ea_gpp: float = 80000,
    shifts: list[float] | None = None,
) -> dict:
    fs = tmp_path / "FS210.csv"
    tts = tmp_path / "container.csv"
    fs.write_text(_block("Sample", 210, frequency_scan=True), encoding="utf-16")
    text = _block("unrelated sample", 210, point_count=1)
    text += "".join(
        _block(
            "Original Test",
            t,
            ea_gp=ea_gp,
            ea_gpp=ea_gpp,
            shift_ln=shifts[i] if shifts is not None else None,
        )
        for i, t in enumerate(temperatures)
    )
    tts.write_text(text, encoding="utf-16")
    return {
        "version": 1,
        "reference_temperature_C": 210,
        "frequency_source": str(fs),
        "frequency_temperature_C": 210,
        "samples": [
            {
                "sample_id": "Explicit alias",
                "polymer": "Test polymer",
                "udc_wt_percent": 2,
                "frequency_test": "Sample",
                "tts_source": str(tts),
                "tts_test": "Original Test",
            }
        ],
    }


def test_exact_horizontal_model_recovers_ea_and_retains_every_point(tmp_path):
    request = _request(tmp_path)
    result = analyze_tts_request(request)
    sample = result["tts_samples"][0]
    assert sample["arrhenius"]["Ea_app_kJ_mol"] == pytest.approx(80, abs=1e-6)
    assert sample["arrhenius"]["R_squared"] == pytest.approx(1, abs=1e-12)
    assert sample["diagnostics"]["rms_log10_modulus"] < 1e-8
    assert sample["reference"]["normalization"] == "measured_nominal_reference"
    assert len(sample["master_curves"]) == 4
    for original, master, shift in zip(
        sample["blocks"], sample["master_curves"], sample["shifts"], strict=True
    ):
        assert len(original["points"]) == len(master["points"]) == 16
        assert [p["omega_rad_s"] for p in master["points"]] == [
            p["omega_rad_s"] for p in original["points"]
        ]
        assert all(
            p["omega_reduced_rad_s"] == pytest.approx(p["omega_rad_s"] * shift["aT"])
            for p in master["points"]
        )
        assert all(
            a["storage_modulus_Pa"] == b["storage_modulus_Pa"]
            for a, b in zip(original["points"], master["points"], strict=True)
        )
    # A stray first Test may not relabel or become part of the selected sweep.
    assert result["excluded_blocks"][0]["test"] == "unrelated sample"
    assert result["excluded_blocks"][0]["point_count"] == 1
    assert sample["selected_test"] == "Original Test"
    # Im(eta*) in the original is not the magnitude of complex viscosity.
    point = result["frequency_samples"][0]["block"]["points"][0]
    assert point["complex_viscosity_Pa_s"] == pytest.approx(
        math.hypot(point["storage_modulus_Pa"], point["loss_modulus_Pa"])
        / point["omega_rad_s"]
    )
    assert point["complex_viscosity_Pa_s"] != pytest.approx(
        point["storage_modulus_Pa"] / point["omega_rad_s"]
    )
    assert result["sources"][0]["sha256"]


def test_virtual_reference_uses_local_reciprocal_temperature_interpolation(tmp_path):
    temps = (240, 220, 200, 180, 160, 140)
    # Curved ln(aT) intentionally disagrees with a single Arrhenius line.
    shifts = [-0.7, 0.0, 0.5, 0.9, 1.3, 1.7]
    sample = analyze_tts_request(_request(tmp_path, temperatures=temps, shifts=shifts))[
        "tts_samples"
    ][0]
    assert not sample["reference"]["measured_nominal_reference_available"]
    factor = ((1 / 483.15) - (1 / 493.15)) / ((1 / 473.15) - (1 / 493.15))
    offset = 0.5 * factor
    assert [row["ln_aT"] for row in sample["shifts"]] == pytest.approx(
        np.array(shifts) - offset, abs=1e-7
    )
    assert sample["arrhenius"]["R_squared"] < 0.999
    assert sample["arrhenius"]["common_nominal_window_150_210_C"]["n_temperatures"] == 3


def test_different_channel_shifts_are_reported_not_hidden(tmp_path):
    sample = analyze_tts_request(_request(tmp_path, ea_gp=80000, ea_gpp=40000))[
        "tts_samples"
    ][0]
    fit = sample["arrhenius"]
    assert fit["G_prime_only_sensitivity"]["Ea_app_kJ_mol"] == pytest.approx(
        80, abs=1e-6
    )
    assert fit["G_double_prime_only_sensitivity"]["Ea_app_kJ_mol"] == pytest.approx(
        40, abs=1e-6
    )
    assert 40 < fit["Ea_app_kJ_mol"] < 80
    assert sample["diagnostics"]["rms_log10_modulus"] > 0.01
    assert sample["diagnostics"]["max_channel_shift_difference_decades"] > 0.2
    assert sample["diagnostics"]["strict_TTS_certified"] is False
    assert sample["diagnostics"]["spectrum_inversion_performed"] is False


def test_nonpositive_modulus_is_not_silently_removed(tmp_path):
    request = _request(tmp_path)
    path = Path(request["samples"][0]["tts_source"])
    lines = path.read_text(encoding="utf-16").splitlines()
    # Corrupt one selected acquisition, retaining its point identifier.
    for i, line in enumerate(lines):
        if line.startswith("\t2\t"):
            fields = line.split("\t")
            fields[4] = "-1"
            lines[i] = "\t".join(fields)
            break
    path.write_text("\n".join(lines), encoding="utf-16")
    with pytest.raises(ValueError, match="No points were dropped"):
        analyze_tts_request(request)


def test_outside_reference_and_duplicate_temperatures_fail_closed(tmp_path):
    request = _request(tmp_path)
    request["reference_temperature_C"] = 250
    with pytest.raises(ValueError, match="no extrapolation"):
        analyze_tts_request(request)
    request = _request(tmp_path, temperatures=(210, 190, 190, 150))
    with pytest.raises(ValueError, match="Duplicate selected nominal temperatures"):
        analyze_tts_request(request)


def test_declared_count_mismatch_and_unknown_test_fail_closed(tmp_path):
    request = _request(tmp_path)
    request["samples"][0]["tts_test"] = "filename alias is not a Test"
    with pytest.raises(ValueError, match="at least three temperatures"):
        analyze_tts_request(request)
    path = Path(request["frequency_source"])
    path.write_text(
        path.read_text(encoding="utf-16").replace("points:\t1\t16", "points:\t1\t17"),
        encoding="utf-16",
    )
    with pytest.raises(ValueError, match="Declared point count"):
        read_tts_blocks(path)


def test_optional_instrument_units_are_not_assumed(tmp_path):
    request = _request(tmp_path)
    path = Path(request["frequency_source"])
    path.write_text(
        path.read_text(encoding="utf-16").replace("[mN·m]", "[N·m]"), encoding="utf-16"
    )
    with pytest.raises(ValueError, match="Unsupported explicit torque unit"):
        read_tts_blocks(path)


def test_source_drift_is_rejected(tmp_path, monkeypatch):
    import sciplot_core.semantic_sources.rheology_tts_source as owner

    request = _request(tmp_path)
    path = Path(request["frequency_source"])
    original = owner.read_raw_table_normalized

    def drifting_read(source):
        frame = original(source)
        source.write_bytes(source.read_bytes() + b"\x00\x00")
        return frame

    monkeypatch.setattr(owner, "read_raw_table_normalized", drifting_read)
    with pytest.raises(ValueError, match="Source changed while reading"):
        owner.read_tts_blocks(path)


def _corrected_request(tmp_path, *, shifts=None):
    request = _request(tmp_path)
    request["analysis_options"] = {
        "temperature_basis": "measured_mean",
        "modulus_correction": "Tref_over_T",
        "reference_normalization": "arrhenius_postfit",
    }
    nominal = [210, 190, 170, 150]
    actual = [208.8, 191.2, 170.8, 150.7]
    logs = (
        [80000 / R * (1 / (t + 273.15) - 1 / 483.15) for t in actual]
        if shifts is None
        else shifts
    )
    text = _block("unrelated sample", 210, point_count=1)
    for t, mean, shift in zip(nominal, actual, logs, strict=True):
        lines = _block("Original Test", t).splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("\t"):
                continue
            cells = line.split("\t")
            if len(cells) < 6 or not cells[1].isdigit():
                continue
            point = int(cells[1]) - 1
            temperature = mean + np.linspace(-0.5, 0.5, 16)[point]
            w = float(cells[3])
            thermal_factor = (temperature + 273.15) / 483.15
            cells[2] = f"{temperature:.15g}"
            cells[4] = f"{100 * (w * math.exp(shift)) ** 0.9 * thermal_factor:.15g}"
            cells[5] = f"{60 * (w * math.exp(shift)) ** 0.6 * thermal_factor:.15g}"
            lines[i] = "\t".join(cells)
        text += "\n".join(lines) + "\n\n"
    Path(request["samples"][0]["tts_source"]).write_text(text, encoding="utf-16")
    return request, actual, logs


def test_measured_point_temperature_correction_recovers_known_model(tmp_path):
    request, actual, logs = _corrected_request(tmp_path)
    analysis = analyze_tts_request(request)
    sample = analysis["tts_samples"][0]
    assert analysis["analysis_kind"] == "temperature_reduced_rheology_tts"
    assert sample["arrhenius"]["Ea_app_kJ_mol"] == pytest.approx(80, abs=1e-6)
    assert sample["diagnostics"]["rms_log10_modulus"] < 1e-8
    assert sample["reference"]["extrapolated_reference"] is True
    assert sample["reference"]["measured_reference_available"] is False
    assert [s["temperature_C"] for s in sample["shifts"]] == pytest.approx(actual)
    assert [s["ln_aT"] for s in sample["shifts"]] == pytest.approx(logs, abs=1e-8)
    for curve in sample["master_curves"]:
        assert len(curve["points"]) == 16
        for point in curve["points"]:
            factor = 483.15 / (point["temperature_C"] + 273.15)
            assert point["modulus_correction_factor"] == pytest.approx(factor)
            assert point["storage_modulus_reduced_Pa"] == pytest.approx(
                point["storage_modulus_Pa"] * factor
            )
            assert point["loss_modulus_reduced_Pa"] == pytest.approx(
                point["loss_modulus_Pa"] * factor
            )
    assert sample["legacy_comparison"]["arrhenius"]["Ea_app_kJ_mol"] != pytest.approx(
        80, abs=0.1
    )
    assert (
        sample["arrhenius"]["common_window_refit_150_210_C"]["temperature_basis"]
        == "measured_mean"
    )
    assert analysis["excluded_blocks"][0]["source_rows"]
    assert "points" not in analysis["excluded_blocks"][0]


def test_arrhenius_postfit_does_not_constrain_independent_tts_shifts(tmp_path):
    request, _, original_logs = _corrected_request(tmp_path, shifts=[0, 0.5, 0.8, 1.8])
    sample = analyze_tts_request(request)["tts_samples"][0]
    normalized = np.array([s["ln_aT"] for s in sample["shifts"]])
    independent = np.array([s["independent_ln_shift"] for s in sample["shifts"]])
    assert np.diff(normalized) == pytest.approx(np.diff(original_logs), abs=1e-8)
    assert np.diff(independent) == pytest.approx(np.diff(original_logs), abs=1e-8)
    assert sample["arrhenius"]["R_squared"] < 0.98
    fit = sample["arrhenius"]
    assert fit["intercept"] + fit[
        "slope_ln_aT_per_1000_over_K"
    ] * 1000 / 483.15 == pytest.approx(0, abs=1e-10)
    assert normalized[0] != pytest.approx(0, abs=0.01)
    offset = sample["reference"]["removed_log10_shift_offset"] * math.log(10)
    assert normalized == pytest.approx(independent - offset, abs=1e-12)


def test_explicit_legacy_options_reproduce_default_and_unknown_options_fail(tmp_path):
    request = _request(tmp_path)
    default = analyze_tts_request(request)
    request["analysis_options"] = {
        "temperature_basis": "nominal",
        "modulus_correction": "none",
        "reference_normalization": "reciprocal_temperature_interpolation",
    }
    assert analyze_tts_request(request) == default
    request["analysis_options"]["modulus_correction"] = "unknown"
    with pytest.raises(ValueError, match="analysis_options"):
        analyze_tts_request(request)
