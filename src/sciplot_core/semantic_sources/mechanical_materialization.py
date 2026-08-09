"""Materialize one source-bound tensile, compression, or flexural dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.materials_rules import ELONGATION_AT_BREAK_METRIC
from sciplot_core.semantic_sources.curve_output import _write_curve_table
from sciplot_core.semantic_sources.mechanical_fact_models import (
    MECHANICAL_RULE_IDS,
    MechanicalSourceFacts,
    normalize_mechanical_curve_mode,
)
from sciplot_core.semantic_sources.mechanical_facts import (
    load_mechanical_source_facts,
)
from sciplot_core.semantic_sources.preparation_context import (
    SemanticPreparationContext,
)
from sciplot_core.semantic_sources.preparation_support import (
    _semantic_preparation_result,
)


_SUMMARY_DEFINITIONS = {
    "tensile_curve": {
        "strength_MPa": (
            "instrument-reported maximum tensile stress, else curve maximum"
        ),
        ELONGATION_AT_BREAK_METRIC: (
            "instrument-reported elongation at break, else curve terminal strain"
        ),
        "modulus_MPa": (
            "instrument-reported 0.05%-0.25% program-segment modulus, else "
            "curve fit with percent strain converted to a fraction"
        ),
        "toughness_MJ_m3": (
            "stress integral over engineering-strain fraction up to break"
        ),
    },
    "compression_curve": {
        "compressive_strength_MPa": (
            "maximum stress magnitude from each retained specimen curve"
        ),
    },
    "flexural_curve": {
        "flexural_strength_MPa": ("maximum stress from each retained specimen curve"),
    },
}


def prepare_exact_mechanical_source(
    context: SemanticPreparationContext,
) -> dict[str, Any] | None:
    """Write curve and raw-observation tables from the same immutable facts."""

    if context.family not in MECHANICAL_RULE_IDS:
        return None
    rule_id = context.rule_id or context.family
    if rule_id != context.family:
        raise ValueError(
            "mechanical_preparation_rule_mismatch: semantic family and rule differ."
        )
    facts = load_mechanical_source_facts(
        context.source,
        rule_id=rule_id,
        series_order=context.series_order,
    )
    mode = normalize_mechanical_curve_mode(context.replicate_mode)
    selected_series = facts.curve_series_for_mode(mode)
    processed_source = _processed_curve_path(
        context.processed_dir,
        source=context.source,
        rule_id=rule_id,
    )
    summary_source = processed_source.with_name(f"{processed_source.stem}_summary.csv")
    _write_curve_table(list(selected_series), processed_source)
    pd.DataFrame(facts.summary_records()).to_csv(summary_source, index=False)

    additional_outputs: tuple[Path, ...] = (summary_source,)
    grouped_raw_curves = facts.individual_curves_complete and any(
        count > 1 for _sample, count in facts.replicate_counts
    )
    if grouped_raw_curves:
        all_source = processed_source.with_name(f"{processed_source.stem}_all.csv")
        _write_curve_table(list(facts.individual_curve_series), all_source)
        additional_outputs = (all_source, summary_source)

    representative_selections = (
        _representative_selections(facts) if mode == "representative" else []
    )
    return _semantic_preparation_result(
        context.source,
        processed_source=processed_source,
        operation=f"extract_{rule_id}_curves",
        parameters={
            "input_series_labels": [
                str((item.diagnostics or {}).get("source_sample") or item.sample)
                for item in facts.raw_series
            ],
            "normalized_input_series_labels": [
                item.sample for item in facts.raw_series
            ],
            "raw_curve_inventory": [
                {
                    "source_sample": str(
                        (item.diagnostics or {}).get("source_sample") or item.sample
                    ),
                    "normalized_sample": item.sample,
                    "replicate_group": (item.diagnostics or {}).get("replicate_group"),
                    "replicate": (item.diagnostics or {}).get("replicate_label"),
                    "source_file": (item.diagnostics or {}).get("source_file"),
                    "point_count": len(item.points),
                }
                for item in facts.raw_series
            ],
            "output_series_labels": [item.sample for item in selected_series],
            "series_order": [item.sample for item in selected_series],
            "sample_order": list(facts.sample_order),
            "replicate_counts": dict(facts.replicate_counts),
            "requested_replicate_mode": mode,
            "applied_curve_replicate_mode": mode,
            "representative_selection_applied": mode == "representative",
            "representative_definition": (
                "closest retained strength to group median, then closest retained "
                "break strain to its group median for tensile, then original "
                "source order"
                if mode == "representative"
                else None
            ),
            "representative_selections": representative_selections,
            "individual_curves_complete": facts.individual_curves_complete,
            "all_series_preserved_in_supporting_output": grouped_raw_curves,
            "curve_source_kind": facts.curve_source_kind,
            "curve_point_counts": dict(facts.curve_point_counts(mode)),
            "source_sha256": facts.source_sha256,
            "selected_source_files": [str(path) for path in facts.selected_sources],
            "summary_metric_source": str(summary_source),
            "summary_replicate_count": len(facts.summary_rows),
            "summary_raw_specimen_count": len(facts.summary_rows),
            "summary_raw_values_preserved": True,
            "summary_statistic_contract": "median_iqr_with_visible_raw_points",
            "summary_metric_units": dict(facts.metric_units),
            "summary_metric_definitions": _SUMMARY_DEFINITIONS[rule_id],
        },
        additional_outputs=additional_outputs,
        source_attestation_rule_id=rule_id,
        source_tree_sha256_before=context.source_tree_sha256_before,
        selected_sources=facts.selected_sources,
    )


def _processed_curve_path(processed_dir: Path, *, source: Path, rule_id: str) -> Path:
    suffix = {
        "tensile_curve": "tensile_curves",
        "compression_curve": "compression_curve_curves",
        "flexural_curve": "flexural_curve_curves",
    }[rule_id]
    return processed_dir / f"{source.stem}_{suffix}.csv"


def _representative_selections(
    facts: MechanicalSourceFacts,
) -> list[dict[str, object]]:
    selections: list[dict[str, object]] = []
    for series in facts.representative_curve_series:
        diagnostics = series.diagnostics or {}
        if not facts.individual_curves_complete:
            selections.append(
                {
                    "sample": series.sample,
                    "replicate": None,
                    "source_file": str(diagnostics.get("source_file") or ""),
                    "metrics": {},
                    "selection_kind": "workbook_authoritative_representative",
                }
            )
            continue
        replicate = str(
            diagnostics.get("replicate_label")
            or diagnostics.get("source_sample")
            or series.sample
        )
        matching = [
            row
            for row in facts.summary_rows
            if row.sample == series.sample
            and (
                row.replicate == replicate
                or (
                    row.source_file
                    and row.source_file == str(diagnostics.get("source_file") or "")
                    and len(
                        [
                            candidate
                            for candidate in facts.summary_rows
                            if candidate.sample == series.sample
                            and candidate.source_file == row.source_file
                        ]
                    )
                    == 1
                )
            )
        ]
        if len(matching) != 1:
            raise ValueError(
                "mechanical_representative_evidence_mismatch: selected curve "
                "does not identify exactly one raw specimen observation."
            )
        observation = matching[0]
        selections.append(
            {
                "sample": observation.sample,
                "replicate": observation.replicate,
                "source_file": observation.source_file,
                "metrics": dict(observation.metrics),
            }
        )
    return selections


__all__ = ["prepare_exact_mechanical_source"]
