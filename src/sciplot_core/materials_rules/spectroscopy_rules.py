"""Declare spectroscopy rules."""

from __future__ import annotations

from sciplot_core.policy import (
    FTIR_SPECTRUM_RENDER_OPTIONS,
)
from sciplot_core.materials_rules.models import (
    AxisSpec,
    AnalysisSpec,
    SemanticRule,
    _rule,
)


SPECTROSCOPY_RULES: tuple[SemanticRule, ...] = (
    _rule(
        "ftir_spectrum",
        "ftir_spectrum",
        "spectroscopy",
        "stacked_curve",
        AxisSpec(
            "Wavenumber",
            "cm^-1",
            "Wavenumber (cm$^{-1}$)",
            aliases=("wavenumber", "cm-1"),
            reverse=True,
        ),
        AxisSpec(
            "Spectral response",
            "",
            "Spectral response",
            aliases=("transmittance", "%T", "absorbance"),
        ),
        keywords=("ftir", "wavenumber"),
        path_keywords=("ftir", "红外"),
        column_aliases=("wavenumber", "transmittance"),
        render_options=dict(FTIR_SPECTRUM_RENDER_OPTIONS),
        analysis=(
            AnalysisSpec(
                "observed_response_extremum_wavenumber_cm-1",
                (
                    "per-series observed minimum for explicitly identified percent "
                    "transmittance or maximum for explicitly identified absorbance"
                ),
                ("wavenumber", "explicit percent transmittance or absorbance"),
                "cm^-1",
            ),
        ),
        fixture_path="tests/fixtures/real_world/ftir_headerless/A40-20.CSV",
        fixture_status="ready",
        priority=50,
        scientific_source_adapter="ftir",
        figure_plan_adapter="registered_single_curve",
        preparation_adapter="curve_family",
    ),
    _rule(
        "uvvis_spectrum",
        "uvvis_spectrum",
        "spectroscopy",
        "curve",
        AxisSpec("Wavelength", "nm", "Wavelength (nm)"),
        AxisSpec("Absorbance", "a.u.", "Absorbance (a.u.)"),
        keywords=("uvvis", "uv-vis", "absorbance"),
        path_keywords=("uvvis_spectrum", "uv-vis"),
        column_aliases=("wavelength", "absorbance"),
        analysis=(
            AnalysisSpec(
                "strongest_absorbance_wavelength_nm",
                "maximum absorbance position",
                ("wavelength", "absorbance"),
                "nm",
            ),
        ),
        fixture_path="tests/fixtures/real_world/uvvis_spectrum/pda_uvvis_spectra.csv",
        fixture_status="ready",
        priority=36,
        scientific_source_adapter="registered_paired_curve",
        figure_plan_adapter="registered_single_curve",
        preparation_adapter="curve_family",
    ),
    _rule(
        "xrd_pattern",
        "xrd_pattern",
        "scattering",
        "curve",
        AxisSpec(
            "Diffraction angle",
            "degree",
            "Diffraction angle (°)",
            aliases=("angle", "2theta", "2θ"),
        ),
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)", aliases=("intensity",)),
        keywords=("2theta", "xrd"),
        column_aliases=("2theta", "intensity"),
        analysis=(
            AnalysisSpec(
                "main_peak_2theta",
                (
                    "per-series maximum observed intensity position from "
                    "canonical paired traces"
                ),
                ("diffraction_angle", "intensity"),
                "degree",
            ),
        ),
        fixture_path="tests/fixtures/real_world/xrd_pattern/pda_xrd_patterns.csv",
        fixture_status="ready",
        priority=46,
        scientific_source_adapter="registered_paired_curve",
        figure_plan_adapter="registered_single_curve",
        preparation_adapter="curve_family",
    ),
    _rule(
        "saxs_profile",
        "saxs_profile",
        "scattering",
        "curve",
        AxisSpec("q", "nm^-1", "q (nm$^{-1}$)", aliases=("q", "q_nm-1")),
        AxisSpec(
            "Intensity",
            "a.u.",
            "Log intensity (a.u.)",
            aliases=("intensity", "log intensity"),
            scale="log",
        ),
        keywords=("saxs", "qnm1", "q_nm1", "q_nm-1"),
        path_keywords=("saxs_profile", "/saxs/"),
        column_aliases=("q_nm-1", "intensity", "log intensity"),
        render_options={"size": "120x55"},
        analysis=(
            AnalysisSpec(
                "main_scattering_peak_q",
                (
                    "per-series highest interior discrete local-intensity maximum; "
                    "boundary maxima are excluded and no structural assignment is inferred"
                ),
                ("q", "intensity"),
                "nm^-1",
            ),
        ),
        fixture_path="tests/fixtures/real_world/saxs_profile/Fig3f_saxs_q_intensity.csv",
        fixture_status="ready",
        priority=47,
        scientific_source_adapter="registered_paired_curve",
        figure_plan_adapter="registered_single_curve",
        preparation_adapter="curve_family",
        reason="Multi-sample SAXS profiles use a documented 120 mm frame so their long legend labels remain legible.",
    ),
    _rule(
        "gpc_sec_chromatogram",
        "gpc_sec_chromatogram",
        "chromatography",
        "curve",
        AxisSpec(
            "Elution time",
            "min",
            "Elution time (min)",
            aliases=("time", "elution", "rt"),
        ),
        AxisSpec(
            "Detector response",
            "mV",
            "RI detector response (mV)",
            aliases=("dri", "ri", "rayleigh ratio"),
        ),
        keywords=("gpc", "sec", "dri", "rayleigh"),
        path_keywords=("/gpc/", "/gpc"),
        column_aliases=("time", "rt", "dri", "ri", "rayleigh"),
        analysis=(
            AnalysisSpec(
                "peak_elution_time_min",
                "per-series maximum detector-response time from the canonical paired table",
                ("time", "response"),
                "min",
            ),
        ),
        fixture_path="tests/fixtures/real_world/gpc_sec_chromatogram",
        fixture_status="ready",
        priority=49,
        scientific_source_adapter="gpc_sec",
        figure_plan_adapter="registered_single_curve",
        preparation_adapter="curve_family",
    ),
)
