"""Stable semantic classification and source-preparation API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.preparation_source_attestation import (
    PreparationSourceAttestation,
    requires_preparation_source_attestation,
)

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
from sciplot_core.semantic_sources.mechanical_facts import (
    load_mechanical_source_facts,
)
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

if TYPE_CHECKING:
    from sciplot_core.materials_rules.models import PreparationAdapterId
    from sciplot_core.semantic_sources.scientific_source import (
        ResolvedScientificSource,
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
    resolved_scientific_source: ResolvedScientificSource | None = None,
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
    if (
        resolved_scientific_source is not None
        and (
            resolved_scientific_source.source != source
            or resolved_scientific_source.rule_id != (rule_id or family)
            or resolved_scientific_source.semantic_family != family
        )
    ):
        raise ValueError(
            "Resolved scientific domain does not match the selected semantic family."
        )
    source_hash_before = None
    if requires_preparation_source_attestation(attestation_rule_id):
        source_hash_before = (
            resolved_scientific_source.source_sha256
            if resolved_scientific_source is not None
            and resolved_scientific_source.source_sha256 is not None
            else source_tree_sha256(source)
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
        resolved_scientific_source=resolved_scientific_source,
    )
    adapter = _semantic_preparation_adapter(family=family, rule_id=rule_id)
    result = _run_semantic_preparation_adapter(adapter, context)
    if result is not None:
        if requires_preparation_source_attestation(attestation_rule_id):
            attestation = result.get("source_attestation")
            if (
                not isinstance(attestation, PreparationSourceAttestation)
                or attestation.rule_id != attestation_rule_id
                or attestation.source_tree_sha256_before != source_hash_before
                or attestation.source_tree_sha256_after != source_hash_before
            ):
                raise RuntimeError(
                    "semantic_preparation_source_changed: source-attested "
                    "semantic data "
                    "changed while semantic preparation was running."
                )
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


def _semantic_preparation_adapter(
    *,
    family: str,
    rule_id: str | None,
) -> PreparationAdapterId | None:
    """Resolve one canonical preparation adapter without a parallel family map."""

    from sciplot_core.materials_rules.catalog import get_rule, iter_rules

    if rule_id is not None:
        rule = get_rule(rule_id)
        if rule.semantic_family != family:
            raise ValueError(
                "semantic_preparation_rule_mismatch: semantic family and rule differ."
            )
        return rule.preparation_adapter
    matches = tuple(rule for rule in iter_rules() if rule.semantic_family == family)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(
            "semantic_preparation_rule_required: semantic family does not identify "
            "one canonical rule."
        )
    return matches[0].preparation_adapter


def _run_semantic_preparation_adapter(
    adapter: PreparationAdapterId | None,
    context: SemanticPreparationContext,
) -> dict[str, Any] | None:
    if adapter == "rheology":
        return prepare_rheology_source(context)
    if adapter == "curve_family":
        return prepare_curve_family_source(context)
    if adapter == "mechanical":
        return prepare_mechanical_source(context)
    if adapter is None:
        return None
    raise RuntimeError(f"Unknown semantic preparation adapter `{adapter}`.")


__all__ = [
    "build_intervention_request",
    "classify_source",
    "has_tensile_export_parent",
    "is_tensile_export_dir",
    "is_rheology_frequency_comparison_dir",
    "is_rheology_temperature_comparison_dir",
    "load_mechanical_source_facts",
    "prepare_semantic_source",
    "TENSILE_EXPORT_DIR_SUFFIX",
    "tensile_export_csv_files",
    "tensile_export_sample_name",
]
