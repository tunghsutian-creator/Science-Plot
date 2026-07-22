from sciplot_core.policy import RHEOLOGY_METRIC_AXIS_LABELS
from sciplot_core.semantic import _unit_conversion


def test_complex_viscosity_keeps_mpa_seconds_as_canonical_unit() -> None:
    assert _unit_conversion("mPa·s", "mPa·s") == ("mPa·s", 1.0, "identity")
    assert RHEOLOGY_METRIC_AXIS_LABELS["complex_viscosity"] == (
        "|\\eta^{*}| (mPa·s)"
    )


def test_complex_viscosity_normalizes_other_supported_units_to_mpa_seconds() -> None:
    assert _unit_conversion("Pa·s", "mPa·s") == (
        "mPa·s",
        1000.0,
        "Pa_s_to_mPa_s",
    )
    assert _unit_conversion("cP", "mPa·s") == (
        "mPa·s",
        1.0,
        "cP_to_mPa_s",
    )
