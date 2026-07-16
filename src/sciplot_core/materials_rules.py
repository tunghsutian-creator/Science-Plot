from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core._utils import token as _utils_token
from sciplot_core.policy import (
    CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
    CURVE_RENDER_OPTIONS,
    DEFAULT_RENDER_OPTIONS as _DEFAULT_RENDER_OPTIONS,
    DEFAULT_LOG_TICK_FORMAT,
    DEFAULT_PALETTE_PRESET,
    FTIR_SPECTRUM_RENDER_OPTIONS,
    POINT_LINE_RENDER_OPTIONS,
    RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
    RHEOLOGY_FREQUENCY_X_LABEL,
    TORQUE_CURVE_RENDER_OPTIONS,
)
from sciplot_core.study_model import experiment_recommendation_payload

ensure_legacy_core()

from src.data_loader import read_raw_table  # noqa: E402


def normalize_token(value: object) -> str:
    result = _utils_token(value)
    return result or "\ufffd"


@dataclass(frozen=True)
class UnitRule:
    source: str
    target: str
    factor: float = 1.0
    offset: float = 0.0


@dataclass(frozen=True)
class AxisSpec:
    canonical_label: str
    canonical_unit: str
    display_label: str
    aliases: tuple[str, ...] = ()
    priority_labels: tuple[str, ...] = ()
    scale: str = "linear"
    reverse: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "canonical_label": self.canonical_label,
            "canonical_unit": self.canonical_unit,
            "display_label": self.display_label,
            "aliases": list(self.aliases),
            "priority_labels": list(self.priority_labels),
            "scale": self.scale,
            "reverse": self.reverse,
        }


@dataclass(frozen=True)
class AnalysisSpec:
    metric: str
    method: str
    required_inputs: tuple[str, ...] = ()
    unit: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "method": self.method,
            "required_inputs": list(self.required_inputs),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class SemanticRule:
    rule_id: str
    semantic_family: str
    recipe: str | None
    template: str
    x_axis: AxisSpec
    y_axis: AxisSpec
    keywords: tuple[str, ...] = ()
    path_keywords: tuple[str, ...] = ()
    column_aliases: tuple[str, ...] = ()
    vendor_models: tuple[str, ...] = ()
    experiment_families: tuple[str, ...] = ()
    render_options: dict[str, Any] = field(default_factory=dict)
    analysis: tuple[AnalysisSpec, ...] = ()
    available_metrics: tuple[str, ...] = ()
    fixture_path: str | None = None
    fixture_status: str = "pending"
    priority: int = 100
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "semantic_family": self.semantic_family,
            "recipe": self.recipe,
            "template": self.template,
            "axis_plan": {
                "x": self.x_axis.to_payload(),
                "y": self.y_axis.to_payload(),
            },
            "unit_plan": {
                "x": format_unit_label(self.x_axis.canonical_unit),
                "y": format_unit_label(self.y_axis.canonical_unit),
            },
            "analysis_plan": [item.to_payload() for item in self.analysis],
            "available_metrics": list(self.available_metrics or tuple(item.metric for item in self.analysis)),
            "experiment_recommendation": experiment_recommendation_payload(
                rule_id=self.rule_id,
                semantic_family=self.semantic_family,
                experiment_type_id=self.rule_id,
            ),
            "keywords": list(self.keywords),
            "path_keywords": list(self.path_keywords),
            "column_aliases": list(self.column_aliases),
            "render_options": dict(self.render_options),
            "fixture_path": self.fixture_path,
            "fixture_status": self.fixture_status,
            "priority": self.priority,
            "reason": self.reason,
        }


_UNIT_RULES = {
    ("Pa", "kPa"): UnitRule("Pa", "kPa", 1e-3),
    ("Pa", "MPa"): UnitRule("Pa", "MPa", 1e-6),
    ("Pa", "GPa"): UnitRule("Pa", "GPa", 1e-9),
    ("kPa", "Pa"): UnitRule("kPa", "Pa", 1e3),
    ("MPa", "Pa"): UnitRule("MPa", "Pa", 1e6),
    ("GPa", "Pa"): UnitRule("GPa", "Pa", 1e9),
    ("mPa.s", "Pa.s"): UnitRule("mPa.s", "Pa.s", 1e-3),
    ("Pa.s", "mPa.s"): UnitRule("Pa.s", "mPa.s", 1e3),
    ("ms", "s"): UnitRule("ms", "s", 1e-3),
    ("min", "s"): UnitRule("min", "s", 60.0),
    ("h", "s"): UnitRule("h", "s", 3600.0),
    ("s", "min"): UnitRule("s", "min", 1 / 60.0),
    ("s", "h"): UnitRule("s", "h", 1 / 3600.0),
    ("K", "C"): UnitRule("K", "C", 1.0, -273.15),
    ("C", "K"): UnitRule("C", "K", 1.0, 273.15),
    ("fraction", "%"): UnitRule("fraction", "%", 100.0),
    ("%", "fraction"): UnitRule("%", "fraction", 0.01),
    ("nm", "um"): UnitRule("nm", "um", 1e-3),
    ("um", "nm"): UnitRule("um", "nm", 1e3),
    ("um", "mm"): UnitRule("um", "mm", 1e-3),
    ("mm", "um"): UnitRule("mm", "um", 1e3),
    ("A^-1", "nm^-1"): UnitRule("A^-1", "nm^-1", 10.0),
    ("nm^-1", "A^-1"): UnitRule("nm^-1", "A^-1", 0.1),
}

_UNIT_LABELS = {
    "C": "°C",
    "um": "µm",
    "mPa.s": "mPa·s",
    "N·m": "N·m",
    "Pa.s": "Pa·s",
    "cm^-1": "cm$^{-1}$",
    "nm^-1": "nm$^{-1}$",
    "A^-1": "Å$^{-1}$",
    "sigma/sigma0": "$\\sigma/\\sigma_0$",
    "G/G0": "$G(t)/G_0$",
    "1/Pa": "Pa$^{-1}$",
}


def convert_value(value: float, source_unit: str, target_unit: str) -> float:
    if source_unit == target_unit:
        return float(value)
    rule = _UNIT_RULES.get((source_unit, target_unit))
    if rule is None:
        raise ValueError(f"No SciPlot material unit conversion from `{source_unit}` to `{target_unit}`.")
    return float(value) * rule.factor + rule.offset


def format_unit_label(unit: str) -> str:
    if not unit:
        return ""
    if unit in _UNIT_LABELS:
        return _UNIT_LABELS[unit]
    return re.sub(r"\^-?(\d+)", lambda match: f"$^{{-{match.group(1)}}}$", unit)


def _rule(
    rule_id: str,
    semantic_family: str,
    recipe: str | None,
    template: str,
    x: AxisSpec,
    y: AxisSpec,
    *,
    keywords: tuple[str, ...] = (),
    path_keywords: tuple[str, ...] = (),
    column_aliases: tuple[str, ...] = (),
    vendor_models: tuple[str, ...] = (),
    experiment_families: tuple[str, ...] = (),
    render_options: dict[str, Any] | None = None,
    analysis: tuple[AnalysisSpec, ...] = (),
    available_metrics: tuple[str, ...] = (),
    fixture_path: str | None = None,
    fixture_status: str = "pending",
    priority: int = 100,
    reason: str = "",
) -> SemanticRule:
    default_options = {
        "point_line": POINT_LINE_RENDER_OPTIONS,
        "curve": CURVE_RENDER_OPTIONS,
    }.get(template, _DEFAULT_RENDER_OPTIONS)
    return SemanticRule(
        rule_id=rule_id,
        semantic_family=semantic_family,
        recipe=recipe,
        template=template,
        x_axis=x,
        y_axis=y,
        keywords=keywords,
        path_keywords=path_keywords,
        column_aliases=column_aliases,
        vendor_models=vendor_models,
        experiment_families=experiment_families,
        render_options={**default_options, **(render_options or {})},
        analysis=analysis,
        available_metrics=available_metrics,
        fixture_path=fixture_path,
        fixture_status=fixture_status,
        priority=priority,
        reason=reason,
    )


RHEOLOGY_X_FREQUENCY = AxisSpec(
    "Angular frequency",
    "rad/s",
    RHEOLOGY_FREQUENCY_X_LABEL,
    aliases=("angular frequency", "frequency", "omega", "ω"),
    scale="log",
)
RHEOLOGY_X_TEMPERATURE = AxisSpec(
    "Temperature",
    "C",
    "Temperature (°C)",
    aliases=("temperature", "temp", "温度"),
)
TIME_AXIS = AxisSpec("Time", "s", "Time (s)", aliases=("time", "时间"))
STRAIN_AXIS = AxisSpec("Strain", "%", "Strain (%)", aliases=("strain", "拉伸应变", "shear strain", "γ"))
STRESS_AXIS = AxisSpec("Stress", "MPa", "Stress (MPa)", aliases=("stress", "拉伸应力", "σ"))
TORQUE_AXIS = AxisSpec("Screw torque", "N·m", "Screw torque (N·m)", aliases=("screw torque", "torque", "转矩"))


RULES: tuple[SemanticRule, ...] = (
    _rule(
        "rheology_frequency_sweep",
        "rheology_frequency",
        "rheology_dma",
        "point_line",
        RHEOLOGY_X_FREQUENCY,
        AxisSpec(
            "Storage modulus",
            "Pa",
            "Storage modulus, G′ (Pa)",
            aliases=("storage modulus", "G'", "G′"),
            priority_labels=("G'", "Storage Modulus", "G′", "G\"", "tanδ"),
            scale="log",
        ),
        keywords=("frequencysweep", "angularfrequency", "pinlv"),
        path_keywords=("/freq/", "pinlv"),
        column_aliases=(
            "angular frequency",
            "storage modulus",
            "loss modulus",
            "loss factor",
            "complex modulus",
        ),
        vendor_models=("frequency_metric_sheet",),
        experiment_families=("rheology",),
        render_options=RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
        analysis=(AnalysisSpec("terminal_modulus", "last finite G' value", ("G'",), "Pa"),),
        fixture_path="tests/fixtures/real_world/rheology_frequency_sweep",
        fixture_status="ready",
        priority=20,
        reason="Rheology frequency sweep with modulus/viscosity metrics.",
    ),
    _rule(
        "rheology_temperature_sweep",
        "rheology_temperature_sweep",
        "rheology_dma",
        "point_line",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec(
            "Storage modulus",
            "Pa",
            "Storage modulus, G′ (Pa)",
            aliases=("storage modulus", "G'", "G′", "complex modulus", "|G*|"),
            priority_labels=("G'", "Storage Modulus", "|G*|", "Complex Modulus", "G\""),
            scale="log",
        ),
        keywords=("rheologytemperaturesweep", "temperaturesweep", "温度扫描"),
        path_keywords=("/temp/", "rheology_temperature"),
        column_aliases=("temperature", "storage modulus", "complex modulus"),
        render_options=_DEFAULT_RENDER_OPTIONS,
        analysis=(
            AnalysisSpec("tan_delta", "loss factor column if present", ("tan delta",), "1"),
            AnalysisSpec(
                "softening_temperature_candidate",
                "largest modulus drop candidate",
                ("temperature", "modulus"),
                "C",
            ),
        ),
        available_metrics=("tan_delta", "softening_temperature_candidate"),
        fixture_path="tests/fixtures/real_world/rheology_temperature_sweep",
        fixture_status="ready",
        priority=10,
        reason="Rheology/DMA temperature sweep with modulus priority G′, |G*|, then G″.",
    ),
    _rule(
        "rheology_time_sweep",
        "rheology_time_sweep",
        "rheology_dma",
        "point_line",
        TIME_AXIS,
        AxisSpec("Modulus", "Pa", "Modulus (Pa)", aliases=("modulus", "G'", "G\"")),
        keywords=("timesweep", "time sweep"),
        path_keywords=("rheology_time_sweep", "time_sweep"),
        analysis=(AnalysisSpec("peak_modulus_time_s", "time at maximum modulus", ("time", "modulus"), "s"),),
        fixture_path="tests/fixtures/real_world/rheology_time_sweep",
        fixture_status="ready",
        priority=28,
    ),
    _rule(
        "rheology_strain_sweep",
        "rheology_strain_sweep",
        "rheology_dma",
        "point_line",
        AxisSpec("Strain", "%", "Strain (%)", aliases=("strain", "shear strain", "γ"), scale="log"),
        AxisSpec("Modulus", "Pa", "Modulus (Pa)", aliases=("modulus", "G'", "G\""), scale="log"),
        keywords=("strainsweep", "amplitude sweep"),
        path_keywords=("rheology_strain_sweep", "strain_sweep"),
        analysis=(
            AnalysisSpec("peak_modulus_strain_percent", "strain at maximum modulus", ("strain", "modulus"), "%"),
        ),
        fixture_path="tests/fixtures/real_world/rheology_strain_sweep",
        fixture_status="ready",
        priority=28,
    ),
    _rule(
        "rheology_stress_sweep",
        "rheology_stress_sweep",
        "rheology_dma",
        "point_line",
        AxisSpec("Stress", "Pa", "Stress (Pa)", aliases=("stress", "shear stress"), scale="log"),
        AxisSpec("Modulus", "Pa", "Modulus (Pa)", aliases=("modulus", "G'", "G\""), scale="log"),
        keywords=("stresssweep", "stress sweep"),
        path_keywords=("rheology_stress_sweep", "stress_sweep"),
        analysis=(AnalysisSpec("peak_modulus_stress_Pa", "stress at maximum modulus", ("stress", "modulus"), "Pa"),),
        fixture_path="tests/fixtures/real_world/rheology_stress_sweep",
        fixture_status="ready",
        priority=28,
        reason=(
            "Shared amplitude-sweep parser using the instrument-reported measured shear-stress axis; "
            "the evidence record does not claim a stress-controlled protocol."
        ),
    ),
    _rule(
        "rheology_creep",
        "rheology_creep",
        "rheology_dma",
        "curve",
        TIME_AXIS,
        AxisSpec("Creep compliance", "1/Pa", "Creep compliance, J(t) (Pa$^{-1}$)", aliases=("creep compliance",)),
        keywords=("creep", "creeptest", "creepcompliance"),
        path_keywords=("creep",),
        analysis=(
            AnalysisSpec("final_compliance", "last finite J(t)", ("Creep compliance",), "1/Pa"),
            AnalysisSpec("recovery_ratio", "recovery segment if available", ("Creep compliance",), "fraction"),
        ),
        fixture_path="tests/fixtures/real_world/rheology_creep",
        fixture_status="ready",
        priority=30,
    ),
    _rule(
        "rheology_stress_relaxation",
        "rheology_stress_relaxation",
        "stress_relaxation",
        "curve",
        AxisSpec("Time", "s", "Time (s)", aliases=("time", "时间"), scale="log"),
        AxisSpec(
            "Normalized stress",
            "sigma/sigma0",
            "Normalized stress ($\\sigma/\\sigma_0$)",
            aliases=("shear stress", "relaxation modulus", "stress"),
        ),
        keywords=("stressrelaxation", "stresssrelaxation", "relaxationtest", "relaxationmodulus", "stepstrain"),
        path_keywords=("relax", "stresss relaxation"),
        analysis=(
            AnalysisSpec("final_normalized_value", "last normalized stress/modulus", ("stress",), "sigma/sigma0"),
            AnalysisSpec("t50_s", "time to normalized value <= 0.5", ("stress", "time"), "s"),
        ),
        render_options={
            **CURVE_RENDER_OPTIONS,
            "xscale": "log",
            "x_tick_format": DEFAULT_LOG_TICK_FORMAT,
            "minor_tick_count": 10,
            "y_min": -0.05,
            "y_max": 1.05,
            "y_ticks": [0.0, 0.25, 0.5, 0.75, 1.0],
        },
        fixture_path="tests/fixtures/real_world/rheology_stress_relaxation",
        fixture_status="ready",
        priority=25,
    ),
    _rule(
        "tensile_curve",
        "tensile_curve",
        "tensile",
        "curve",
        AxisSpec(
            "Strain",
            "%",
            "Tensile Strain (%)",
            aliases=("strain", "拉伸应变", "shear strain", "γ"),
        ),
        AxisSpec(
            "Stress",
            "MPa",
            "Tensile Stress (MPa)",
            aliases=("stress", "拉伸应力", "σ"),
        ),
        keywords=("tensile", "拉伸", "结果表格2"),
        path_keywords=("tensile", ".is_tens_exports"),
        vendor_models=("tensile_curve",),
        analysis=(
            AnalysisSpec("modulus_MPa", "low-strain linear slope", ("strain", "stress"), "MPa"),
            AnalysisSpec("strength_MPa", "maximum stress", ("stress",), "MPa"),
            AnalysisSpec("strain_at_break_percent", "last strain", ("strain",), "%"),
            AnalysisSpec(
                "toughness_MJ_m3",
                "area under stress-strain curve using engineering strain as a fraction",
                ("strain", "stress"),
                "MJ/m3",
            ),
        ),
        fixture_path="tests/fixtures/real_world/tensile_curve/E0 2MM.is_tens_Exports",
        fixture_status="ready",
        priority=40,
    ),
    _rule(
        "torque_curve",
        "torque_curve",
        "rheology_dma",
        "curve",
        TIME_AXIS,
        TORQUE_AXIS,
        keywords=("screwtorque", "screw torque", "screw speed", "setting torque", "转矩"),
        path_keywords=("torque", "转矩"),
        column_aliases=("screw torque", "转矩"),
        analysis=(
            AnalysisSpec(
                "selected_event_mean_torque_Nm_by_sample",
                "mean torque over the recorded selected final event, reported separately for each sample",
                ("Screw Torque",),
                "N·m",
            ),
        ),
        render_options=dict(TORQUE_CURVE_RENDER_OPTIONS),
        fixture_path="tests/fixtures/real_world/torque_curve/260607",
        fixture_status="ready",
        priority=42,
        reason="Torque rheometer export with Screw Torque over time.",
    ),
    _rule(
        "compression_curve",
        "compression_curve",
        "tensile",
        "curve",
        STRAIN_AXIS,
        STRESS_AXIS,
        keywords=("compression", "compressive", "压缩"),
        path_keywords=("compression_curve", "compressive"),
        analysis=(
            AnalysisSpec("peak_compressive_stress_MPa", "maximum compressive stress", ("strain", "stress"), "MPa"),
        ),
        fixture_path="tests/fixtures/real_world/compression_curve/conventional_pu_compression.csv",
        fixture_status="ready",
        priority=34,
    ),
    _rule(
        "flexural_curve",
        "flexural_curve",
        "tensile",
        "curve",
        STRAIN_AXIS,
        STRESS_AXIS,
        keywords=("flexural", "bending", "弯曲"),
        path_keywords=("flexural_curve", "bending"),
        analysis=(AnalysisSpec("peak_flexural_stress_MPa", "maximum flexural stress", ("strain", "stress"), "MPa"),),
        fixture_path="tests/fixtures/real_world/flexural_curve/A_HA56_dry_flexural.csv",
        fixture_status="ready",
        priority=34,
    ),
    _rule(
        "impact_metric",
        "impact_metric",
        "metrics_swelling",
        "box_strip",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec("Impact strength", "kJ/m2", "Impact strength (kJ/m²)", aliases=("impact strength", "冲击")),
        keywords=("impact", "冲击"),
        render_options={
            **CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
            "x_label_override": "Sample",
            "y_label_override": "Impact strength (kJ/m²)",
            "summary_statistic": "median_iqr",
        },
        analysis=(
            AnalysisSpec("impact_group_n", "per-sample raw replicate count", ("impact",), "count"),
            AnalysisSpec("impact_group_median", "per-sample median of raw values", ("impact",), "kJ/m2"),
            AnalysisSpec(
                "impact_group_iqr",
                "per-sample interquartile range when at least two raw values are available",
                ("impact",),
                "kJ/m2",
            ),
        ),
        fixture_path="tests/fixtures/real_world/impact_metric/impact strength.xlsx",
        fixture_status="ready",
        priority=5,
        reason=(
            "Impact-strength groups preserve every raw observation; groups with at least two replicates use "
            "a native Veusz median/IQR box summary, while smaller groups remain raw-point only."
        ),
    ),
    _rule(
        "dsc_curve",
        "dsc_curve",
        "thermal",
        "curve",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec("Heat flow", "W/g", "Heat flow (W/g)", aliases=("heat flow", "dsc")),
        keywords=("dsc", "heatflow", "heat flow"),
        column_aliases=("heat flow",),
        analysis=(
            AnalysisSpec("tg_candidate_C", "largest heat-flow slope candidate", ("temperature", "heat flow"), "C"),
            AnalysisSpec("peak_temperature_C", "largest absolute heat-flow peak", ("temperature", "heat flow"), "C"),
        ),
        fixture_path="tests/fixtures/real_world/dsc_curve/udc_dsc_digitized.csv",
        fixture_status="ready",
        priority=8,
    ),
    _rule(
        "tga_curve",
        "tga_curve",
        "thermal",
        "curve",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec("Mass", "%", "Mass (%)", aliases=("weight", "mass", "tga")),
        keywords=("tga", "weightloss", "weight"),
        column_aliases=("temp", "weight"),
        analysis=(
            AnalysisSpec("residual_mass_percent", "last finite mass percent", ("mass",), "%"),
            AnalysisSpec("t5_temperature_C", "temperature at 5% mass loss", ("temperature", "mass"), "C"),
            AnalysisSpec("t10_temperature_C", "temperature at 10% mass loss", ("temperature", "mass"), "C"),
        ),
        fixture_path="tests/fixtures/real_world/tga_curve/evoh1_tga_curve.csv",
        fixture_status="ready",
        priority=42,
    ),
    _rule(
        "dtg_curve",
        "dtg_curve",
        "thermal",
        "curve",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec("Derivative mass", "%/C", "DTG (%/°C)", aliases=("dtg", "derivative")),
        keywords=("dtg", "derivativeweight"),
        path_keywords=("dtg_curve", "dtg"),
        column_aliases=("temperature", "dtg", "derivative"),
        analysis=(AnalysisSpec("dtg_peak_temperature_C", "maximum derivative loss", ("temperature", "dtg"), "C"),),
        fixture_path="tests/fixtures/real_world/dtg_curve/evoh1_dtg_curve.csv",
        fixture_status="ready",
        priority=32,
    ),
    _rule(
        "dma_temperature_sweep",
        "dma_temperature_sweep",
        "rheology_dma",
        "point_line",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec("Storage modulus", "Pa", "Storage modulus, E′ (Pa)", aliases=("E'", "storage modulus", "tan delta")),
        keywords=("dma", "storagemodulusmpa", "tanδ", "tandelta"),
        path_keywords=("dma_temperature_sweep", "dma_temperature"),
        column_aliases=("temperature", "storage modulus", "loss factor", "tan delta"),
        analysis=(
            AnalysisSpec(
                "storage_modulus_drop_temperature_C",
                "largest E′ drop candidate",
                ("temperature", "storage modulus"),
                "C",
            ),
        ),
        render_options={**_DEFAULT_RENDER_OPTIONS, "y_min": 0.0},
        fixture_path=(
            "tests/fixtures/real_world/dma_temperature_sweep/"
            "Fig2b_storage_modulus_temperature.csv"
        ),
        fixture_status="ready",
        priority=30,
    ),
    _rule(
        "ftir_spectrum",
        "ftir_spectrum",
        "spectroscopy",
        "stacked_curve",
        AxisSpec("Wavenumber", "cm^-1", "Wavenumber (cm$^{-1}$)", aliases=("wavenumber", "cm-1"), reverse=True),
        AxisSpec("Transmittance", "%", "Transmittance (%)", aliases=("transmittance", "%T", "absorbance")),
        keywords=("ftir", "wavenumber"),
        path_keywords=("ftir", "红外"),
        column_aliases=("wavenumber", "transmittance"),
        render_options=dict(FTIR_SPECTRUM_RENDER_OPTIONS),
        analysis=(
            AnalysisSpec(
                "strongest_peak_position",
                "maximum/minimum intensity position",
                ("wavenumber",),
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
        AxisSpec("Intensity", "count", "Intensity (counts)", aliases=("intensity", "count")),
        keywords=("2theta", "xrd"),
        column_aliases=("2theta", "intensity"),
        analysis=(AnalysisSpec("main_peak_2theta", "maximum intensity position", ("2theta", "intensity"), "degree"),),
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
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)", aliases=("intensity",), scale="log"),
        keywords=("saxs", "qnm1", "q_nm1", "q_nm-1"),
        path_keywords=("saxs_profile", "/saxs/"),
        column_aliases=("q_nm-1", "intensity", "log intensity"),
        render_options={"size": "120x55"},
        analysis=(AnalysisSpec("main_scattering_peak_q", "maximum intensity q", ("q", "intensity"), "nm^-1"),),
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
        AxisSpec("Elution time", "min", "Elution time (min)", aliases=("time", "elution", "rt")),
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
                "maximum detector response time",
                ("time", "response"),
                "min",
            ),
        ),
        fixture_path="tests/fixtures/real_world/gpc_sec_chromatogram",
        fixture_status="ready",
        priority=49,
    ),
    _rule(
        "swelling_curve",
        "swelling_curve",
        "metrics_swelling",
        "point_line",
        AxisSpec("Time", "h", "Time (h)", aliases=("time",)),
        AxisSpec(
            "Swelling ratio",
            "1",
            "Swelling ratio",
            aliases=("swelling ratio", "Ai/A0", "normalized projected area"),
        ),
        keywords=("swelling ratio",),
        column_aliases=("swelling ratio",),
        analysis=(
            AnalysisSpec(
                "terminal_swelling_ratio",
                "last finite reported swelling ratio per curve; not inferred as equilibrium",
                ("swelling ratio",),
                "1",
            ),
        ),
        fixture_path="tests/fixtures/real_world/swelling_curve/Data_Core_Shell_Hydrogels.xlsx",
        fixture_status="ready",
        priority=55,
        reason=(
            "Use explicit swelling-curve intent for labeled time/Ai-A0 observations; gel fraction alone is not "
            "treated as swelling kinetics."
        ),
    ),
    _rule(
        "dma_frequency_sweep",
        "dma_frequency_sweep",
        "rheology_dma",
        "point_line",
        RHEOLOGY_X_FREQUENCY,
        AxisSpec(
            "Storage modulus",
            "Pa",
            "Storage modulus, E′ (Pa)",
            aliases=("E'", "storage modulus", "E′"),
            priority_labels=("E'", "Storage Modulus", "E′", "tanδ", "E\""),
            scale="log",
        ),
        keywords=("dmafreq", "dma frequency sweep", "E' frequency", "dmafrequencysweep"),
        path_keywords=("/dma_freq/", "dma frequency", "dma_frequency_sweep", "dma_frequency"),
        column_aliases=("angular frequency", "frequency", "storage modulus", "loss modulus", "tan delta"),
        experiment_families=("dma",),
        render_options=RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
        analysis=(
            AnalysisSpec(
                "terminal_storage_modulus_frequency",
                "highest-frequency E′ value",
                ("frequency", "storage modulus"),
                "Pa",
            ),
        ),
        fixture_path=(
            "tests/fixtures/real_world/dma_frequency_sweep/"
            "benchmark_vitrimer_20C_digitized.csv"
        ),
        fixture_status="ready",
        priority=30,
        reason="DMA frequency sweep (isothermal) with E′, E″, tanδ vs angular frequency.",
    ),
)

_RULE_BY_ID = {rule.rule_id: rule for rule in RULES}


def iter_rules() -> tuple[SemanticRule, ...]:
    return tuple(sorted(RULES, key=lambda rule: (rule.priority, rule.rule_id)))


def get_rule(rule_id: str) -> SemanticRule:
    try:
        return _RULE_BY_ID[rule_id]
    except KeyError as exc:
        known = ", ".join(sorted(_RULE_BY_ID))
        raise ValueError(f"Unknown material rule `{rule_id}`. Available rules: {known}.") from exc


def _is_ready_rule(rule: SemanticRule) -> bool:
    return rule.fixture_status == "ready"


def iter_public_rules(*, include_pending: bool = False) -> tuple[SemanticRule, ...]:
    rules = iter_rules()
    if include_pending:
        return rules
    return tuple(rule for rule in rules if _is_ready_rule(rule))


def list_rules_payload(*, include_pending: bool = False) -> dict[str, Any]:
    rules = iter_public_rules(include_pending=include_pending)
    all_rules = iter_rules()
    return {
        "kind": "sciplot_material_rules",
        "visibility": "all" if include_pending else "ready",
        "ready_count": sum(1 for rule in all_rules if _is_ready_rule(rule)),
        "pending_count": sum(1 for rule in all_rules if not _is_ready_rule(rule)),
        "rules": [
            {
                "rule_id": rule.rule_id,
                "semantic_family": rule.semantic_family,
                "recipe": rule.recipe,
                "template": rule.template,
                "x": rule.x_axis.display_label,
                "y": rule.y_axis.display_label,
                "fixture_status": rule.fixture_status,
                "priority": rule.priority,
            }
            for rule in rules
        ],
    }


def show_rule_payload(rule_id: str) -> dict[str, Any]:
    return get_rule(rule_id).to_payload()


def match_rule(
    *,
    evidence: str,
    compact_evidence: str,
    vendor_model: str | None = None,
    experiment_family: str | None = None,
    requested_rule_id: str | None = None,
) -> SemanticRule | None:
    if requested_rule_id:
        return get_rule(requested_rule_id)
    candidates: list[tuple[int, SemanticRule]] = []
    # Automatic production matching is deliberately narrower than the full
    # registry. Pending rules remain inspectable and explicitly addressable,
    # but they cannot silently enter the deterministic plotting path before a
    # fixture-backed acceptance promotes them to ``ready``.
    for rule in RULES:
        if not _is_ready_rule(rule):
            continue
        score = 0
        if vendor_model and vendor_model in rule.vendor_models:
            score += 100
        if experiment_family and experiment_family in rule.experiment_families:
            score += 40
        score += 35 * sum(1 for item in rule.keywords if _matches_rule_token(item, evidence, compact_evidence))
        # A rule-named source path or experiment folder is stronger evidence
        # than a generic vendor shape classifier (for example, every
        # strain/stress table can otherwise look like tensile data).
        score += 120 * sum(1 for item in rule.path_keywords if item.casefold() in evidence)
        score += 30 * sum(
            1 for item in rule.column_aliases if _matches_rule_token(item, evidence, compact_evidence)
        )
        adjusted_score = score - rule.priority
        if adjusted_score > 0:
            candidates.append((adjusted_score, rule))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _matches_rule_token(item: str, evidence: str, compact_evidence: str) -> bool:
    normalized = normalize_token(item)
    raw = str(item).strip().casefold()
    if raw.isascii() and normalized.isascii() and normalized.isalnum() and len(normalized) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(raw)}(?![a-z0-9])", evidence) is not None
    return normalized in compact_evidence


def semantic_payload_from_rule(
    rule: SemanticRule,
    *,
    confidence: float,
    reason: str | None = None,
    vendor_model: str | None = None,
    vendor_error: str | None = None,
) -> dict[str, Any]:
    payload = rule.to_payload()
    rule_ready = _is_ready_rule(rule)
    render_options = dict(rule.render_options)
    if rule.x_axis.scale != "linear":
        render_options.setdefault("xscale", rule.x_axis.scale)
    if rule.y_axis.scale != "linear":
        render_options.setdefault("yscale", rule.y_axis.scale)
    if rule.x_axis.reverse:
        render_options.setdefault("reverse_x", True)
    if rule.rule_id == "ftir_spectrum":
        render_options.setdefault("x_min", 400.0)
        render_options.setdefault("x_max", 4000.0)
        render_options.setdefault("x_tick_density", "auto")
    return {
        "rule_id": rule.rule_id,
        "semantic_family": rule.semantic_family,
        "recommended_recipe": rule.recipe,
        "template": rule.template,
        "render_options": render_options,
        "confidence": confidence if rule_ready else 0.0,
        "reason": (
            reason
            or rule.reason
            or (
                f"Material rule `{rule.rule_id}` is pending fixture-backed acceptance."
                if not rule_ready
                else f"Matched material rule `{rule.rule_id}`."
            )
        ),
        "needs_ai_intervention": not rule_ready,
        "production_status": "ready" if rule_ready else "needs_rule_repair",
        "rule_readiness": rule.fixture_status,
        "vendor_model": vendor_model,
        "vendor_error": vendor_error,
        "axis_plan": payload["axis_plan"],
        "unit_plan": payload["unit_plan"],
        "analysis_plan": payload["analysis_plan"],
        "available_metrics": payload["available_metrics"],
        "experiment_recommendation": experiment_recommendation_payload(
            rule_id=rule.rule_id,
            semantic_family=rule.semantic_family,
            experiment_type_id=rule.rule_id,
        ),
        "missing_requirements": (
            []
            if rule_ready
            else [
                "fixture_backed_rule_acceptance",
                "deterministic_semantic_rule_promotion",
            ]
        ),
        "rule_priority": rule.priority,
    }


def _write_metrics_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ("metric", "value", "unit", "status", "reason")
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _metric(
    metric: str,
    value: float | str | None,
    unit: str = "",
    status: str = "ok",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": "" if value is None else value,
        "unit": unit,
        "status": status,
        "reason": reason,
    }


def _read_labeled_paired_curve_table(
    path: Path,
    *,
    y_tokens: tuple[str, ...] = (),
) -> list[tuple[str, pd.DataFrame]]:
    raw = pd.read_csv(path, header=None)
    if raw.shape[0] < 4:
        return []
    series: list[tuple[str, pd.DataFrame]] = []
    for col in range(0, raw.shape[1] - 1, 2):
        y_header = normalize_token(raw.iat[0, col + 1])
        if y_tokens and not any(normalize_token(token) in y_header for token in y_tokens):
            continue
        data = raw.iloc[3:, [col, col + 1]].apply(pd.to_numeric, errors="coerce").dropna()
        if not data.empty:
            data.columns = ["x", "y"]
            sample = str(raw.iat[2, col]).strip()
            if not sample or sample.casefold() == "nan":
                sample = f"series_{col // 2 + 1}"
            series.append((sample, data.reset_index(drop=True)))
    return series


def _read_paired_curve_table(path: Path) -> list[pd.DataFrame]:
    return [frame for _sample, frame in _read_labeled_paired_curve_table(path)]


def tensile_curve_metric_values(
    points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    *,
    x_unit: str = "%",
    reported: dict[str, float] | None = None,
) -> dict[str, float | str]:
    """Return publication-safe tensile metrics from one engineering curve.

    Instrument-reported strength, break strain, and the programmed low-strain
    modulus take precedence when present.  Derived modulus values convert
    percent strain to a unitless fraction, and toughness is reported as
    MJ/m3 rather than the intermediate MPa-percent integral.
    """

    data = pd.DataFrame(points, columns=["strain", "stress"])
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    if data.empty:
        raise ValueError("A tensile metric calculation needs at least one finite stress-strain point.")
    data = data.sort_values("strain", kind="stable").drop_duplicates(subset="strain", keep="last")
    reported = reported or {}

    reported_strength = reported.get("strength_MPa")
    strength = (
        float(reported_strength)
        if reported_strength is not None and np.isfinite(float(reported_strength))
        else float(data["stress"].max())
    )
    strength_source = "instrument_report" if reported_strength is not None else "curve_maximum"

    reported_break = reported.get("strain_at_break_percent")
    strain_at_break = (
        float(reported_break)
        if reported_break is not None and np.isfinite(float(reported_break))
        else float(data["strain"].iloc[-1])
    )
    break_source = "instrument_report" if reported_break is not None else "curve_terminal_point"

    unit_token = str(x_unit or "%").strip().casefold()
    strain_is_percent = "%" in unit_token or "percent" in unit_token
    strain_fraction_factor = 0.01 if strain_is_percent else 1.0
    fit_low, fit_high = ((0.05, 0.25) if strain_is_percent else (0.0005, 0.0025))
    fit = data[(data["strain"] >= fit_low) & (data["strain"] <= fit_high)]
    if len(fit) < 2 or fit["strain"].nunique() < 2:
        fit = data[(data["strain"] >= 0.0) & (data["strain"] <= fit_high)]
    if len(fit) < 2 or fit["strain"].nunique() < 2:
        fit = data.iloc[: min(25, len(data))]
    derived_modulus = float("nan")
    if len(fit) >= 2 and fit["strain"].nunique() >= 2:
        try:
            slope = float(
                np.polyfit(
                    fit["strain"].to_numpy(dtype=float),
                    fit["stress"].to_numpy(dtype=float),
                    deg=1,
                )[0]
            )
            derived_modulus = slope / strain_fraction_factor
        except (ValueError, np.linalg.LinAlgError):
            derived_modulus = float("nan")
    reported_modulus = reported.get("modulus_MPa")
    modulus = (
        float(reported_modulus)
        if reported_modulus is not None and np.isfinite(float(reported_modulus))
        else derived_modulus
    )
    modulus_source = "instrument_report_0.05_to_0.25_percent" if reported_modulus is not None else "curve_fit"

    clipped = data[data["strain"] <= strain_at_break].copy()
    after_break = data[data["strain"] > strain_at_break]
    if not clipped.empty and not after_break.empty and float(clipped["strain"].iloc[-1]) < strain_at_break:
        left = clipped.iloc[-1]
        right = after_break.iloc[0]
        x0, y0 = float(left["strain"]), float(left["stress"])
        x1, y1 = float(right["strain"]), float(right["stress"])
        if x1 > x0:
            y_break = y0 + (strain_at_break - x0) * (y1 - y0) / (x1 - x0)
            clipped = pd.concat(
                [clipped, pd.DataFrame([{"strain": strain_at_break, "stress": y_break}])],
                ignore_index=True,
            )
    if len(clipped) >= 2:
        toughness = float(
            np.trapezoid(
                clipped["stress"].to_numpy(dtype=float),
                clipped["strain"].to_numpy(dtype=float) * strain_fraction_factor,
            )
        )
    else:
        toughness = float("nan")

    if reported_break is not None and float(data["strain"].iloc[-1]) >= strain_at_break:
        toughness_source = "curve_integral_to_reported_break"
    elif reported_break is not None:
        toughness_source = "curve_integral_over_available_excerpt_before_reported_break"
    else:
        toughness_source = "curve_integral"

    return {
        "strength_MPa": strength,
        "strength_source": strength_source,
        "strain_at_break_percent": strain_at_break,
        "strain_at_break_source": break_source,
        "modulus_MPa": modulus,
        "modulus_source": modulus_source,
        "toughness_MJ_m3": toughness,
        "toughness_source": toughness_source,
    }


def _interpolated_threshold_time(data: pd.DataFrame, threshold: float = 0.5) -> float | None:
    below = data[data["y"] <= threshold]
    if below.empty:
        return None
    index = int(below.index[0])
    if index == 0:
        return float(data.loc[index, "x"])
    x0, y0 = float(data.loc[index - 1, "x"]), float(data.loc[index - 1, "y"])
    x1, y1 = float(data.loc[index, "x"]), float(data.loc[index, "y"])
    if y1 == y0:
        return x1
    return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)


def _stress_relaxation_metrics(processed_source: Path) -> list[dict[str, Any]]:
    frames = _read_paired_curve_table(processed_source)
    if not frames:
        return [_metric("final_normalized_value", None, "sigma/sigma0", "skipped", "No normalized curve found.")]
    data = frames[0]
    final_value = float(data["y"].iloc[-1])
    t50 = _interpolated_threshold_time(data, 0.5)
    return [
        _metric("final_normalized_value", final_value, "sigma/sigma0"),
        _metric(
            "t50_s",
            t50,
            "s",
            "ok" if t50 is not None else "skipped",
            "Curve never reached 0.5." if t50 is None else "",
        ),
    ]


def _creep_metrics(processed_source: Path) -> list[dict[str, Any]]:
    frames = _read_paired_curve_table(processed_source)
    if not frames:
        return [_metric("final_compliance", None, "1/Pa", "skipped", "No creep curve found.")]
    return [
        _metric("final_compliance", float(frames[0]["y"].iloc[-1]), "1/Pa"),
        _metric("recovery_ratio", None, "fraction", "skipped", "Recovery segment not detected."),
    ]


def _tensile_summary_metrics(summary_source: Path) -> list[dict[str, Any]]:
    summary = pd.read_csv(summary_source)
    required = {
        "sample",
        "strength_MPa",
        "strain_at_break_percent",
        "modulus_MPa",
        "toughness_MJ_m3",
    }
    if not required <= set(summary.columns):
        return []
    samples = [str(value) for value in summary["sample"].dropna().drop_duplicates().tolist()]
    rows: list[dict[str, Any]] = []
    metric_contract = (
        ("strength_MPa", "MPa", "strength_iqr_MPa"),
        ("strain_at_break_percent", "%", "strain_at_break_iqr_percent"),
        ("modulus_MPa", "MPa", "modulus_iqr_MPa"),
        ("toughness_MJ_m3", "MJ/m3", "toughness_iqr_MJ_m3"),
    )
    for sample in samples:
        group = summary[summary["sample"].astype(str) == sample]
        suffix = "" if len(samples) == 1 else f"[{sample}]"
        rows.append(_metric(f"replicate_count{suffix}", int(len(group)), "count"))
        for metric_name, unit, iqr_name in metric_contract:
            values = pd.to_numeric(group[metric_name], errors="coerce").dropna().to_numpy(dtype=float)
            if values.size == 0:
                rows.append(_metric(f"{metric_name}{suffix}", None, unit, "skipped", "No finite replicate metric."))
                rows.append(_metric(f"{iqr_name}{suffix}", None, unit, "skipped", "No finite replicate metric."))
                continue
            reason = f"Median of {values.size} retained raw specimen value(s)."
            rows.append(_metric(f"{metric_name}{suffix}", float(np.median(values)), unit, reason=reason))
            if values.size >= 2:
                iqr = float(np.quantile(values, 0.75) - np.quantile(values, 0.25))
                rows.append(_metric(f"{iqr_name}{suffix}", iqr, unit))
            else:
                rows.append(
                    _metric(
                        f"{iqr_name}{suffix}",
                        None,
                        unit,
                        "skipped",
                        "At least two specimens are required for an IQR.",
                    )
                )
    return rows


def _tensile_metrics(processed_source: Path) -> list[dict[str, Any]]:
    summary_source = processed_source.with_name(f"{processed_source.stem}_summary.csv")
    if summary_source.exists():
        summary_rows = _tensile_summary_metrics(summary_source)
        if summary_rows:
            return summary_rows
    frames = _read_paired_curve_table(processed_source)
    rows: list[dict[str, Any]] = []
    if not frames:
        return [_metric("strength_MPa", None, "MPa", "skipped", "No tensile curve found.")]
    data = frames[0].replace([np.inf, -np.inf], np.nan).dropna()
    values = tensile_curve_metric_values(
        list(zip(data["x"].astype(float), data["y"].astype(float), strict=True)),
        x_unit="%",
    )
    modulus = float(values["modulus_MPa"])
    toughness = float(values["toughness_MJ_m3"])
    modulus_status = "ok" if np.isfinite(modulus) else "skipped"
    modulus_reason = "" if modulus_status == "ok" else "Low-strain fit did not have enough distinct finite points."
    rows.extend(
        [
            _metric("strength_MPa", float(values["strength_MPa"]), "MPa"),
            _metric("strain_at_break_percent", float(values["strain_at_break_percent"]), "%"),
            _metric(
                "modulus_MPa",
                modulus if modulus_status == "ok" else None,
                "MPa",
                modulus_status,
                modulus_reason,
            ),
            _metric(
                "toughness_MJ_m3",
                toughness if np.isfinite(toughness) else None,
                "MJ/m3",
                "ok" if np.isfinite(toughness) else "skipped",
                "" if np.isfinite(toughness) else "Curve did not contain two points before break.",
            ),
        ]
    )
    return rows


def _torque_metrics(processed_source: Path) -> list[dict[str, Any]]:
    raw = pd.read_csv(processed_source, header=None)
    rows: list[dict[str, Any]] = []
    if raw.shape[0] < 4:
        return [
            _metric(
                "selected_event_mean_torque_Nm_by_sample",
                None,
                "N·m",
                "skipped",
                "No selected torque event found.",
            )
        ]
    for col in range(0, raw.shape[1] - 1, 2):
        sample = str(raw.iat[2, col]).strip() or f"series_{col // 2 + 1}"
        values = pd.to_numeric(raw.iloc[3:, col + 1], errors="coerce").dropna()
        metric_name = f"selected_event_mean_torque_Nm[{sample}]"
        if values.empty:
            rows.append(_metric(metric_name, None, "N·m", "skipped", "No finite torque values found."))
        else:
            rows.append(_metric(metric_name, float(values.mean()), "N·m"))
    return rows or [
        _metric(
            "selected_event_mean_torque_Nm_by_sample",
            None,
            "N·m",
            "skipped",
            "No selected torque event found.",
        )
    ]


def _raw_table(path: Path) -> pd.DataFrame:
    return read_raw_table(path).dropna(how="all").dropna(axis=1, how="all")


def _tga_metrics(source_path: Path) -> list[dict[str, Any]]:
    raw = _raw_table(source_path)
    tokens = [[normalize_token(value) for value in row] for row in raw.astype(str).values.tolist()]
    temp_col: int | None = None
    mass_col: int | None = None
    for row in tokens:
        for index, token in enumerate(row):
            if temp_col is None and "temp" in token:
                temp_col = index
            if mass_col is None and ("weight" in token or "mass" in token):
                mass_col = index
    if temp_col is None or mass_col is None:
        return [_metric("residual_mass_percent", None, "%", "skipped", "Temperature/mass columns not found.")]
    data = raw.iloc[:, [temp_col, mass_col]].apply(pd.to_numeric, errors="coerce").dropna()
    if data.empty:
        return [_metric("residual_mass_percent", None, "%", "skipped", "No numeric TGA data found.")]
    data.columns = ["temperature", "mass"]
    initial = float(data["mass"].iloc[0])
    residual = float(data["mass"].iloc[-1])
    rows = [_metric("residual_mass_percent", residual, "%")]
    for loss, metric in ((5, "t5_temperature_C"), (10, "t10_temperature_C")):
        threshold = initial - loss
        below = data[data["mass"] <= threshold]
        if below.empty:
            rows.append(_metric(metric, None, "C", "skipped", f"Mass never reached {threshold:g} %."))
        else:
            rows.append(_metric(metric, float(below["temperature"].iloc[0]), "C"))
    return rows


def _generic_peak_metrics(source_path: Path, *, metric_name: str, x_unit: str) -> list[dict[str, Any]]:
    raw = _raw_table(source_path)
    numeric = raw.apply(pd.to_numeric, errors="coerce")
    best: tuple[float, float] | None = None
    for col in range(0, numeric.shape[1] - 1):
        pair = numeric.iloc[:, [col, col + 1]].dropna()
        if pair.empty:
            continue
        idx = pair.iloc[:, 1].abs().idxmax()
        candidate = (float(pair.loc[idx].iloc[0]), float(abs(pair.loc[idx].iloc[1])))
        if best is None or candidate[1] > best[1]:
            best = candidate
    if best is None:
        return [_metric(metric_name, None, x_unit, "skipped", "No numeric peak trace found.")]
    return [_metric(metric_name, best[0], x_unit)]


def _terminal_y_metrics(
    source_path: Path,
    *,
    metric_name: str,
    y_unit: str,
    y_tokens: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(source_path, y_tokens=y_tokens)
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = data.replace([np.inf, -np.inf], np.nan).dropna().sort_values("x", kind="stable")
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if finite.empty:
            rows.append(_metric(f"{metric_name}{suffix}", None, y_unit, "skipped", "No finite curve found."))
            continue
        rows.append(_metric(f"{metric_name}{suffix}", float(finite["y"].iloc[-1]), y_unit))
    return rows or [_metric(metric_name, None, y_unit, "skipped", "No finite curve found.")]


def _peak_y_metrics(
    source_path: Path,
    *,
    metric_name: str,
    y_unit: str,
    magnitude: bool = False,
    y_tokens: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(source_path, y_tokens=y_tokens)
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = data.replace([np.inf, -np.inf], np.nan).dropna()
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if finite.empty:
            rows.append(_metric(f"{metric_name}{suffix}", None, y_unit, "skipped", "No finite curve found."))
            continue
        value = float(finite["y"].abs().max() if magnitude else finite["y"].max())
        rows.append(_metric(f"{metric_name}{suffix}", value, y_unit))
    return rows or [_metric(metric_name, None, y_unit, "skipped", "No finite curve found.")]


def _dsc_metrics(source_path: Path) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(source_path, y_tokens=("heat flow", "dsc"))
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values("x", kind="stable")
            .drop_duplicates(subset="x", keep="last")
        )
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if len(finite) < 3:
            reason = "At least three finite temperature/heat-flow points are required."
            rows.append(_metric(f"tg_candidate_C{suffix}", None, "C", "skipped", reason))
            rows.append(_metric(f"peak_temperature_C{suffix}", None, "C", "skipped", reason))
            continue
        temperatures = finite["x"].to_numpy(dtype=float)
        heat_flow = finite["y"].to_numpy(dtype=float)
        slope = np.gradient(heat_flow, temperatures)
        slope_index = int(np.nanargmax(np.abs(slope)))
        peak_index = int(np.nanargmax(np.abs(heat_flow)))
        rows.append(
            _metric(
                f"tg_candidate_C{suffix}",
                float(temperatures[slope_index]),
                "C",
                reason=(
                    "Largest absolute heat-flow slope; this is an algorithmic candidate, "
                    "not a confirmed glass-transition assignment."
                ),
            )
        )
        rows.append(
            _metric(
                f"peak_temperature_C{suffix}",
                float(temperatures[peak_index]),
                "C",
                reason="Temperature of the largest absolute recorded heat-flow excursion.",
            )
        )
    if rows:
        return rows
    return [
        _metric("tg_candidate_C", None, "C", "skipped", "No finite DSC curve found."),
        _metric("peak_temperature_C", None, "C", "skipped", "No finite DSC curve found."),
    ]


def _swelling_metrics(source_path: Path) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(source_path, y_tokens=("swelling ratio",))
    if not series:
        return [_metric("terminal_swelling_ratio", None, "1", "skipped", "No prepared swelling curves found.")]
    multiple = len(series) > 1
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        metric_name = f"terminal_swelling_ratio[{sample}]" if multiple else "terminal_swelling_ratio"
        rows.append(
            _metric(
                metric_name,
                float(data["y"].iloc[-1]),
                "1",
                reason="Last finite reported observation; no equilibrium plateau is inferred.",
            )
        )
    return rows


def _impact_metric_tables(processed_source: Path) -> list[tuple[str, pd.DataFrame]]:
    """Read every deterministic impact table represented by one source file."""

    suffix = processed_source.suffix.casefold()
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        workbook = pd.ExcelFile(processed_source)
        return [
            (
                str(sheet_name),
                pd.read_excel(processed_source, sheet_name=sheet_name, header=None)
                .dropna(how="all")
                .dropna(axis=1, how="all"),
            )
            for sheet_name in workbook.sheet_names
        ]
    return [("", read_raw_table(processed_source).dropna(how="all").dropna(axis=1, how="all"))]


def _impact_metrics(processed_source: Path) -> list[dict[str, Any]]:
    grouped_values: dict[tuple[str, str], tuple[str, list[float]]] = {}
    for table_name, raw in _impact_metric_tables(processed_source):
        if raw.shape[0] < 4:
            continue
        for column in range(raw.shape[1]):
            sample = str(raw.iat[2, column]).strip()
            if not sample or sample.casefold() == "nan":
                sample = f"Sample {column + 1}"
            unit = str(raw.iat[1, column]).strip()
            if not unit or unit.casefold() == "nan":
                unit = "kJ/m2"
            values = pd.to_numeric(raw.iloc[3:, column], errors="coerce").dropna().to_numpy(dtype=float)
            if values.size == 0:
                continue
            key = (table_name, sample)
            existing_unit, existing_values = grouped_values.setdefault(key, (unit, []))
            existing_values.extend(float(value) for value in values)
            grouped_values[key] = (existing_unit, existing_values)

    if not grouped_values:
        return [
            _metric(
                "impact_group_n",
                None,
                "count",
                "skipped",
                "The prepared impact table did not contain categorical raw values.",
            )
        ]

    sample_occurrences: dict[str, int] = {}
    for _table_name, sample in grouped_values:
        sample_occurrences[sample] = sample_occurrences.get(sample, 0) + 1

    rows: list[dict[str, Any]] = []
    for (table_name, sample), (unit, raw_values) in grouped_values.items():
        label = f"{sample} ({table_name})" if table_name and sample_occurrences[sample] > 1 else sample
        values = np.asarray(raw_values, dtype=float)
        rows.append(_metric(f"impact_group_n[{label}]", int(values.size), "count"))
        rows.append(_metric(f"impact_group_median[{label}]", float(np.quantile(values, 0.5)), unit))
        if values.size >= 2:
            iqr = float(np.quantile(values, 0.75) - np.quantile(values, 0.25))
            rows.append(_metric(f"impact_group_iqr[{label}]", iqr, unit))
        else:
            rows.append(
                _metric(
                    f"impact_group_iqr[{label}]",
                    None,
                    unit,
                    "skipped",
                    "At least two raw replicates are required for an IQR summary; the raw point is retained.",
                )
            )
    if rows:
        return rows
    return [
        _metric(
            "impact_group_n",
            None,
            "count",
            "skipped",
            "The prepared impact table did not contain finite raw values.",
        )
    ]


def _analysis_metric_name(semantic: dict[str, Any], fallback: str) -> str:
    analysis_plan = semantic.get("analysis_plan") or []
    if analysis_plan and isinstance(analysis_plan[0], dict):
        metric = str(analysis_plan[0].get("metric") or "").strip()
        if metric:
            return metric
    return fallback


def compute_analysis_metrics(
    *,
    source_path: Path,
    processed_source: Path | None,
    semantic: dict[str, Any],
    output_dir: Path,
) -> list[dict[str, Any]]:
    rule_id = str(semantic.get("rule_id") or "")
    processed = processed_source if processed_source and processed_source.exists() else None
    canonical_source = processed or source_path
    if rule_id == "rheology_stress_relaxation" and processed is not None:
        rows = _stress_relaxation_metrics(processed)
    elif rule_id == "rheology_creep" and processed is not None:
        rows = _creep_metrics(processed)
    elif rule_id == "tensile_curve" and processed is not None:
        rows = _tensile_metrics(processed)
    elif rule_id == "torque_curve" and processed is not None:
        rows = _torque_metrics(processed)
    elif rule_id == "tga_curve":
        rows = _tga_metrics(canonical_source)
    elif rule_id == "dsc_curve":
        rows = _dsc_metrics(canonical_source)
    elif rule_id == "dma_frequency_sweep":
        rows = _terminal_y_metrics(
            canonical_source,
            metric_name="terminal_storage_modulus_frequency",
            y_unit=semantic["axis_plan"]["y"]["canonical_unit"],
            y_tokens=("storage modulus", "E′", "E'"),
        )
    elif rule_id == "compression_curve":
        rows = _peak_y_metrics(
            canonical_source,
            metric_name="peak_compressive_stress_MPa",
            y_unit=semantic["axis_plan"]["y"]["canonical_unit"],
            magnitude=True,
            y_tokens=("stress",),
        )
    elif rule_id == "flexural_curve":
        rows = _peak_y_metrics(
            canonical_source,
            metric_name="peak_flexural_stress_MPa",
            y_unit=semantic["axis_plan"]["y"]["canonical_unit"],
            y_tokens=("stress",),
        )
    elif rule_id in {
        "rheology_time_sweep",
        "rheology_strain_sweep",
        "rheology_stress_sweep",
        "dma_temperature_sweep",
        "dtg_curve",
    }:
        rows = _generic_peak_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "peak_response_position"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
        )
    elif rule_id == "swelling_curve":
        rows = _swelling_metrics(canonical_source)
    elif rule_id == "impact_metric" and processed is not None:
        rows = _impact_metrics(processed)
    elif rule_id in {"ftir_spectrum", "uvvis_spectrum"}:
        rows = _generic_peak_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "strongest_peak_position"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
        )
    elif rule_id in {"xrd_pattern", "saxs_profile"}:
        rows = _generic_peak_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "main_scattering_peak_q"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
        )
    elif rule_id == "gpc_sec_chromatogram":
        rows = _generic_peak_metrics(source_path, metric_name="peak_elution_time_min", x_unit="min")
    else:
        rows = [
            _metric(
                item["metric"],
                None,
                item.get("unit", ""),
                "skipped",
                "Metric is registered but no deterministic calculator is available yet.",
            )
            for item in semantic.get("analysis_plan", [])
        ]
    _write_metrics_csv(rows, output_dir / "tables" / "analysis_metrics.csv")
    return rows


JOURNAL_PRESETS: dict[str, dict[str, Any]] = {
    "nature": {
        "label": "SciPlot publication layout (legacy Nature alias)",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "nature",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": (
            "Legacy compatibility alias. The 60/120/180 mm values are SciPlot panel widths, "
            "not verified Nature column widths or a compliance claim."
        ),
        "verified_compliance": False,
        "compatibility_alias": True,
        "publication_profile_id": "sciplot_composite_183_v1",
    },
    "acs": {
        "label": "ACS",
        "sizes": ("60x55", "120x55"),
        "style_preset": "acs",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 120,
        "description": "Legacy unverified SciPlot style hint; not an ACS submission-compliance profile.",
        "verified_compliance": False,
        "compatibility_alias": True,
        "publication_profile_id": "sciplot_composite_183_v1",
    },
    "science": {
        "label": "Science",
        "sizes": ("60x55", "120x55"),
        "style_preset": "science",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 120,
        "description": "Legacy unverified SciPlot style hint; not a Science submission-compliance profile.",
        "verified_compliance": False,
        "compatibility_alias": True,
        "publication_profile_id": "sciplot_composite_183_v1",
    },
    "elsevier": {
        "label": "Elsevier",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "elsevier",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": "Legacy unverified SciPlot style hint; not an Elsevier submission-compliance profile.",
        "verified_compliance": False,
        "compatibility_alias": True,
        "publication_profile_id": "sciplot_composite_183_v1",
    },
    "wiley": {
        "label": "Wiley",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "wiley",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": "Legacy unverified SciPlot style hint; not a Wiley submission-compliance profile.",
        "verified_compliance": False,
        "compatibility_alias": True,
        "publication_profile_id": "sciplot_composite_183_v1",
    },
    "acs_macromolecules": {
        "label": "Macromolecules (ACS)",
        "sizes": ("60x55", "120x55"),
        "style_preset": "acs",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 120,
        "description": "Legacy unverified SciPlot style hint; not a Macromolecules compliance profile.",
        "verified_compliance": False,
        "compatibility_alias": True,
        "publication_profile_id": "sciplot_composite_183_v1",
    },
    "polymer": {
        "label": "Polymer (Elsevier)",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "elsevier",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": "Legacy unverified SciPlot style hint; not a Polymer submission-compliance profile.",
        "verified_compliance": False,
        "compatibility_alias": True,
        "publication_profile_id": "sciplot_composite_183_v1",
    },
}


def list_journal_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": preset_id,
            "label": preset["label"],
            "description": preset["description"],
            "sizes": list(preset["sizes"]),
            "style_preset": preset["style_preset"],
            "palette_preset": preset["palette_preset"],
            "verified_compliance": preset["verified_compliance"],
            "compatibility_alias": preset["compatibility_alias"],
            "publication_profile_id": preset["publication_profile_id"],
        }
        for preset_id, preset in JOURNAL_PRESETS.items()
    ]


def get_journal_preset(preset_id: str) -> dict[str, Any]:
    if preset_id not in JOURNAL_PRESETS:
        known = ", ".join(sorted(JOURNAL_PRESETS))
        raise ValueError(f"Unknown journal preset `{preset_id}`. Available: {known}.")
    return dict(JOURNAL_PRESETS[preset_id])


__all__ = [
    "AnalysisSpec",
    "AxisSpec",
    "SemanticRule",
    "UnitRule",
    "compute_analysis_metrics",
    "convert_value",
    "format_unit_label",
    "get_rule",
    "iter_public_rules",
    "iter_rules",
    "list_rules_payload",
    "match_rule",
    "normalize_token",
    "semantic_payload_from_rule",
    "show_rule_payload",
    "tensile_curve_metric_values",
]
