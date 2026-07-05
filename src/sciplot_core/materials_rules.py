from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sciplot_core._bootstrap import ensure_legacy_core
from sciplot_core._constants import _DEFAULT_RENDER_OPTIONS
from sciplot_core._utils import token as _utils_token
from sciplot_core.policy import (
    DEFAULT_PALETTE_PRESET,
    FTIR_SPECTRUM_RENDER_OPTIONS,
    NMR_SPECTRUM_RENDER_OPTIONS,
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
    fixture_status: str = "ready"
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


_POINT_LINE_LOG = {**_DEFAULT_RENDER_OPTIONS, "xscale": "log", "yscale": "log", "reverse_x": False}

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
    fixture_status: str = "ready",
    priority: int = 100,
    reason: str = "",
) -> SemanticRule:
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
        render_options=render_options or _DEFAULT_RENDER_OPTIONS,
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
    "Angular frequency (rad/s)",
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
        render_options=_POINT_LINE_LOG,
        analysis=(AnalysisSpec("terminal_modulus", "last finite G' value", ("G'",), "Pa"),),
        fixture_path="tests/fixtures/polymer_corpus/rheology_dma/rheology_frequency_excerpt.csv",
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
        ),
        keywords=("temperaturesweep", "temperature", "温度"),
        path_keywords=("/temp/", "temperature"),
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
        fixture_path="tests/fixtures/materials_rules/rheology_temperature_sweep.csv",
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
        column_aliases=("time", "storage modulus", "modulus"),
        analysis=(AnalysisSpec("peak_modulus_time_s", "time at maximum modulus", ("time", "modulus"), "s"),),
        fixture_path="tests/fixtures/materials_rules/rheology_time_sweep.csv",
        priority=28,
    ),
    _rule(
        "rheology_strain_sweep",
        "rheology_strain_sweep",
        "rheology_dma",
        "point_line",
        STRAIN_AXIS,
        AxisSpec("Modulus", "Pa", "Modulus (Pa)", aliases=("modulus", "G'", "G\"")),
        keywords=("strainsweep", "amplitude sweep"),
        path_keywords=("rheology_strain_sweep", "strain_sweep"),
        column_aliases=("strain", "storage modulus", "modulus"),
        analysis=(
            AnalysisSpec("peak_modulus_strain_percent", "strain at maximum modulus", ("strain", "modulus"), "%"),
        ),
        fixture_path="tests/fixtures/materials_rules/rheology_strain_sweep.csv",
        priority=28,
    ),
    _rule(
        "rheology_stress_sweep",
        "rheology_stress_sweep",
        "rheology_dma",
        "point_line",
        AxisSpec("Stress", "Pa", "Stress (Pa)", aliases=("stress", "shear stress")),
        AxisSpec("Modulus", "Pa", "Modulus (Pa)", aliases=("modulus", "G'", "G\"")),
        keywords=("stresssweep", "stress sweep"),
        path_keywords=("rheology_stress_sweep", "stress_sweep"),
        column_aliases=("stress", "storage modulus", "modulus"),
        analysis=(AnalysisSpec("peak_modulus_stress_Pa", "stress at maximum modulus", ("stress", "modulus"), "Pa"),),
        fixture_path="tests/fixtures/materials_rules/rheology_stress_sweep.csv",
        priority=28,
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
        fixture_path="tests/fixtures/semantic/creep_utf16.csv",
        priority=30,
    ),
    _rule(
        "rheology_stress_relaxation",
        "rheology_stress_relaxation",
        "stress_relaxation",
        "curve",
        TIME_AXIS,
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
        fixture_path="tests/fixtures/semantic/stress_relaxation_utf16.csv",
        priority=25,
    ),
    _rule(
        "tensile_curve",
        "tensile_curve",
        "tensile",
        "curve",
        STRAIN_AXIS,
        STRESS_AXIS,
        keywords=("tensile", "拉伸", "结果表格2"),
        path_keywords=("tensile", ".is_tens_exports"),
        vendor_models=("tensile_curve",),
        analysis=(
            AnalysisSpec("modulus_MPa", "low-strain linear slope", ("strain", "stress"), "MPa"),
            AnalysisSpec("strength_MPa", "maximum stress", ("stress",), "MPa"),
            AnalysisSpec("strain_at_break_percent", "last strain", ("strain",), "%"),
            AnalysisSpec("toughness_MPa_percent", "area under stress-strain curve", ("strain", "stress"), "MPa %"),
        ),
        fixture_path="tests/fixtures/semantic/Specimen.is_tens_Exports",
        priority=40,
    ),
    _rule(
        "torque_curve",
        "torque_curve",
        "rheology_dma",
        "curve",
        TIME_AXIS,
        TORQUE_AXIS,
        keywords=("screwtorque", "screw torque", "转矩"),
        path_keywords=("torque", "转矩"),
        column_aliases=("screw torque", "转矩"),
        analysis=(
            AnalysisSpec(
                "final_segment_mean_torque_Nm",
                "mean torque in the processed final segment",
                ("Screw Torque",),
                "N·m",
            ),
        ),
        render_options=dict(TORQUE_CURVE_RENDER_OPTIONS),
        fixture_status="pending",
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
        column_aliases=("strain", "stress"),
        analysis=(
            AnalysisSpec("peak_compressive_stress_MPa", "maximum compressive stress", ("strain", "stress"), "MPa"),
        ),
        fixture_path="tests/fixtures/materials_rules/compression_curve.csv",
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
        column_aliases=("strain", "stress"),
        analysis=(AnalysisSpec("peak_flexural_stress_MPa", "maximum flexural stress", ("strain", "stress"), "MPa"),),
        fixture_path="tests/fixtures/materials_rules/flexural_curve.csv",
        priority=34,
    ),
    _rule(
        "impact_metric",
        "impact_metric",
        "metrics_swelling",
        "box",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec("Impact strength", "kJ/m2", "Impact strength (kJ/m$^2$)", aliases=("impact strength", "冲击")),
        keywords=("impact", "冲击"),
        analysis=(AnalysisSpec("max_impact_strength", "maximum replicate/metric value", ("impact",), "kJ/m2"),),
        fixture_path="tests/fixtures/polymer_corpus/impact_metrics/foam_impact_metrics.csv",
        priority=5,
    ),
    _rule(
        "fracture_metric",
        "fracture_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample"),
        AxisSpec("Fracture toughness", "MPa.m^0.5", "Fracture toughness", aliases=("fracture", "KIC")),
        keywords=("fracture", "toughness", "KIC"),
        fixture_status="pending",
        priority=85,
    ),
    _rule(
        "fatigue_cycle_metric",
        "fatigue_cycle_metric",
        "metrics_swelling",
        "point_line",
        AxisSpec("Cycle", "1", "Cycle", aliases=("cycle", "cycles")),
        AxisSpec("Property retention", "%", "Property retention (%)", aliases=("retention",)),
        keywords=("fatigue", "cycle"),
        fixture_status="pending",
        priority=85,
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
        fixture_path="tests/fixtures/materials_rules/dsc_curve.csv",
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
        fixture_path="tests/fixtures/polymer_corpus/thermal_dsc_tga/evoh_ega_excerpt.csv",
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
        fixture_path="tests/fixtures/materials_rules/dtg_curve.csv",
        priority=32,
    ),
    _rule(
        "dma_temperature_sweep",
        "dma_temperature_sweep",
        "rheology_dma",
        "point_line",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec("Storage modulus", "Pa", "Storage modulus, E′ (Pa)", aliases=("E'", "storage modulus", "tan delta")),
        keywords=("dma", "tanδ", "tandelta"),
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
        fixture_path="tests/fixtures/materials_rules/dma_temperature_sweep.csv",
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
        fixture_path="tests/fixtures/polymer_corpus/spectroscopy_ftir_uvvis/ftir_plastics_pet_excerpt.csv",
        priority=50,
    ),
    _rule(
        "raman_spectrum",
        "raman_spectrum",
        "spectroscopy",
        "curve",
        AxisSpec("Raman shift", "cm^-1", "Raman shift (cm$^{-1}$)"),
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)"),
        keywords=("raman",),
        fixture_status="pending",
        priority=80,
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
        fixture_path="tests/fixtures/materials_rules/uvvis_spectrum.csv",
        priority=36,
    ),
    _rule(
        "nmr_spectrum",
        "nmr_spectrum",
        "spectroscopy",
        "stacked_curve",
        AxisSpec("Chemical shift", "ppm", "Chemical shift (ppm)", reverse=True),
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)"),
        keywords=("nmr", "ppm"),
        render_options=dict(NMR_SPECTRUM_RENDER_OPTIONS),
        fixture_status="pending",
        priority=80,
    ),
    _rule(
        "xps_spectrum",
        "xps_spectrum",
        "spectroscopy",
        "curve",
        AxisSpec("Binding energy", "eV", "Binding energy (eV)", reverse=True),
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)"),
        keywords=("xps", "bindingenergy"),
        fixture_status="pending",
        priority=80,
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
        fixture_path="tests/fixtures/materials_rules/xrd_pattern.csv",
        priority=46,
    ),
    _rule(
        "waxs_pattern",
        "waxs_pattern",
        "scattering",
        "curve",
        AxisSpec("q", "nm^-1", "q (nm$^{-1}$)"),
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)"),
        keywords=("waxs", "waxd"),
        fixture_status="pending",
        priority=48,
    ),
    _rule(
        "saxs_profile",
        "saxs_profile",
        "scattering",
        "curve",
        AxisSpec("q", "nm^-1", "q (nm$^{-1}$)", aliases=("q", "q_nm-1")),
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)", aliases=("intensity",)),
        keywords=("saxs", "qnm1", "q_nm1", "q_nm-1"),
        column_aliases=("q_nm-1", "intensity"),
        analysis=(AnalysisSpec("main_scattering_peak_q", "maximum intensity q", ("q", "intensity"), "nm^-1"),),
        fixture_path="tests/fixtures/polymer_corpus/scattering_xrd_saxs_waxs/waxd_saxs_excerpt.csv",
        priority=47,
    ),
    _rule(
        "sans_profile",
        "sans_profile",
        "scattering",
        "curve",
        AxisSpec("q", "nm^-1", "q (nm$^{-1}$)"),
        AxisSpec("Intensity", "a.u.", "Intensity (a.u.)"),
        keywords=("sans",),
        fixture_status="pending",
        priority=80,
    ),
    _rule(
        "gpc_sec_chromatogram",
        "gpc_sec_chromatogram",
        "chromatography",
        "curve",
        AxisSpec("Elution time", "min", "Elution time (min)", aliases=("time", "elution")),
        AxisSpec("Detector response", "a.u.", "Detector response (a.u.)", aliases=("dri", "rayleigh ratio")),
        keywords=("gpc", "sec", "dri", "rayleigh"),
        column_aliases=("time", "dri", "rayleigh"),
        analysis=(
            AnalysisSpec(
                "peak_elution_time_min",
                "maximum detector response time",
                ("time", "response"),
                "min",
            ),
        ),
        fixture_path="tests/fixtures/polymer_corpus/chromatography_gpc_sec/gpc_dmf_excerpt.csv",
        priority=49,
    ),
    _rule(
        "molecular_weight_distribution",
        "molecular_weight_distribution",
        "chromatography",
        "curve",
        AxisSpec("Molecular weight", "g/mol", "Molecular weight (g/mol)", scale="log"),
        AxisSpec("dW/dlogM", "a.u.", "dW/dlogM"),
        keywords=("molecularweight", "mw", "mn"),
        fixture_status="pending",
        priority=75,
    ),
    _rule(
        "swelling_curve",
        "swelling_curve",
        "metrics_swelling",
        "point_line",
        AxisSpec("Time", "h", "Time (h)", aliases=("time",)),
        AxisSpec("Swelling ratio", "1", "Swelling ratio", aliases=("swelling ratio",)),
        keywords=("swelling", "gel fraction"),
        column_aliases=("swelling ratio", "gel fraction"),
        analysis=(AnalysisSpec("equilibrium_swelling_ratio", "last finite swelling ratio", ("swelling ratio",), "1"),),
        fixture_path="tests/fixtures/polymer_corpus/swelling_gel/hydrogel_swelling_excerpt.csv",
        priority=55,
    ),
    _rule(
        "gel_fraction_metric",
        "gel_fraction_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample"),
        AxisSpec("Gel fraction", "%", "Gel fraction (%)"),
        keywords=("gelfraction", "gel fraction"),
        fixture_status="pending",
        priority=70,
    ),
    _rule(
        "degradation_mass_loss",
        "degradation_mass_loss",
        "metrics_swelling",
        "point_line",
        TIME_AXIS,
        AxisSpec("Mass loss", "%", "Mass loss (%)"),
        keywords=("degradation", "massloss"),
        fixture_status="pending",
        priority=75,
    ),
    _rule(
        "conductivity_curve",
        "conductivity_curve",
        "metrics_swelling",
        "point_line",
        AxisSpec("Temperature", "C", "Temperature (°C)"),
        AxisSpec("Conductivity", "S/cm", "Conductivity (S/cm)"),
        keywords=("conductivity",),
        fixture_status="pending",
        priority=80,
    ),
    _rule(
        "arrhenius_conductivity",
        "arrhenius_conductivity",
        "metrics_swelling",
        "scatter_fit",
        AxisSpec("1000/T", "K^-1", "1000/T (K$^{-1}$)"),
        AxisSpec("log conductivity", "S/cm", "log conductivity"),
        keywords=("arrhenius",),
        fixture_status="pending",
        priority=80,
    ),
    _rule(
        "dls_size_distribution",
        "dls_size_distribution",
        "metrics_swelling",
        "curve",
        AxisSpec("Diameter", "nm", "Diameter (nm)", scale="log"),
        AxisSpec("Intensity", "%", "Intensity (%)"),
        keywords=("dls", "size distribution"),
        fixture_status="pending",
        priority=80,
    ),
    _rule(
        "bet_isotherm",
        "bet_isotherm",
        "metrics_swelling",
        "curve",
        AxisSpec("Relative pressure", "P/P0", "Relative pressure (P/P$_0$)"),
        AxisSpec("Quantity adsorbed", "cm3/g", "Quantity adsorbed (cm$^3$/g)"),
        keywords=("bet", "isotherm"),
        fixture_status="pending",
        priority=80,
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
        render_options=_POINT_LINE_LOG,
        analysis=(
            AnalysisSpec(
                "terminal_storage_modulus_frequency",
                "highest-frequency E′ value",
                ("frequency", "storage modulus"),
                "Pa",
            ),
        ),
        fixture_path="tests/fixtures/materials_rules/dma_frequency_sweep.csv",
        priority=30,
        reason="DMA frequency sweep (isothermal) with E′, E″, tanδ vs angular frequency.",
    ),
    _rule(
        "dielectric_spectroscopy",
        "dielectric_spectroscopy",
        "spectroscopy",
        "point_line",
        RHEOLOGY_X_FREQUENCY,
        AxisSpec(
            "Permittivity",
            "1",
            "Permittivity, ε′",
            aliases=("permittivity", "ε'", "epsilon'", "ε′", "dielectric constant"),
            priority_labels=("ε'", "Permittivity", "ε\""),
            scale="log",
        ),
        keywords=("dielectric", "dea", "permittivity", "ε'", "epsilon'"),
        path_keywords=("/dielectric/", "dea"),
        column_aliases=("frequency", "permittivity", "dielectric loss", "loss tangent"),
        fixture_status="pending",
        priority=52,
        reason="Dielectric spectroscopy: permittivity ε′, loss ε″ vs frequency.",
    ),
    _rule(
        "dsc_kinetics",
        "dsc_kinetics",
        "thermal",
        "curve",
        AxisSpec("Temperature", "C", "Temperature (°C)", aliases=("temperature", "temp")),
        AxisSpec(
            "Normalized heat flow",
            "W/g",
            "Normalized heat flow (W/g)",
            aliases=("heat flow", "dsc", "normalized"),
        ),
        keywords=("dsc kinetics", "kissinger", "ozawa", "heating rate", "activation energy"),
        path_keywords=("/dsc_kinetics/", "kinetics"),
        column_aliases=("temperature", "heat flow", "normalized heat flow"),
        fixture_status="pending",
        priority=9,
        reason="DSC multi-heating-rate kinetics for activation energy (Kissinger/Ozawa).",
    ),
    _rule(
        "tma_curve",
        "tma_curve",
        "thermal",
        "curve",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec(
            "Dimension change",
            "um",
            "Dimension change (µm)",
            aliases=("dimension change", "displacement", "dL", "strain"),
        ),
        keywords=("tma", "thermomechanical", "dilatometry", "cte", "热机械", "膨胀系数"),
        path_keywords=("/tma/", "thermomechanical"),
        column_aliases=("temperature", "dimension change", "expansion"),
        fixture_status="pending",
        priority=45,
        reason="Thermomechanical analysis: dimension change/CTE vs temperature.",
    ),
    _rule(
        "capillary_rheometry",
        "capillary_rheometry",
        "rheology_dma",
        "point_line",
        AxisSpec(
            "Shear rate",
            "1/s",
            "Shear rate (s$^{-1}$)",
            aliases=("shear rate", "gamma dot"),
            scale="log",
        ),
        AxisSpec(
            "Shear viscosity",
            "Pa.s",
            "Shear viscosity (Pa·s)",
            aliases=("viscosity", "shear viscosity", "η"),
            scale="log",
        ),
        keywords=("capillary", "shear viscosity", "flow curve", "shear rate", "melt viscosity"),
        path_keywords=("capillary", "flow"),
        column_aliases=("shear rate", "viscosity", "shear viscosity", "pressure"),
        render_options=_POINT_LINE_LOG,
        fixture_status="pending",
        priority=38,
        reason="Capillary rheometry flow curve: shear viscosity vs shear rate.",
    ),
    _rule(
        "creep_recovery_curve",
        "creep_recovery_curve",
        "rheology_dma",
        "curve",
        TIME_AXIS,
        AxisSpec(
            "Strain",
            "%",
            "Strain (%)",
            aliases=("strain", "γ", "gamma", "compliance"),
        ),
        keywords=("creep recovery", "creeprecovery", "creep and recovery"),
        path_keywords=("creep_recovery", "recovery"),
        column_aliases=("time", "strain", "compliance"),
        fixture_status="pending",
        priority=32,
        reason="Creep-recovery cycle: loading + unloading recovery segments.",
    ),
    _rule(
        "hardness_metric",
        "hardness_metric",
        "metrics_swelling",
        "box",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Hardness",
            "1",
            "Hardness (Shore A/D)",
            aliases=("hardness", "shore", "shore a", "shore d", "rockwell", "硬度"),
        ),
        keywords=("hardness", "shore", "rockwell", "硬度"),
        fixture_status="pending",
        priority=65,
        reason="Shore A/D or Rockwell hardness measurement.",
    ),
    _rule(
        "mfi_metric",
        "mfi_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Melt flow index",
            "g/10min",
            "MFI (g/10 min)",
            aliases=("mfi", "melt flow index", "mfr", "melt index", "熔融指数"),
        ),
        keywords=("mfi", "mfr", "melt flow", "melt index", "熔融指数"),
        fixture_status="pending",
        priority=60,
        reason="Melt flow index / melt flow rate measurement.",
    ),
    _rule(
        "tear_strength_metric",
        "tear_strength_metric",
        "tensile",
        "box",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Tear strength",
            "kN/m",
            "Tear strength (kN/m)",
            aliases=("tear strength", "tear resistance", "撕裂"),
        ),
        keywords=("tear", "tear strength", "撕裂"),
        fixture_status="pending",
        priority=68,
        reason="Tear strength / trouser tear measurement.",
    ),
    _rule(
        "hysteresis_curve",
        "hysteresis_curve",
        "tensile",
        "curve",
        STRAIN_AXIS,
        STRESS_AXIS,
        keywords=("hysteresis", "cyclic", "loading unloading", "energy dissipation", "滞后"),
        path_keywords=("hysteresis", "cyclic"),
        column_aliases=("strain", "stress", "cycle"),
        fixture_status="pending",
        priority=55,
        reason="Cyclic loading-unloading hysteresis loop with energy dissipation.",
    ),
    _rule(
        "gas_permeability_metric",
        "gas_permeability_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Permeability",
            "barrer",
            "Permeability (Barrer)",
            aliases=("permeability", "barrer", "O2", "CO2", "WVTR", "透氧"),
        ),
        keywords=("permeability", "barrer", "wvtr", "otr", "gas barrier", "透氧", "透湿"),
        fixture_status="pending",
        priority=65,
        reason="Gas permeability (O₂, CO₂) or water vapor transmission rate.",
    ),
    _rule(
        "loi_metric",
        "loi_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Limiting oxygen index",
            "%",
            "LOI (%)",
            aliases=("loi", "limiting oxygen index", "氧指数", "oxygen index"),
        ),
        keywords=("loi", "oxygen index", "limiting oxygen", "氧指数", "flame"),
        fixture_status="pending",
        priority=65,
        reason="Limiting oxygen index for flame retardancy.",
    ),
    _rule(
        "thermal_conductivity_metric",
        "thermal_conductivity_metric",
        "thermal",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Thermal conductivity",
            "W/(m·K)",
            "Thermal conductivity (W/(m·K))",
            aliases=("thermal conductivity", "κ", "k", "导热系数", "lambda"),
        ),
        keywords=("thermal conductivity", "导热系数", "κ", "lambda"),
        fixture_status="pending",
        priority=65,
        reason="Thermal conductivity (guarded hot plate / laser flash).",
    ),
    _rule(
        "contact_angle_metric",
        "contact_angle_metric",
        "metrics_swelling",
        "box",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Contact angle",
            "degree",
            "Contact angle (°)",
            aliases=("contact angle", "θ", "接触角", "surface energy", "wettability"),
        ),
        keywords=("contact angle", "θ", "接触角", "wettability", "surface energy"),
        fixture_status="pending",
        priority=65,
        reason="Contact angle / surface energy / wettability measurement.",
    ),
    _rule(
        "intrinsic_viscosity_metric",
        "intrinsic_viscosity_metric",
        "chromatography",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Intrinsic viscosity",
            "dL/g",
            "Intrinsic viscosity, [η] (dL/g)",
            aliases=("intrinsic viscosity", "[η]", "[eta]", "特性粘度"),
        ),
        keywords=("intrinsic viscosity", "limiting viscosity", "特性粘度"),
        fixture_status="pending",
        priority=80,
        reason="Intrinsic viscosity / limiting viscosity number.",
    ),
    _rule(
        "zeta_potential_metric",
        "zeta_potential_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Zeta potential",
            "mV",
            "Zeta potential (mV)",
            aliases=("zeta potential", "ζ", "zeta", "Zeta电位"),
        ),
        keywords=("zeta", "ζ", "zeta potential", "Zeta电位"),
        fixture_status="pending",
        priority=70,
        reason="Zeta potential for colloidal/particle stability.",
    ),
    _rule(
        "edx_spectrum",
        "edx_spectrum",
        "spectroscopy",
        "curve",
        AxisSpec("Energy", "keV", "Energy (keV)", aliases=("energy", "keV", "eV")),
        AxisSpec("Intensity", "count", "Intensity (counts)", aliases=("intensity", "count", "counts")),
        keywords=("edx", "eds", "edax", "energy dispersive", "elemental"),
        path_keywords=("edx", "eds"),
        column_aliases=("energy", "intensity", "counts"),
        fixture_status="pending",
        priority=53,
        reason="EDX/EDS elemental analysis spectrum.",
    ),
    _rule(
        "crosslink_density_metric",
        "crosslink_density_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Crosslink density",
            "mol/m3",
            "Crosslink density, νₑ (mol/m$^3$)",
            aliases=("crosslink density", "νₑ", "Mc", "交联密度", "network density"),
        ),
        keywords=("crosslink", "νₑ", "Mc", "交联密度", "crosslinking density"),
        fixture_status="pending",
        priority=70,
        reason="Crosslink density from swelling, modulus, or Flory-Rehner.",
    ),
    _rule(
        "abrasion_wear_metric",
        "abrasion_wear_metric",
        "metrics_swelling",
        "bar",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Volume loss",
            "mm3",
            "Volume loss (mm$^3$)",
            aliases=("volume loss", "wear", "abrasion", "taber", "磨损"),
        ),
        keywords=("abrasion", "wear", "taber", "磨损"),
        fixture_status="pending",
        priority=75,
        reason="Abrasion/wear resistance (Taber, DIN, or equivalent).",
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


def list_rules_payload() -> dict[str, Any]:
    return {
        "kind": "sciplot_material_rules",
        "rules": [
            {
                "rule_id": rule.rule_id,
                "semantic_family": rule.semantic_family,
                "recipe": rule.recipe,
                "template": rule.template,
                "x": rule.x_axis.display_label,
                "y": rule.y_axis.display_label,
                "priority": rule.priority,
            }
            for rule in iter_rules()
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
    for rule in RULES:
        score = 0
        if vendor_model and vendor_model in rule.vendor_models:
            score += 100
        if experiment_family and experiment_family in rule.experiment_families:
            score += 40
        score += 35 * sum(1 for item in rule.keywords if normalize_token(item) in compact_evidence)
        score += 45 * sum(1 for item in rule.path_keywords if item.casefold() in evidence)
        score += 30 * sum(1 for item in rule.column_aliases if normalize_token(item) in compact_evidence)
        if score:
            candidates.append((score - rule.priority, rule))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def semantic_payload_from_rule(
    rule: SemanticRule,
    *,
    confidence: float,
    reason: str | None = None,
    vendor_model: str | None = None,
    vendor_error: str | None = None,
) -> dict[str, Any]:
    payload = rule.to_payload()
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
        "confidence": confidence,
        "reason": reason or rule.reason or f"Matched material rule `{rule.rule_id}`.",
        "needs_ai_intervention": False,
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
        "missing_requirements": [],
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


def _read_paired_curve_table(path: Path) -> list[pd.DataFrame]:
    raw = pd.read_csv(path, header=None)
    if raw.shape[0] < 4:
        return []
    frames: list[pd.DataFrame] = []
    for col in range(0, raw.shape[1] - 1, 2):
        data = raw.iloc[3:, [col, col + 1]].apply(pd.to_numeric, errors="coerce").dropna()
        if not data.empty:
            data.columns = ["x", "y"]
            frames.append(data.reset_index(drop=True))
    return frames


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


def _tensile_metrics(processed_source: Path) -> list[dict[str, Any]]:
    frames = _read_paired_curve_table(processed_source)
    rows: list[dict[str, Any]] = []
    if not frames:
        return [_metric("strength_MPa", None, "MPa", "skipped", "No tensile curve found.")]
    data = frames[0].replace([np.inf, -np.inf], np.nan).dropna()
    strength = float(data["y"].max())
    strain_at_break = float(data["x"].iloc[-1])
    fit = data.drop_duplicates(subset="x").iloc[: min(8, len(data))]
    if len(fit) >= 2 and fit["x"].nunique() >= 2:
        try:
            slope = float(np.polyfit(fit["x"].to_numpy(dtype=float), fit["y"].to_numpy(dtype=float), deg=1)[0])
        except (ValueError, np.linalg.LinAlgError):
            slope = float("nan")
    else:
        slope = float("nan")
    toughness = float(np.trapezoid(data["y"].to_numpy(dtype=float), data["x"].to_numpy(dtype=float)))
    modulus_status = "ok" if np.isfinite(slope) else "skipped"
    modulus_reason = "" if modulus_status == "ok" else "Low-strain fit did not have enough distinct finite points."
    rows.extend(
        [
            _metric("strength_MPa", strength, "MPa"),
            _metric("strain_at_break_percent", strain_at_break, "%"),
            _metric(
                "modulus_MPa",
                slope if modulus_status == "ok" else None,
                "MPa",
                modulus_status,
                modulus_reason,
            ),
            _metric("toughness_MPa_percent", toughness, "MPa %"),
        ]
    )
    return rows


def _torque_metrics(processed_source: Path) -> list[dict[str, Any]]:
    frames = _read_paired_curve_table(processed_source)
    values: list[float] = []
    for frame in frames:
        values.extend(frame["y"].dropna().astype(float).tolist())
    if not values:
        return [_metric("final_segment_mean_torque_Nm", None, "N·m", "skipped", "No torque segment found.")]
    return [_metric("final_segment_mean_torque_Nm", float(np.mean(values)), "N·m")]


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


def _swelling_metrics(source_path: Path) -> list[dict[str, Any]]:
    raw = _raw_table(source_path)
    header = [normalize_token(value) for value in raw.iloc[0].tolist()]
    try:
        index = next(i for i, token in enumerate(header) if "swelling" in token)
    except StopIteration:
        return [_metric("equilibrium_swelling_ratio", None, "1", "skipped", "Swelling column not found.")]
    values = pd.to_numeric(raw.iloc[1:, index], errors="coerce").dropna()
    if values.empty:
        return [_metric("equilibrium_swelling_ratio", None, "1", "skipped", "No numeric swelling values found.")]
    return [_metric("equilibrium_swelling_ratio", float(values.iloc[-1]), "1")]


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
    if rule_id == "rheology_stress_relaxation" and processed is not None:
        rows = _stress_relaxation_metrics(processed)
    elif rule_id == "rheology_creep" and processed is not None:
        rows = _creep_metrics(processed)
    elif rule_id == "tensile_curve" and processed is not None:
        rows = _tensile_metrics(processed)
    elif rule_id == "torque_curve" and processed is not None:
        rows = _torque_metrics(processed)
    elif rule_id == "tga_curve":
        rows = _tga_metrics(source_path)
    elif rule_id in {
        "rheology_time_sweep",
        "rheology_strain_sweep",
        "rheology_stress_sweep",
        "dma_temperature_sweep",
        "dma_frequency_sweep",
        "compression_curve",
        "flexural_curve",
        "dtg_curve",
    }:
        rows = _generic_peak_metrics(
            source_path,
            metric_name=_analysis_metric_name(semantic, "peak_response_position"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
        )
    elif rule_id == "swelling_curve":
        rows = _swelling_metrics(source_path)
    elif rule_id in {"ftir_spectrum", "raman_spectrum", "uvvis_spectrum", "nmr_spectrum", "xps_spectrum"}:
        rows = _generic_peak_metrics(
            source_path,
            metric_name=_analysis_metric_name(semantic, "strongest_peak_position"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
        )
    elif rule_id in {"xrd_pattern", "waxs_pattern", "saxs_profile", "sans_profile"}:
        rows = _generic_peak_metrics(
            source_path,
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
        "label": "Nature",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "nature",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": "Nature journal: 1-col (60 mm), 1.5-col (120 mm), 2-col (180 mm).",
    },
    "acs": {
        "label": "ACS",
        "sizes": ("60x55", "120x55"),
        "style_preset": "acs",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 120,
        "description": "ACS journals: single-column figures up to 120 mm wide.",
    },
    "science": {
        "label": "Science",
        "sizes": ("60x55", "120x55"),
        "style_preset": "science",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 120,
        "description": "Science journal: single-column or 2/3-page width.",
    },
    "elsevier": {
        "label": "Elsevier",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "elsevier",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": "Elsevier journals: 1-col (60 mm), 1.5-col (120 mm), 2-col (180 mm).",
    },
    "wiley": {
        "label": "Wiley",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "wiley",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": "Wiley journals: full range of figure sizes.",
    },
    "acs_macromolecules": {
        "label": "Macromolecules (ACS)",
        "sizes": ("60x55", "120x55"),
        "style_preset": "acs",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 120,
        "description": "ACS Macromolecules: figures fit within single column (60 mm) or page width (120 mm).",
    },
    "polymer": {
        "label": "Polymer (Elsevier)",
        "sizes": ("60x55", "120x55", "180x55"),
        "style_preset": "elsevier",
        "palette_preset": DEFAULT_PALETTE_PRESET,
        "exports": ("pdf", "tiff_300"),
        "max_width_mm": 180,
        "description": "Polymer journal (Elsevier): standard Elsevier figure sizes.",
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
    "iter_rules",
    "list_rules_payload",
    "match_rule",
    "normalize_token",
    "semantic_payload_from_rule",
    "show_rule_payload",
]
