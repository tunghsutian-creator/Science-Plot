"""Declare study-model replicate modes and experiment figure plans."""

from __future__ import annotations

from typing import Any

from sciplot_core.dma_temperature_contract import dma_temperature_experiment_plan
from sciplot_core.mechanical_figure_contract import (
    mechanical_experiment_plan,
    mechanical_statistics_method,
)


STUDY_MODEL_KIND = "sciplot_study_model"


STUDY_MODEL_VERSION = 2


REPLICATE_MODES: dict[str, dict[str, str]] = {
    "mean": {
        "label": "Mean",
        "description": "Average compatible replicate files into one sample trace or metric.",
    },
    "representative": {
        "label": "Representative",
        "description": "Keep one representative replicate for the sample.",
    },
    "individual": {
        "label": "All",
        "description": "Render each replicate trace or metric without averaging.",
    },
}


_REPLICATE_MODE_ALIASES = {
    "average": "mean",
    "avg": "mean",
    "best": "representative",
    "all": "individual",
}


_DEFAULT_FIGURE_QUEUE = (
    {
        "id": "primary_curve",
        "title": "Primary curve",
        "metric": "primary",
        "x_metric": "x",
        "y_metric": "y",
        "default_template": "curve",
    },
)


# First-party compatibility alias; executable mechanical queues are built from
# ``mechanical_experiment_plan`` and this payload is not an independent owner.
_TENSILE_DESCRIPTIVE_STATISTICS = mechanical_statistics_method()


_EXPERIMENT_PLANS: dict[str, dict[str, Any]] = {
    "dma_temperature_sweep": dma_temperature_experiment_plan(),
    "rheology_frequency_sweep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "storage_modulus_vs_frequency",
                "title": "Storage modulus vs frequency",
                "metric": "storage_modulus",
                "x_metric": "angular_frequency",
                "y_metric": "storage_modulus",
                "default_template": "point_line",
            },
            {
                "id": "loss_modulus_vs_frequency",
                "title": "Loss modulus vs frequency",
                "metric": "loss_modulus",
                "x_metric": "angular_frequency",
                "y_metric": "loss_modulus",
                "default_template": "point_line",
            },
            {
                "id": "loss_factor_vs_frequency",
                "title": "tan delta vs frequency",
                "metric": "loss_factor",
                "x_metric": "angular_frequency",
                "y_metric": "loss_factor",
                "default_template": "point_line",
            },
            {
                "id": "complex_viscosity_vs_frequency",
                "title": "Complex viscosity vs frequency",
                "metric": "complex_viscosity",
                "x_metric": "angular_frequency",
                "y_metric": "complex_viscosity",
                "default_template": "point_line",
            },
        ),
    },
    "rheology_temperature_sweep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "storage_modulus_vs_temperature",
                "title": "Storage modulus vs temperature",
                "metric": "storage_modulus",
                "x_metric": "temperature",
                "y_metric": "storage_modulus",
                "default_template": "point_line",
            },
            {
                "id": "tan_delta_vs_temperature",
                "title": "tan delta vs temperature",
                "metric": "loss_factor",
                "x_metric": "temperature",
                "y_metric": "loss_factor",
                "default_template": "point_line",
            },
        ),
    },
    "rheology_strain_sweep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "storage_modulus_vs_strain",
                "title": "Storage modulus vs strain",
                "metric": "storage_modulus",
                "x_metric": "strain",
                "y_metric": "storage_modulus",
                "default_template": "point_line",
            },
            {
                "id": "loss_factor_vs_strain",
                "title": "Loss factor vs strain",
                "metric": "loss_factor",
                "x_metric": "strain",
                "y_metric": "loss_factor",
                "default_template": "point_line",
            },
        ),
    },
    "rheology_stress_sweep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "storage_modulus_vs_stress",
                "title": "Storage modulus vs stress",
                "metric": "storage_modulus",
                "x_metric": "stress",
                "y_metric": "storage_modulus",
                "default_template": "point_line",
            },
            {
                "id": "loss_factor_vs_stress",
                "title": "Loss factor vs stress",
                "metric": "loss_factor",
                "x_metric": "stress",
                "y_metric": "loss_factor",
                "default_template": "point_line",
            },
        ),
    },
    "rheology_time_sweep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "complex_modulus_vs_time",
                "title": "Complex modulus vs time",
                "metric": "complex_modulus",
                "x_metric": "time",
                "y_metric": "complex_modulus",
                "default_template": "point_line",
            },
        ),
    },
    "rheology_stress_relaxation": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "normalized_stress_vs_time",
                "title": "Normalized stress vs time",
                "metric": "normalized_stress",
                "x_metric": "time",
                "y_metric": "normalized_stress",
                "default_template": "curve",
            },
        ),
    },
    "rheology_creep": {
        "default_replicate_mode": "mean",
        "figure_queue": (
            {
                "id": "creep_compliance_vs_time",
                "title": "Creep compliance vs time",
                "metric": "creep_compliance",
                "x_metric": "time",
                "y_metric": "creep_compliance",
                "default_template": "curve",
            },
        ),
    },
    "tensile_curve": mechanical_experiment_plan("tensile_curve"),
    "compression_curve": mechanical_experiment_plan("compression_curve"),
    "flexural_curve": mechanical_experiment_plan("flexural_curve"),
    "torque_curve": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "screw_torque_vs_time",
                "title": "Screw torque vs time",
                "metric": "screw_torque",
                "x_metric": "time",
                "y_metric": "screw_torque",
                "default_template": "curve",
            },
        ),
    },
    "impact_metric": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "impact_strength_by_sample",
                "title": "Impact strength by sample",
                "metric": "impact_strength",
                "x_metric": "sample",
                "y_metric": "impact_strength",
                "default_template": "box_strip",
            },
        ),
    },
    "torque_offset_stack": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "screw_torque_offset_stack",
                "title": "Screw torque offset stack",
                "metric": "screw_torque",
                "x_metric": "time",
                "y_metric": "screw_torque",
                "default_template": "stacked_curve",
            },
        ),
    },
    "ftir_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "ftir_intensity_vs_wavenumber",
                "title": "FTIR spectrum",
                "metric": "infrared_intensity",
                "x_metric": "wavenumber",
                "y_metric": "intensity",
                "default_template": "curve",
            },
        ),
    },
    "raman_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "raman_intensity_vs_shift",
                "title": "Raman spectrum",
                "metric": "raman_intensity",
                "x_metric": "raman_shift",
                "y_metric": "intensity",
                "default_template": "curve",
            },
        ),
    },
    "uvvis_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "uvvis_absorbance_vs_wavelength",
                "title": "UV-vis spectrum",
                "metric": "absorbance",
                "x_metric": "wavelength",
                "y_metric": "absorbance",
                "default_template": "curve",
            },
        ),
    },
    "xps_spectrum": {
        "default_replicate_mode": "individual",
        "figure_queue": (
            {
                "id": "xps_intensity_vs_binding_energy",
                "title": "XPS spectrum",
                "metric": "xps_intensity",
                "x_metric": "binding_energy",
                "y_metric": "intensity",
                "default_template": "curve",
            },
        ),
    },
}
