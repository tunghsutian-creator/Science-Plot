"""Stable semantic classification and source-preparation API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation

from sciplot_core.semantic_sources.classification import (
    TENSILE_EXPORT_DIR_SUFFIX,
    classify_source,
    has_tensile_export_parent,
    is_tensile_export_dir,
    tensile_export_csv_files,
    tensile_export_sample_name,
)
from sciplot_core.semantic_sources.curve_output import _write_curve_table  # noqa: F401
from sciplot_core.semantic_sources.dma_sources import (  # noqa: F401
    _read_dma_temperature_series,
)
from sciplot_core.semantic_sources.ftir_sources import (  # noqa: F401
    _read_ftir_series,
    _read_ftir_series_list,
)
from sciplot_core.semantic_sources.impact_sources import (  # noqa: F401
    read_impact_condition_payloads,
)
from sciplot_core.semantic_sources.interventions import build_intervention_request
from sciplot_core.semantic_sources.models import (  # noqa: F401
    CurveSeriesPayload,
    ImpactReplicatePayload,
    RheologySweepSample,
    _ImpactDataValidationError,
    _StressRelaxationHoldError,
)
from sciplot_core.semantic_sources.preparation_context import (
    SemanticPreparationContext,
)
from sciplot_core.semantic_sources.preparation_support import (
    _semantic_preparation_result,
)
from sciplot_core.semantic_sources.prepare_curve_families import (
    prepare_curve_family_source,
)
from sciplot_core.semantic_sources.prepare_mechanical import (
    prepare_mechanical_source,
)
from sciplot_core.semantic_sources.prepare_rheology import (
    prepare_rheology_source,
)
from sciplot_core.semantic_sources.rheology_replicates import (
    is_rheology_frequency_comparison_dir,
    is_rheology_temperature_comparison_dir,
)
from sciplot_core.semantic_sources.rheology_sweep_sources import (  # noqa: F401
    _read_rheology_frequency_comparison_samples,
    _read_rheology_temperature_comparison_samples,
    _unit_conversion,
)
from sciplot_core.semantic_sources.stress_relaxation_sources import (  # noqa: F401
    _read_stress_relaxation_series_list,
    _read_stress_relaxation_source_series,
)
from sciplot_core.semantic_sources.tensile_workbooks import (  # noqa: F401
    _read_tensile_workbook_directory,
)
from sciplot_core.semantic_sources.torque_labels import (  # noqa: F401
    _compact_torque_sample_labels,
)
from sciplot_core.semantic_sources.torque_event_selection import (  # noqa: F401
    _apply_torque_selection,
    _auto_torque_event_selection,
)
from sciplot_core.semantic_sources.torque_sources import (  # noqa: F401
    _read_torque_full_series,
    _torque_source_files,
)


_SOURCE_ATTESTED_FAMILIES = frozenset(
    {"dma_temperature_sweep", "rheology_temperature_sweep"}
)


def prepare_semantic_source(
    input_path: str | Path,
    *,
    output_dir: Path,
    semantic: dict[str, Any],
    curation_path: str | Path | None = None,
    series_order: object = None,
    column_confirmations: object = None,
    replicate_mode: object = None,
) -> dict[str, Any]:
    """Prepare one source through the handler for its semantic family."""

    source = Path(input_path).expanduser().resolve()
    family = str(semantic["semantic_family"])
    rule_value = semantic.get("rule_id")
    rule_id = (
        rule_value
        if isinstance(rule_value, str)
        and bool(rule_value)
        and rule_value.strip() == rule_value
        else None
    )
    attestation_rule_id = rule_id or family
    source_hash_before = (
        source_tree_sha256(source) if family in _SOURCE_ATTESTED_FAMILIES else None
    )
    processed_dir = output_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    context = SemanticPreparationContext(
        source=source,
        processed_dir=processed_dir,
        family=family,
        rule_id=rule_id,
        curation_path=curation_path,
        series_order=series_order,
        column_confirmations=column_confirmations,
        replicate_mode=replicate_mode,
        source_tree_sha256_before=source_hash_before,
    )
    for handler in (
        prepare_rheology_source,
        prepare_curve_family_source,
        prepare_mechanical_source,
    ):
        result = handler(context)
        if result is not None:
            if family in _SOURCE_ATTESTED_FAMILIES:
                attestation = result.get("source_attestation")
                if (
                    not isinstance(attestation, PreparationSourceAttestation)
                    or attestation.rule_id != attestation_rule_id
                    or attestation.source_tree_sha256_before != source_hash_before
                    or attestation.source_tree_sha256_after != source_hash_before
                ):
                    raise RuntimeError(
                        "semantic_preparation_source_changed: source-attested "
                        "temperature data "
                        "changed while semantic preparation was running."
                    )
                attestation.verify_current(source_root=source)
            return result

    return _semantic_preparation_result(
        source,
        processed_source=None,
        operation="identity",
        parameters={
            "reason": (
                "The input is already plot-ready for the selected semantic family."
            )
        },
    )


__all__ = [
    "build_intervention_request",
    "classify_source",
    "has_tensile_export_parent",
    "is_tensile_export_dir",
    "is_rheology_frequency_comparison_dir",
    "is_rheology_temperature_comparison_dir",
    "prepare_semantic_source",
    "TENSILE_EXPORT_DIR_SUFFIX",
    "tensile_export_csv_files",
    "tensile_export_sample_name",
]
