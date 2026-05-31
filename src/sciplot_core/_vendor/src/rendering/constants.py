from __future__ import annotations

from pathlib import Path

from src import plot_style
from src.plot_contract import (
    default_size_for_template,
    palette_names,
    size_names,
    template_names,
)

WORKSPACE_OUTPUT_DIR = Path("figures") / "debug_outputs"

TEMPLATE_CHOICES = template_names()
SIZE_CHOICES = size_names()
STYLE_PRESET_CHOICES = plot_style.list_public_style_presets()
PALETTE_PRESET_CHOICES = palette_names()
DEFAULT_SIZE_BY_TEMPLATE: dict[str, str] = {
    name: default_size_for_template(name)
    for name in TEMPLATE_CHOICES
}
LEGACY_TEMPLATE_HINTS = {
    "box_bar_plots": "Use `bar` or `box` instead, and switch to `violin` only when needed.",
    "frequency_sweep": "Use `point_line` or `curve` instead.",
    "temperature_sweep": "Use `point_line` or `curve` instead.",
    "stress_relaxation": "Use `point_line` or `curve` instead.",
    "tensile_curve": "Use `curve` or `point_line` instead.",
    "ftir": "Use `stacked_curve` instead.",
    "nmr": "Use `stacked_curve` instead.",
    "wide_nmr": "Use `segmented_stacked_curve` instead.",
    "xrd": "Use `stacked_curve` instead.",
    "dsc": "Use `stacked_curve` instead.",
    "tga": "Use `curve` instead.",
    "dma": "Use `curve` instead.",
}

FREQUENCY_OUTPUTS = {
    "storage_modulus": "freq_storage_modulus.pdf",
    "loss_modulus": "freq_loss_modulus.pdf",
    "loss_factor": "freq_loss_factor.pdf",
    "complex_viscosity": "freq_complex_viscosity.pdf",
}
FREQUENCY_CURVE_OUTPUTS = {
    "storage_modulus": "freq_storage_modulus_curve.pdf",
    "loss_modulus": "freq_loss_modulus_curve.pdf",
    "loss_factor": "freq_loss_factor_curve.pdf",
    "complex_viscosity": "freq_complex_viscosity_curve.pdf",
}
FREQUENCY_AREA_CURVE_OUTPUTS = {
    "storage_modulus": "freq_storage_modulus_area_curve.pdf",
    "loss_modulus": "freq_loss_modulus_area_curve.pdf",
    "loss_factor": "freq_loss_factor_area_curve.pdf",
    "complex_viscosity": "freq_complex_viscosity_area_curve.pdf",
}
FREQUENCY_STEP_LINE_OUTPUTS = {
    "storage_modulus": "freq_storage_modulus_step_line.pdf",
    "loss_modulus": "freq_loss_modulus_step_line.pdf",
    "loss_factor": "freq_loss_factor_step_line.pdf",
    "complex_viscosity": "freq_complex_viscosity_step_line.pdf",
}
TEMPERATURE_OUTPUTS = {
    "storage_modulus": "temp_storage_modulus.pdf",
    "complex_viscosity": "temp_complex_viscosity.pdf",
}
TEMPERATURE_CURVE_OUTPUTS = {
    "storage_modulus": "temp_storage_modulus_curve.pdf",
    "complex_viscosity": "temp_complex_viscosity_curve.pdf",
}
TEMPERATURE_AREA_CURVE_OUTPUTS = {
    "storage_modulus": "temp_storage_modulus_area_curve.pdf",
    "complex_viscosity": "temp_complex_viscosity_area_curve.pdf",
}
TEMPERATURE_STEP_LINE_OUTPUTS = {
    "storage_modulus": "temp_storage_modulus_step_line.pdf",
    "complex_viscosity": "temp_complex_viscosity_step_line.pdf",
}
STRESS_RELAXATION_OUTPUT = "stress_relaxation_sigma_over_sigma0.pdf"
STRESS_RELAXATION_CURVE_OUTPUT = "stress_relaxation_sigma_over_sigma0_curve.pdf"
STRESS_RELAXATION_AREA_CURVE_OUTPUT = "stress_relaxation_sigma_over_sigma0_area_curve.pdf"
STRESS_RELAXATION_STEP_LINE_OUTPUT = "stress_relaxation_sigma_over_sigma0_step_line.pdf"
