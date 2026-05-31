from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.data_studio.ingest import preview_raw_file
from src.data_studio.models import (
    FieldCandidate,
    TemplateDefinition,
    TemplateFieldBinding,
    TemplateFieldRole,
)
from src.data_studio.workbook_constants import GENERIC_TEMPLATE_PARSE_STRATEGY


def create_template_from_candidates(
    *,
    source_path: str | Path,
    label: str,
    accepted_candidate_ids: Iterable[str] | None = None,
    template_id: str | None = None,
    description: str = "",
) -> TemplateDefinition:
    preview = preview_raw_file(source_path)
    accepted_ids = set(accepted_candidate_ids or ())
    all_candidates = list(preview.field_candidates)
    candidates = [candidate for candidate in all_candidates if not accepted_ids or candidate.id in accepted_ids]
    x_candidate, y_candidate = _resolve_curve_pair(preview, accepted_ids, candidates, all_candidates)
    if x_candidate is None or y_candidate is None:
        raise ValueError("Template creation needs at least one recommended X field and one recommended Y field.")
    metric_candidates = [candidate for candidate in candidates if candidate.kind == "metric"]
    block = _resolve_block(preview, x_candidate.block_id or y_candidate.block_id)
    metadata = {
        "sheet_name": block.sheet_name if block is not None else x_candidate.sheet_name,
        "block_id": block.id if block is not None else x_candidate.block_id,
        "header_row_index": block.header_row_index if block is not None else None,
        "unit_row_index": block.unit_row_index if block is not None else None,
        "data_start_row_index": block.data_start_row_index if block is not None else None,
    }
    field_bindings = [
        _binding_from_candidate(x_candidate, role="curve_x"),
        _binding_from_candidate(y_candidate, role="curve_y"),
    ]
    for candidate in metric_candidates:
        field_bindings.append(_binding_from_candidate(candidate, role="metric"))

    resolved_id = template_id or f"user/{slugify_template_label(label)}"
    return TemplateDefinition(
        version=1,
        id=resolved_id,
        label=label.strip() or "Untitled Data Studio Template",
        family="structured_curve_metrics",
        builtin=False,
        description=description.strip() or f"Template created from {Path(source_path).name}.",
        file_types=(Path(source_path).suffix.lower().lstrip("."),),
        parse_strategy=GENERIC_TEMPLATE_PARSE_STRATEGY,
        field_bindings=tuple(field_bindings),
        workbook_metric_ids=tuple(binding.label for binding in field_bindings if binding.role == "metric"),
        preferred_sheet_name="Representative_Curve",
        metadata=metadata,
    )


def slugify_template_label(label: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in label).strip("_") or "template"


def _resolve_curve_pair(
    preview: Any,
    accepted_ids: set[str],
    candidates: list[FieldCandidate],
    all_candidates: list[FieldCandidate],
) -> tuple[FieldCandidate | None, FieldCandidate | None]:
    selected_curve_suggestions = [
        suggestion
        for suggestion in preview.binding_suggestions
        if suggestion.kind == "curve_pair"
        and suggestion.candidate_ids
        and set(suggestion.candidate_ids).issubset(accepted_ids)
    ]
    if selected_curve_suggestions:
        curve_candidate_ids = set(selected_curve_suggestions[0].candidate_ids)
        x_candidate = next(
            (
                candidate
                for candidate in all_candidates
                if candidate.id in curve_candidate_ids and candidate.kind == "curve_x"
            ),
            None,
        )
        y_candidate = next(
            (
                candidate
                for candidate in all_candidates
                if candidate.id in curve_candidate_ids and candidate.kind == "curve_y"
            ),
            None,
        )
        if x_candidate is not None and y_candidate is not None:
            return x_candidate, y_candidate

    same_block_pairs: list[tuple[float, FieldCandidate, FieldCandidate]] = []
    candidate_pool = candidates or all_candidates
    x_candidates = [candidate for candidate in candidate_pool if candidate.kind == "curve_x"]
    y_candidates = [candidate for candidate in candidate_pool if candidate.kind == "curve_y"]
    for x_candidate in x_candidates:
        for y_candidate in y_candidates:
            if x_candidate.block_id and y_candidate.block_id and x_candidate.block_id != y_candidate.block_id:
                continue
            score = x_candidate.confidence + y_candidate.confidence
            same_block_pairs.append((score, x_candidate, y_candidate))
    if same_block_pairs:
        same_block_pairs.sort(key=lambda item: (-item[0], item[1].label.lower(), item[2].label.lower()))
        _, x_candidate, y_candidate = same_block_pairs[0]
        return x_candidate, y_candidate

    return _best_candidate(candidates, "curve_x") or _best_candidate(all_candidates, "curve_x"), _best_candidate(
        candidates, "curve_y"
    ) or _best_candidate(all_candidates, "curve_y")


def _resolve_block(preview: Any, block_id: str | None) -> Any:
    if block_id is None:
        return None
    for sheet in preview.sheets:
        for block in sheet.blocks:
            if block.id == block_id:
                return block
    return None


def _best_candidate(candidates: list[FieldCandidate], kind: str) -> FieldCandidate | None:
    matches = [candidate for candidate in candidates if candidate.kind == kind]
    if not matches:
        return None
    matches.sort(key=lambda item: (-item.confidence, item.label.lower(), item.id))
    return matches[0]


def _binding_from_candidate(candidate: FieldCandidate, *, role: TemplateFieldRole) -> TemplateFieldBinding:
    column_index = candidate.range.start_col if candidate.range is not None else None
    return TemplateFieldBinding(
        id=candidate.id,
        role=role,
        label=candidate.label,
        sheet_name=candidate.sheet_name,
        block_id=candidate.block_id,
        column_name=candidate.label,
        column_index=column_index,
        unit_hint=candidate.unit_hint,
    )


__all__ = ["create_template_from_candidates", "slugify_template_label"]
