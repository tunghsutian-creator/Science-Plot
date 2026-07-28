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
            "Transmittance",
            "%",
            "Transmittance (%)",
            aliases=("transmittance", "%T", "absorbance"),
        ),
        keywords=("ftir", "wavenumber"),
        path_keywords=("ftir", "红外"),
        column_aliases=("wavenumber", "transmittance"),
        render_options=dict(FTIR_SPECTRUM_RENDER_OPTIONS),
        analysis=(
            AnalysisSpec(
                "strongest_peak_position",
                "per-series transmittance minimum or absorbance maximum position from canonical paired traces",
                ("wavenumber", "transmittance or absorbance"),
                "cm^-1",
            ),
        ),
        fixture_path="tests/fixtures/real_world/ftir_headerless/A40-20.CSV",
        fixture_status="ready",
        priority=50,
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
    ),
    _rule(
        "xrd_pattern",
        "xrd_pattern",
        "scattering",
        "curve",
        AxisSpec("2θ", "degree", "2θ (°)", aliases=("2theta", "2θ")),
        AxisSpec(
            "Intensity", "count", "Intensity (counts)", aliases=("intensity", "count")
        ),
        keywords=("2theta", "xrd"),
        column_aliases=("2theta", "intensity"),
        analysis=(
            AnalysisSpec(
                "main_peak_2theta",
                "per-series maximum intensity position from canonical paired traces",
                ("2theta", "intensity"),
                "degree",
            ),
        ),
        fixture_path="tests/fixtures/real_world/xrd_pattern/pda_xrd_patterns.csv",
        fixture_status="ready",
        priority=46,
    ),
    _rule(
        "saxs_profile",
        "saxs_profile",
        "scattering",
        "curve",
        AxisSpec("q", "nm^-1", "q (nm$^{-1}$)", aliases=("q", "q_nm-1"), scale="log"),
        AxisSpec(
            "Intensity", "a.u.", "Intensity (a.u.)", aliases=("intensity",), scale="log"
        ),
        keywords=("saxs", "qnm1", "q_nm1", "q_nm-1"),
        path_keywords=("saxs_profile", "/saxs/"),
        column_aliases=("q_nm-1", "intensity", "log intensity"),
        render_options={"size": "120x55"},
        analysis=(
            AnalysisSpec(
                "main_scattering_peak_q",
                "per-series highest interior local-intensity maximum; boundary maxima are excluded",
                ("q", "intensity"),
                "nm^-1",
            ),
        ),
        fixture_path="tests/fixtures/real_world/saxs_profile/Fig3f_saxs_q_intensity.csv",
        fixture_status="ready",
        priority=47,
        reason="Multi-sample SAXS profiles use a documented 120 mm log-log frame so their long legend labels remain legible.",
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
            "a.u.",
            "Detector response (a.u.)",
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
    ),
)
