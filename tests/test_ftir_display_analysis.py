from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.materials_rules import (
    _ftir_peak_position_metrics,
    get_rule,
    semantic_payload_from_rule,
)
from sciplot_core.one_step import build_quality_actions
from sciplot_core.policy import (
    FTIR_SPECTRUM_RENDER_OPTIONS,
    layout_policy_for_semantic,
    layout_policy_payload,
)
from sciplot_core.study_model import experiment_recommendation_payload


_FTIR_EXTREMUM_METRIC = "observed_response_extremum_wavenumber_cm-1"


def test_ftir_policy_keeps_reverse_x_without_a_fixed_wavenumber_domain() -> None:
    semantic = semantic_payload_from_rule(get_rule("ftir_spectrum"), confidence=1.0)
    render_options = semantic["render_options"]
    layout = layout_policy_payload(
        layout_policy_for_semantic(semantic, template="stacked_curve")
    )

    assert FTIR_SPECTRUM_RENDER_OPTIONS["reverse_x"] is True
    assert FTIR_SPECTRUM_RENDER_OPTIONS["x_tick_density"] == "auto"
    assert render_options["reverse_x"] is True
    assert render_options["x_tick_density"] == "auto"
    for options in (FTIR_SPECTRUM_RENDER_OPTIONS, render_options):
        assert "x_min" not in options
        assert "x_max" not in options
        assert "x_ticks" not in options
    assert layout["tick_policy"] == {"reverse_x": True}
    assert build_quality_actions(
        issue_ids=["ftir_wavenumber_bounds_missing"],
        autofixes_applied=[],
    ) == []


def test_ftir_study_model_uses_the_shared_plan_identity_and_metrics() -> None:
    recommendation = experiment_recommendation_payload(rule_id="ftir_spectrum")

    assert recommendation["figure_queue"] == [
        {
            "id": "ftir_spectrum_spectral_response_vs_wavenumber",
            "title": "FTIR spectrum",
            "metric": "spectral_response",
            "x_metric": "wavenumber",
            "y_metric": "spectral_response",
            "default_template": "stacked_curve",
        }
    ]


def test_ftir_observed_extremum_requires_an_explicit_response_mode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ftir_modes.csv"
    pd.DataFrame(
        [
            [
                "Wavenumber",
                "Transmittance",
                "Wavenumber",
                "Absorbance",
                "Wavenumber",
                "Spectral response",
            ],
            ["cm^-1", "%", "cm^-1", "a.u.", "cm^-1", "a.u."],
            ["Percent T", "Percent T", "Abs", "Abs", "Unknown", "Unknown"],
            [350.0, 80.0, 4100.0, 0.1, 500.0, 10.0],
            [900.0, 20.0, 3000.0, 0.8, 1500.0, 30.0],
            [4100.0, 70.0, 350.0, 0.2, 4100.0, 20.0],
        ]
    ).to_csv(source, header=False, index=False)

    rows = {
        str(row["metric"]): row for row in _ftir_peak_position_metrics(source)
    }

    transmittance = rows[f"{_FTIR_EXTREMUM_METRIC}[Percent T]"]
    absorbance = rows[f"{_FTIR_EXTREMUM_METRIC}[Abs]"]
    unknown = rows[f"{_FTIR_EXTREMUM_METRIC}[Unknown]"]
    assert transmittance["status"] == "ok"
    assert transmittance["value"] == 900.0
    assert absorbance["status"] == "ok"
    assert absorbance["value"] == 3000.0
    assert unknown["status"] == "skipped"
    assert unknown["value"] == ""
    for row in (transmittance, absorbance, unknown):
        reason = str(row["reason"]).casefold()
        assert "observed" in reason
        assert "chemical assignment" in reason

