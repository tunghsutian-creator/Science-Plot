"""Dispatch rule-specific analysis metric computation and materialize metric artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.materials_rules.metric_tables import (
    _write_metrics_csv,
    _metric,
)

from sciplot_core.materials_rules.mechanical_metrics import (
    _mechanical_strength_summary_metrics,
    _stress_relaxation_metrics,
    _creep_metrics,
    _tensile_metrics,
    _torque_metrics,
)

from sciplot_core.materials_rules.curve_extrema_metrics import (
    _tga_metrics,
    _paired_extreme_position_metrics,
    _paired_steepest_drop_position_metrics,
)
from sciplot_core.materials_rules.curve_peak_metrics import (
    _ftir_peak_position_metrics,
    _interior_local_peak_position_metrics,
    _terminal_y_metrics,
    _peak_y_metrics,
)

from sciplot_core.materials_rules.thermal_metrics import (
    _dsc_metrics,
    _swelling_metrics,
)

from sciplot_core.materials_rules.impact_metrics import (
    _impact_metrics,
)


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
    processed = (
        processed_source if processed_source and processed_source.exists() else None
    )
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
    elif rule_id == "rheology_frequency_sweep":
        rows = _terminal_y_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "terminal_modulus"),
            y_unit=semantic["axis_plan"]["y"]["canonical_unit"],
            x_boundary="lowest",
            x_tokens=("angular frequency", "frequency"),
            y_tokens=("storage modulus",),
        )
    elif rule_id == "dma_frequency_sweep":
        rows = _terminal_y_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(
                semantic,
                "terminal_storage_modulus_frequency",
            ),
            y_unit=semantic["axis_plan"]["y"]["canonical_unit"],
            x_boundary="highest",
            x_tokens=("angular frequency", "frequency"),
            y_tokens=("storage modulus",),
        )
    elif rule_id == "rheology_temperature_sweep":
        rows = _peak_y_metrics(
            canonical_source,
            metric_name="maximum_tan_delta",
            y_unit="1",
            x_tokens=("temperature",),
            y_tokens=("loss factor", "tan delta"),
            reason=(
                "Maximum finite loss factor in the canonical trace; "
                "this value is not interpreted as Tg."
            ),
        )
        rows.extend(
            _paired_extreme_position_metrics(
                canonical_source,
                metric_name="temperature_at_maximum_tan_delta_C",
                x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
                extreme="maximum",
                x_tokens=("temperature",),
                y_tokens=("loss factor", "tan delta"),
                reason=(
                    "Temperature of the maximum finite loss factor; endpoint "
                    "maxima are retained and this is not interpreted as Tg."
                ),
            )
        )
        rows.extend(
            _paired_steepest_drop_position_metrics(
                canonical_source,
                metric_name="softening_temperature_candidate",
                x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
                x_tokens=("temperature",),
                y_tokens=("storage modulus",),
            )
        )
    elif rule_id == "compression_curve":
        summary_source = canonical_source.with_name(
            f"{canonical_source.stem}_summary.csv"
        )
        rows = (
            _mechanical_strength_summary_metrics(
                summary_source,
                metric_name="compressive_strength_MPa",
                iqr_name="compressive_strength_iqr_MPa",
            )
            if summary_source.is_file()
            else []
        )
        if not rows:
            rows = _peak_y_metrics(
                canonical_source,
                metric_name="compressive_strength_MPa",
                y_unit=semantic["axis_plan"]["y"]["canonical_unit"],
                magnitude=True,
                y_tokens=("stress",),
            )
    elif rule_id == "flexural_curve":
        summary_source = canonical_source.with_name(
            f"{canonical_source.stem}_summary.csv"
        )
        rows = (
            _mechanical_strength_summary_metrics(
                summary_source,
                metric_name="flexural_strength_MPa",
                iqr_name="flexural_strength_iqr_MPa",
            )
            if summary_source.is_file()
            else []
        )
        if not rows:
            rows = _peak_y_metrics(
                canonical_source,
                metric_name="flexural_strength_MPa",
                y_unit=semantic["axis_plan"]["y"]["canonical_unit"],
                y_tokens=("stress",),
            )
    elif rule_id == "rheology_time_sweep":
        rows = _paired_extreme_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "peak_response_position"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            extreme="maximum",
            x_tokens=("time", "elapsed time"),
            y_tokens=("complex modulus", "complex shear modulus"),
        )
    elif rule_id in {"rheology_strain_sweep", "rheology_stress_sweep"}:
        rows = _paired_extreme_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "peak_response_position"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            extreme="maximum",
            x_tokens=(
                ("strain", "shear strain")
                if rule_id == "rheology_strain_sweep"
                else ("stress", "shear stress")
            ),
            y_tokens=("storage modulus",),
        )
    elif rule_id == "dma_temperature_sweep":
        rows = _paired_steepest_drop_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(
                semantic, "storage_modulus_drop_temperature_C"
            ),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            x_tokens=("temperature",),
            y_tokens=("storage modulus",),
        )
    elif rule_id == "dtg_curve":
        rows = _paired_extreme_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "dtg_peak_temperature_C"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            extreme="maximum",
            x_tokens=("temperature",),
            y_tokens=("derivative mass", "dtg", "derivative"),
            reason=(
                "Temperature of the maximum finite -d(mass)/dT response in "
                "the canonical paired trace."
            ),
        )
    elif rule_id == "swelling_curve":
        rows = _swelling_metrics(canonical_source)
    elif rule_id == "impact_metric" and processed is not None:
        rows = _impact_metrics(processed)
    elif rule_id == "ftir_spectrum":
        rows = _ftir_peak_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(
                semantic,
                "observed_response_extremum_wavenumber_cm-1",
            ),
        )
    elif rule_id == "uvvis_spectrum":
        rows = _paired_extreme_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "strongest_peak_position"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            extreme="maximum",
            x_tokens=("wavelength",),
            y_tokens=("absorbance",),
        )
    elif rule_id == "xrd_pattern":
        rows = _paired_extreme_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "main_peak_2theta"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            extreme="maximum",
            x_tokens=("diffraction angle", "angle", "2theta", "2 theta"),
            y_tokens=("intensity",),
            reason=(
                "Diffraction angle of the maximum finite observed intensity; "
                "this descriptive position does not assign a crystalline phase."
            ),
        )
    elif rule_id == "saxs_profile":
        rows = _interior_local_peak_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(semantic, "main_scattering_peak_q"),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            x_tokens=("q",),
            y_tokens=("intensity",),
        )
    elif rule_id == "gpc_sec_chromatogram":
        rows = _paired_extreme_position_metrics(
            canonical_source,
            metric_name=_analysis_metric_name(
                semantic,
                "peak_molar_mass_g_mol",
            ),
            x_unit=semantic["axis_plan"]["x"]["canonical_unit"],
            extreme="maximum",
            x_tokens=("molar mass", "molecular weight", "mw"),
            y_tokens=(
                "differential weight fraction",
                "dwdlogm",
                "weight distribution",
            ),
            reason=(
                "Molar mass at the maximum finite instrument-exported dW/dlog M "
                "value; no molecular-weight calibration is inferred from RI."
            ),
        )
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
