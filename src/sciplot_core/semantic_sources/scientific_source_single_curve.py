"""Bind one resolved curve transform to the shared single-task plan."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic_sources.table_selection import confirmed_source_sheet

if TYPE_CHECKING:
    from sciplot_core.semantic_sources.scientific_source_models import (
        ResolvedScientificSource,
    )


def bind_single_curve_scientific_source(
    source: Path,
    *,
    rule: SemanticRule,
    request: dict[str, Any],
    template: str,
    transform: ResolvedScientificTransform,
    source_sha256_before: str,
) -> ResolvedScientificSource:
    from sciplot_core.figure_plan.errors import FigurePlanResolutionError
    from sciplot_core.figure_plan.single_curve_resolution import (
        resolve_registered_single_curve_plan,
    )
    from sciplot_core.semantic_sources.scientific_source_models import (
        ResolvedScientificSource,
        ScientificSourceResolutionError,
    )

    source_sha256_after = require_single_curve_source_sha256(source, rule=rule)
    if source_sha256_after != source_sha256_before:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_source_changed_during_resolution",
            f"The {rule.rule_id} source changed while its scientific snapshot "
            "was being resolved.",
        )
    try:
        figure_plan = resolve_registered_single_curve_plan(
            rule_id=rule.rule_id,
            request={**request, "template": template},
            source_resolution=transform,
            source_sha256=source_sha256_before,
        )
    except FigurePlanResolutionError as exc:
        raise ScientificSourceResolutionError(exc.reason_code, str(exc)) from exc
    return ResolvedScientificSource(
        rule_id=rule.rule_id,
        source=source,
        domain=transform,
        figure_plan=figure_plan,
        source_sha256=source_sha256_before,
    )


def require_single_curve_source_sha256(
    source: Path,
    *,
    rule: SemanticRule,
) -> str:
    """Fingerprint one source at an explicit scientific-resolution boundary."""

    from sciplot_core.figure_plan.source_binding import source_tree_sha256
    from sciplot_core.semantic_sources.scientific_source_models import (
        ScientificSourceResolutionError,
    )

    try:
        source_sha256 = source_tree_sha256(source)
    except OSError as exc:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_source_unavailable",
            f"SciPlot could not fingerprint the {rule.rule_id} source: {exc}",
        ) from exc
    if source_sha256 is None:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_source_unavailable",
            f"SciPlot could not fingerprint the {rule.rule_id} source.",
        )
    return source_sha256


def resolve_single_curve_transform(
    source: Path,
    *,
    rule: SemanticRule,
    series_order: object = None,
    column_confirmations: object = None,
) -> ResolvedScientificTransform:
    from sciplot_core.semantic_sources.confirmation_contract import require_supported_confirmations

    column_confirmations = require_supported_confirmations(rule, column_confirmations)
    adapter = rule.scientific_source_adapter
    if adapter == "ftir":
        from sciplot_core.semantic_sources.ftir_sources import (
            resolve_ftir_scientific_transform,
        )

        return resolve_ftir_scientific_transform(
            source,
            series_order=series_order,
        )
    if adapter == "registered_paired_curve":
        from sciplot_core.semantic_sources.registered_paired_curve_transform import (
            resolve_registered_paired_curve_transform,
        )

        selected_sheet = confirmed_source_sheet(source, column_confirmations)
        return resolve_registered_paired_curve_transform(
            source,
            rule=rule,
            series_order=series_order,
            **(
                {"selected_sheet": selected_sheet} if selected_sheet is not None else {}
            ),
        )
    if adapter == "gpc_sec":
        from sciplot_core.semantic_sources.gpc_sources import (
            resolve_gpc_scientific_transform,
        )

        return resolve_gpc_scientific_transform(
            source,
            rule=rule,
            series_order=series_order,
        )
    if adapter == "swelling":
        from sciplot_core.semantic_sources.swelling_transform import (
            resolve_swelling_scientific_transform,
        )

        return resolve_swelling_scientific_transform(
            source,
            series_order=series_order,
        )
    raise ValueError(
        f"Rule {rule.rule_id!r} does not own a single-curve source adapter."
    )


def resolve_single_curve_scientific_source(
    source: Path,
    *,
    rule: SemanticRule,
    request: dict[str, Any],
    template: str,
) -> ResolvedScientificSource:
    from sciplot_core.semantic_sources.scientific_source_models import (
        ScientificSourceResolutionError,
    )

    source_sha256_before = require_single_curve_source_sha256(source, rule=rule)
    try:
        transform = resolve_single_curve_transform(
            source,
            rule=rule,
            series_order=request.get("series_order"),
            column_confirmations=request.get("column_confirmations"),
        )
    except (OSError, ValueError) as exc:
        raise ScientificSourceResolutionError(
            f"{rule.rule_id}_transform_invalid",
            str(exc),
        ) from exc
    return bind_single_curve_scientific_source(
        source,
        rule=rule,
        request=request,
        template=template,
        transform=transform,
        source_sha256_before=source_sha256_before,
    )


def bind_archived_single_curve(
    observed: ResolvedScientificSource,
    archive: Path,
    *,
    request: dict[str, Any],
    template: str,
) -> ResolvedScientificSource | None:
    """Move unchanged single-file curve values onto their exact intake identity."""

    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.foundation.source_tree import source_tree_sha256
    from sciplot_core.materials_rules.catalog import get_rule

    transform = observed.transform
    source = observed.source
    if (
        transform is None or transform.selected_sources != (source,)
        or source.suffix.lower() not in {".csv", ".tsv"} or not source.is_file()
        or request.get("rule_id") != observed.rule_id
        or request.get("series_order") or request.get("column_confirmations")
        or transform.contract.output.get("explicit_series_order_applied")
        or not archive.is_dir()
    ):
        return None
    rule = get_rule(observed.rule_id)
    adapter = rule.scientific_source_adapter
    if adapter not in {"registered_paired_curve", "ftir", "gpc_sec"}:
        return None
    members = tuple(archive.iterdir())
    if len(members) != 1:
        return None
    archived, = members
    if not archived.is_file() or archived.is_symlink() or archived.suffix != source.suffix:
        return None
    content_sha256 = file_sha256(archived)
    if canonical_json_sha256({"kind": "file", "content_sha256": content_sha256}) != observed.source_sha256:
        return None
    if adapter == "registered_paired_curve":
        from sciplot_core.semantic_sources.table_scanning import curve_table_sample_prefix

        original_prefix, archive_prefix = (curve_table_sample_prefix(p.stem) for p in (source, archived))
    elif adapter == "ftir":
        from sciplot_core.semantic_sources.series_labels import _source_display_sample

        original_prefix, archive_prefix = (_source_display_sample(p) for p in (source, archived))
    else:
        original_prefix, archive_prefix = source.stem, archived.stem
    series = []
    for item in transform.series:
        diagnostics = item.diagnostics or {}
        if diagnostics.get("source_file") != str(source) or diagnostics.get("source_table") != source.stem:
            return None
        detection = diagnostics.get("source_sample_detection")
        sample = item.sample
        if detection in {"fallback_from_source_table", "derived_from_source_filename"}:
            suffix = sample.removeprefix(original_prefix)
            if not sample.startswith(original_prefix) or (suffix and not (suffix.startswith(" ") and suffix[1:].isdigit())):
                return None
            sample = archive_prefix + suffix
        elif detection not in {"detected_from_adjacent_sample_row", "detected_from_preceding_sample_row",
                               "detected_from_instrument_metadata"}:
            return None
        series.append(replace(item, sample=sample, diagnostics={**diagnostics, "source_sample_value": sample,
                              "source_file": str(archived), "source_table": archived.stem}))
    if len({item.sample for item in series}) != len(series):
        return None
    if adapter == "registered_paired_curve":
        from sciplot_core.semantic_sources.registered_paired_curve_contract import build_registered_paired_curve_contract

        contract = build_registered_paired_curve_contract(
            series, rule=rule, selected_sources=(archived,), explicit_series_order_applied=False,
        )
    elif adapter == "ftir":
        from sciplot_core.semantic_sources.ftir_transform_contract import build_ftir_transform_contract

        contract = build_ftir_transform_contract(series, selected_sources=(archived,), explicit_series_order_applied=False)
    else:
        from sciplot_core.semantic_sources.gpc_transform_contract import build_gpc_transform_contract

        contract = build_gpc_transform_contract(
            series, rule=rule, selected_sources=(archived,), explicit_series_order_applied=False,
        )
    expected = canonical_json_sha256({"kind": "directory", "files": [
        {"path": archived.name, "content_sha256": content_sha256},
    ]}, allow_nan=False)
    if source_tree_sha256(archive) != expected:
        return None
    return bind_single_curve_scientific_source(
        archive, rule=rule, request=request, template=template,
        transform=ResolvedScientificTransform(tuple(series), contract, (archived,)),
        source_sha256_before=expected,
    )


__all__ = [
    "bind_single_curve_scientific_source",
    "require_single_curve_source_sha256",
    "resolve_single_curve_scientific_source",
    "resolve_single_curve_transform",
]
