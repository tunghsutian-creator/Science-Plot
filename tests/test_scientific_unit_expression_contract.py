from __future__ import annotations

import pytest

from sciplot_core.materials_rules import (
    format_plot_text_units,
    format_unit_label,
    scientific_unit_expression_contract,
    unit_solidus_violations,
)
from sciplot_core.studio import _veusz_axis_label
from sciplot_core.style_contract import audit_style_template_contract


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("kJ/m2", "kJ m⁻²"),
        ("kJ/m²", "kJ m⁻²"),
        ("W/g", "W g⁻¹"),
        ("J/g", "J g⁻¹"),
        ("%/C", "% °C⁻¹"),
        ("%/°C", "% °C⁻¹"),
        ("1/Pa", "Pa⁻¹"),
        ("rad/s", "rad s⁻¹"),
        ("MJ/m3", "MJ m⁻³"),
        ("K/min", "K min⁻¹"),
        ("MPa/min", "MPa min⁻¹"),
        ("m/s2", "m s⁻²"),
        ("W/(m K)", "W m⁻¹ K⁻¹"),
        ("cm^-1", "cm⁻¹"),
        ("mm^{−1}", "mm⁻¹"),
        ("mPa.s", "mPa·s"),
    ],
)
def test_unit_display_uses_products_and_negative_exponents(
    source: str,
    expected: str,
) -> None:
    assert format_unit_label(source) == expected
    assert format_unit_label(expected) == expected


def test_plot_text_rewrites_unit_qualifiers_but_not_variable_ratios() -> None:
    assert (
        format_plot_text_units("Impact strength (kJ/m²)") == "Impact strength (kJ m⁻²)"
    )
    assert (
        format_plot_text_units("Specific tensile toughness (J/g)")
        == "Specific tensile toughness (J g⁻¹)"
    )
    assert (
        format_plot_text_units(r"Normalized stress (\sigma/\sigma_{0})")
        == r"Normalized stress (\sigma/\sigma_{0})"
    )
    assert format_plot_text_units("G′/G′ₘ") == "G′/G′ₘ"
    assert format_unit_label("σ/σ₀") == "σ/σ₀"
    assert format_unit_label("G′/G′ₘ") == "G′/G′ₘ"
    assert format_plot_text_units("Sample / thickness (mm)") == (
        "Sample / thickness (mm)"
    )


def test_plot_text_rewrites_free_and_nested_unit_expressions() -> None:
    assert format_plot_text_units("Heat flow W/g") == "Heat flow W g⁻¹"
    assert format_plot_text_units("Rate: K/min") == "Rate: K min⁻¹"
    assert (
        format_plot_text_units("Thermal conductivity (W/(m K))")
        == "Thermal conductivity (W m⁻¹ K⁻¹)"
    )
    assert (
        format_plot_text_units("At 25 °C, heat flow W/g") == "At 25 °C, heat flow W g⁻¹"
    )


def test_unit_solidus_validator_reports_only_unit_division() -> None:
    assert unit_solidus_violations("Heat flow (W/g)") == [
        {
            "expression": "W/g",
            "replacement": "W g⁻¹",
        }
    ]
    assert unit_solidus_violations(r"Normalized stress (\sigma/\sigma_{0})") == []
    assert unit_solidus_violations("G′/G′ₘ") == []
    assert unit_solidus_violations("Rate: K/min") == [
        {
            "expression": "K/min",
            "replacement": "K min⁻¹",
        }
    ]
    assert unit_solidus_violations("Thermal conductivity (W/(m K))") == [
        {
            "expression": "W/(m K)",
            "replacement": "W m⁻¹ K⁻¹",
        }
    ]


def test_veusz_axis_boundary_applies_unit_contract() -> None:
    assert _veusz_axis_label("Heat flow (W/g)") == "Heat flow (W g⁻¹)"
    assert _veusz_axis_label("Impact strength (kJ/m²)") == ("Impact strength (kJ m⁻²)")


def test_style_audit_exposes_source_controlled_unit_contract() -> None:
    audit = audit_style_template_contract()
    contract = audit["unit_expression_contract"]

    assert audit["status"] == "passed"
    assert contract == {
        **scientific_unit_expression_contract(),
        "ready_rule_violations": [],
    }
    assert contract["division_style"] == "negative_exponent_product"
    assert contract["solidus_allowed_in_display_units"] is False
