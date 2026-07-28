"""Declare canonical axes shared by semantic rule domains."""

from __future__ import annotations

from sciplot_core.policy import (
    COMPRESSION_X_AXIS_LABEL,
    COMPRESSION_Y_AXIS_LABEL,
    FLEXURAL_X_AXIS_LABEL,
    FLEXURAL_Y_AXIS_LABEL,
    RHEOLOGY_FREQUENCY_X_LABEL,
    TENSILE_X_AXIS_LABEL,
    TENSILE_Y_AXIS_LABEL,
)
from sciplot_core.materials_rules.models import (
    AxisSpec,
)

RHEOLOGY_X_FREQUENCY = AxisSpec(
    "Angular frequency",
    "rad/s",
    RHEOLOGY_FREQUENCY_X_LABEL,
    aliases=("angular frequency", "frequency", "omega", "ω"),
    scale="log",
)


RHEOLOGY_X_TEMPERATURE = AxisSpec(
    "Temperature", "C", "Temperature (°C)", aliases=("temperature", "temp", "温度")
)


TIME_AXIS = AxisSpec("Time", "s", "Time (s)", aliases=("time", "时间"))


TENSILE_STRAIN_AXIS = AxisSpec(
    "Tensile strain",
    "%",
    TENSILE_X_AXIS_LABEL,
    aliases=("strain", "tensile strain", "拉伸应变"),
)


TENSILE_STRESS_AXIS = AxisSpec(
    "Tensile stress",
    "MPa",
    TENSILE_Y_AXIS_LABEL,
    aliases=("stress", "tensile stress", "拉伸应力", "σ"),
)


COMPRESSION_STRAIN_AXIS = AxisSpec(
    "Compressive strain",
    "%",
    COMPRESSION_X_AXIS_LABEL,
    aliases=("strain", "compressive strain", "compression strain", "压缩应变"),
)


COMPRESSION_STRESS_AXIS = AxisSpec(
    "Compressive stress",
    "MPa",
    COMPRESSION_Y_AXIS_LABEL,
    aliases=("stress", "compressive stress", "compression stress", "压缩应力", "σ"),
)


FLEXURAL_STRAIN_AXIS = AxisSpec(
    "Flexural strain",
    "%",
    FLEXURAL_X_AXIS_LABEL,
    aliases=("strain", "flexural strain", "bending strain", "弯曲应变"),
)


FLEXURAL_STRESS_AXIS = AxisSpec(
    "Flexural stress",
    "MPa",
    FLEXURAL_Y_AXIS_LABEL,
    aliases=("stress", "flexural stress", "bending stress", "弯曲应力", "σ"),
)


TORQUE_AXIS = AxisSpec(
    "Screw torque",
    "N·m",
    "Screw torque (N·m)",
    aliases=("screw torque", "torque", "转矩"),
)
