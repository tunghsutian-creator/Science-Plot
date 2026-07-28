"""Build semantic preparation results and shared preparation inventories."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.publication import build_transform_step


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
    RheologySweepSample,
    _RHEOLOGY_AMPLITUDE_OUTPUT_METRICS,
    _RHEOLOGY_TIME_OUTPUT_METRICS,
)

from sciplot_core.semantic_sources.series_labels import (
    _intake_group_name,
)


def _has_intake_grouped_series(series_list: list[CurveSeriesPayload]) -> bool:
    return any(_intake_group_name(series.sample) for series in series_list)


def _semantic_preparation_result(
    source: Path,
    *,
    processed_source: Path | None,
    operation: str,
    parameters: dict[str, Any] | None = None,
    additional_outputs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    output_path = processed_source if processed_source is not None else source
    return {
        "source": str(output_path),
        "processed": processed_source is not None,
        "processed_source": str(processed_source)
        if processed_source is not None
        else None,
        "transform_steps": [
            build_transform_step(
                step_id="semantic_preparation",
                operation=operation,
                input_path=source,
                output_path=output_path,
                implementation_ref="sciplot_core.semantic.prepare_semantic_source",
                parameters=parameters,
                additional_outputs=additional_outputs,
            )
        ],
    }


_SHARED_RHEOLOGY_SWEEP_CONFIG: dict[str, dict[str, Any]] = {
    "rheology_strain_sweep": {
        "x_aliases": ("shearstrain", "strain", "gamma", "γ"),
        "x_label": "Strain",
        "x_unit": "%",
        "metrics": _RHEOLOGY_AMPLITUDE_OUTPUT_METRICS,
        "comparison_sheet": "Strain_Comparison",
    },
    "rheology_stress_sweep": {
        "x_aliases": ("shearstress", "stress"),
        "x_label": "Stress",
        "x_unit": "Pa",
        "metrics": _RHEOLOGY_AMPLITUDE_OUTPUT_METRICS,
        "comparison_sheet": "Stress_Comparison",
    },
    "rheology_time_sweep": {
        "x_aliases": ("time", "elapsedtime"),
        "x_label": "Time",
        "x_unit": "s",
        "metrics": _RHEOLOGY_TIME_OUTPUT_METRICS,
        "comparison_sheet": "Time_Comparison",
    },
}


def _rheology_replicate_inventory(
    samples: list[RheologySweepSample],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[RheologySweepSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.sample, []).append(sample)
    return [
        {
            "sample": sample_label,
            "replicate_count": len(replicates),
            "source_files": [str(replicate.source) for replicate in replicates],
        }
        for sample_label, replicates in grouped.items()
    ]


def _rheology_unit_conversion_inventory(
    samples: list[RheologySweepSample],
) -> list[dict[str, Any]]:
    return [
        {
            "sample": sample.sample,
            "source": str(sample.source),
            "x": sample.x_conversion,
            "metrics": sample.metric_conversions or {},
        }
        for sample in samples
    ]
