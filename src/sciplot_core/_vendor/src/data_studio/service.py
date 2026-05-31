from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_studio.comparison import (
    comparison_recipes_for_workbooks,
    export_comparison_bundle,
    materialize_comparison_context,
    preview_comparison_recipe,
)
from src.data_studio.import_templates_v2 import (
    V2_PARSE_STRATEGY,
    build_workbook_from_template,
    create_template_definition,
    parse_file_with_template,
    preview_template_apply,
)
from src.data_studio.ingest import preview_and_recommend
from src.data_studio.models import (
    DataStudioWorkbook,
    TemplateDefinition,
    TemplateFieldBinding,
    TemplateMatch,
    TemplateMatchCondition,
    TemplateSegmentSelector,
    TemplateSourceFormat,
)
from src.data_studio.session import normalize_session_payload
from src.data_studio.template_store import (
    delete_template,
    list_templates,
    load_template,
    rename_template,
    save_template,
)
from src.data_studio.workbooks import (
    build_workbook,
    import_workbook,
    import_workbooks,
    preview_workbook,
)
from src.infrastructure.persistence.data_studio_imports import prepare_managed_data_studio_import_dir
from src.rendering.data_containers import table_container_from_frame
from src.text_normalization import slugify_label


def list_data_studio_templates():
    return list_templates()


def list_data_studio_template_recommendations(source_path: str | Path):
    preview, recommendations = preview_and_recommend(source_path)
    return _data_studio_recommendations_for_mode(preview=preview, recommendations=recommendations)


def list_data_studio_template_recommendations_payload(
    source_path: str | Path,
    *,
    import_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = _normalize_import_selection(source_path, import_selection=import_selection)
    blocking = _blocking_import_selection_diagnostics(selection)
    if blocking:
        return {"matches": [], "diagnostics": blocking}
    preview, recommendations = preview_and_recommend(_selection_input_path(source_path, selection))
    recommendations = _data_studio_recommendations_for_mode(preview=preview, recommendations=recommendations)
    diagnostics = _selection_applied_diagnostics(selection)
    return {
        "matches": [
            _enriched_template_match(match, selection=selection)
            for match in recommendations
        ],
        "diagnostics": diagnostics,
    }


def _data_studio_recommendations_for_mode(*, preview: object, recommendations: tuple[TemplateMatch, ...]) -> tuple[TemplateMatch, ...]:
    _ = preview
    return recommendations


def create_data_studio_template(
    *,
    label: str,
    template_id: str | None = None,
    description: str = "",
    output_kind: str = "curve_metrics",
    comparison_enabled: bool | None = None,
    source_format: dict[str, object] | None = None,
    segment_policy: str = "single_table",
    segment_selectors: list[dict[str, object]] | None = None,
    field_bindings: list[dict[str, object]] | None = None,
    match_conditions: list[dict[str, object]] | None = None,
    metadata: dict[str, object] | None = None,
):
    template = create_template_definition(
        label=label,
        template_id=template_id,
        description=description,
        output_kind=output_kind,
        comparison_enabled=comparison_enabled,
        source_format=_source_format_from_payload(source_format or {}),
        segment_policy=segment_policy,
        segment_selectors=tuple(_segment_selector_from_payload(item) for item in (segment_selectors or [])),
        field_bindings=tuple(_field_binding_from_payload(item) for item in (field_bindings or [])),
        match_conditions=tuple(_condition_from_payload(item) for item in (match_conditions or [])),
        metadata=metadata,
    )
    save_template(template)
    return template


def preview_data_studio_template(
    source_path: str | Path,
    *,
    template_payload: dict[str, object],
    import_selection: dict[str, Any] | None = None,
):
    template = create_template_definition(
        label=str(template_payload.get("label", "Draft Import Template")),
        template_id=(
            str(template_payload["template_id"])
            if template_payload.get("template_id") is not None
            else "draft/template"
        ),
        description=str(template_payload.get("description", "")),
        output_kind=str(template_payload.get("output_kind", "curve_metrics")),
        comparison_enabled=(
            bool(template_payload["comparison_enabled"])
            if template_payload.get("comparison_enabled") is not None
            else None
        ),
        source_format=_source_format_from_payload(dict(template_payload.get("source_format", {}) or {})),
        segment_policy=str(template_payload.get("segment_policy", "single_table")),
        segment_selectors=tuple(
            _segment_selector_from_payload(item)
            for item in list(template_payload.get("segment_selectors", []) or [])
            if isinstance(item, dict)
        ),
        field_bindings=tuple(
            _field_binding_from_payload(item)
            for item in list(template_payload.get("field_bindings", []) or [])
            if isinstance(item, dict)
        ),
        match_conditions=tuple(
            _condition_from_payload(item)
            for item in list(template_payload.get("match_conditions", []) or [])
            if isinstance(item, dict)
        ),
        metadata=dict(template_payload.get("metadata", {}) or {}),
    )
    selection = _normalize_import_selection(source_path, import_selection=import_selection)
    effective = _template_with_import_selection(template, selection)
    preview = preview_template_apply(_selection_input_path(source_path, selection), effective)
    normalized, containers = _normalized_output_preview_and_containers(
        _selection_input_path(source_path, selection),
        effective,
        selection=selection,
    )
    return replace(preview, normalized_output_preview=normalized, data_containers=tuple(containers))


def update_data_studio_template(template_id: str, *, new_id: str | None = None, new_label: str | None = None):
    return rename_template(template_id, new_id=new_id, new_label=new_label)


def delete_data_studio_template(template_id: str) -> None:
    delete_template(template_id)


def build_data_studio_workbook(
    *,
    file_paths: list[str | Path],
    output_path: str | Path | None = None,
    template_id: str,
    group_name: str | None = None,
    import_selection: dict[str, Any] | None = None,
):
    if not file_paths:
        raise ValueError("Select at least one source file.")
    resolved_output_path = output_path or _managed_group_workbook_path(file_paths, group_name=group_name)
    template = load_template(template_id)
    selection = _normalize_import_selection(file_paths[0] if file_paths else "", import_selection=import_selection)
    if template.parse_strategy == V2_PARSE_STRATEGY and selection:
        effective = _template_with_import_selection(template, selection)
        workbook = build_workbook_from_template(
            file_paths=file_paths,
            output_path=resolved_output_path,
            template=effective,
            group_name=group_name,
        )
    else:
        workbook = build_workbook(
            file_paths=file_paths,
            output_path=resolved_output_path,
            template_id=template_id,
            group_name=group_name,
        )
    return replace(workbook, data_containers=tuple(_workbook_data_containers(workbook)))


def _managed_group_workbook_path(
    file_paths: list[str | Path],
    *,
    group_name: str | None,
) -> Path:
    first_path = Path(file_paths[0]).expanduser()
    managed_dir = prepare_managed_data_studio_import_dir(first_path)
    stem = slugify_label(group_name or first_path.stem) or "sample_group"
    return managed_dir / f"{stem}.xlsx"


def _normalize_import_selection(
    source_path: str | Path,
    *,
    import_selection: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not import_selection:
        return None
    selection = dict(import_selection)
    selection.setdefault("input_path", str(source_path))
    selection.setdefault("options", {})
    selection.setdefault("diagnostics", [])
    return selection


def _selection_input_path(source_path: str | Path, selection: dict[str, Any] | None) -> str | Path:
    if selection and selection.get("input_path"):
        return str(selection["input_path"])
    return source_path


def _blocking_import_selection_diagnostics(selection: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not selection:
        return []
    profile = selection.get("profile") if isinstance(selection.get("profile"), dict) else {}
    diagnostics = [item for item in selection.get("diagnostics", []) if isinstance(item, dict)]
    if profile.get("status") == "disabled":
        return diagnostics or [
            {
                "status_code": "import_filter_disabled",
                "severity": "warning",
                "message": "The selected import filter is disabled for Data Studio templates.",
            }
        ]
    return [
        item
        for item in diagnostics
        if str(item.get("status_code")) in {"dependency_missing", "policy_not_implemented"}
    ]


def _selection_applied_diagnostics(selection: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not selection:
        return []
    selected = selection.get("selected_sheet_or_segment")
    return [
        {
            "status_code": "import_selection_applied",
            "severity": "info",
            "message": "Using the selected import profile, options, and source structure.",
            "selected_sheet_or_segment": selected,
            "filter_id": selection.get("filter_id"),
        }
    ]


def _template_with_import_selection(
    template: TemplateDefinition,
    selection: dict[str, Any] | None,
) -> TemplateDefinition:
    if not selection:
        return template
    options = selection.get("options") if isinstance(selection.get("options"), dict) else {}
    selected = selection.get("selected_sheet_or_segment")
    selected_text = str(selected) if selected is not None else ""
    sheet_name = options.get("sheet") or options.get("sheet_name")
    if sheet_name is None and selected_text and "::" not in selected_text:
        sheet_name = selected_text
    if sheet_name is None and "::" in selected_text:
        sheet_name = selected_text.split("::", 1)[0]
    delimiter = (
        options.get("delimiter")
        if options.get("delimiter") not in {"", "auto", None}
        else template.source_format.delimiter
    )
    if delimiter == "tab":
        delimiter = "\t"
    source_format = replace(
        template.source_format,
        encoding=(
            str(options["encoding"])
            if options.get("encoding") not in {"", "auto", None}
            else template.source_format.encoding
        ),
        delimiter=str(delimiter) if delimiter is not None else None,
        sheet_name=str(sheet_name) if sheet_name is not None else template.source_format.sheet_name,
    )
    segment_selectors = template.segment_selectors
    segment_id = str(options.get("segment_id") or selected_text or "")
    if segment_id and "::" in segment_id:
        segment_selectors = (
            TemplateSegmentSelector(
                id=segment_id,
                label=segment_id,
            ),
        )
    return replace(
        template,
        source_format=source_format,
        segment_selectors=segment_selectors,
    )


def _enriched_template_match(match: TemplateMatch, *, selection: dict[str, Any] | None) -> dict[str, Any]:
    template = load_template(match.template_id)
    missing_roles = _missing_required_roles(template)
    matched_roles = _role_matches_for_template(template, missing_roles=missing_roles)
    diagnostics = _selection_applied_diagnostics(selection)
    return {
        "template_id": match.template_id,
        "label": match.label,
        "family": match.family,
        "confidence": match.confidence,
        "recommendation_source": match.recommendation_source,
        "reasons": list(match.reasons),
        "warnings": list(match.warnings),
        "matched_sheet_names": list(match.matched_sheet_names),
        "auto_selected": match.auto_selected,
        "matched_roles": matched_roles,
        "missing_roles": missing_roles,
        "ambiguous_roles": [],
        "matched_structure_id": (selection or {}).get("selected_sheet_or_segment"),
        "diagnostics": diagnostics,
    }


def _role_matches_for_template(
    template: TemplateDefinition,
    *,
    missing_roles: list[str],
) -> list[dict[str, Any]]:
    missing = set(missing_roles)
    matches: list[dict[str, Any]] = []
    for binding in template.field_bindings:
        matches.append(
            {
                "role": binding.role,
                "label": binding.label,
                "source_label": binding.column_name or binding.label,
                "status": "missing" if binding.role in missing else "matched",
                "confidence": 0.0 if binding.role in missing else 1.0,
            }
        )
    return matches


def _missing_required_roles(template: TemplateDefinition) -> list[str]:
    roles = {binding.role for binding in template.field_bindings if not binding.optional}
    if template.output_kind == "curve_metrics":
        required = ["curve_x", "curve_y"]
        if template.comparison_enabled:
            required.append("metric")
        return [role for role in required if role not in roles]
    if template.output_kind == "metric_table":
        return ["metric"] if "metric" not in roles else []
    if template.output_kind == "matrix_heatmap":
        return [role for role in ("matrix_x", "matrix_y", "matrix_z") if role not in roles]
    return []


def _normalized_output_preview_and_containers(
    source_path: str | Path,
    template: TemplateDefinition,
    *,
    selection: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        parsed = parse_file_with_template(source_path, template)
    except Exception as exc:
        return {
            "selected_structure_id": (selection or {}).get("selected_sheet_or_segment"),
            "role_mapping": _role_matches_for_template(template, missing_roles=_missing_required_roles(template)),
            "series_count": 0,
            "metric_count": 0,
            "matrix_row_count": 0,
            "sample_rows": [],
            "warnings": [],
            "errors": [str(exc)],
        }, []
    rows: list[list[object]] = []
    if parsed.curves:
        curve = parsed.curves[0]
        rows = [[curve.x_label, curve.y_label], [curve.x_unit, curve.y_unit]]
        rows.extend(curve.data.head(12).values.tolist())
    elif parsed.matrix_rows is not None:
        rows = parsed.matrix_rows.head(14).values.tolist()
    elif parsed.metrics:
        rows = [["Metric", "Value"], *[[key, value] for key, value in parsed.metrics.items()]]
    frame = _frame_from_sample_rows(rows)
    containers = []
    if frame is not None:
        containers.append(
            table_container_from_frame(
                frame,
                input_path=source_path,
                sheet=template.source_format.sheet_name or "Sheet1",
                container_id=f"data-studio-normalized:{template.id}",
                label=f"{template.label} normalized output",
                kind="transformed_view",
                help_text="Readonly normalized Data Studio output generated from the selected import profile.",
            )
        )
    return {
        "selected_structure_id": (
            parsed.curves[0].segment_id
            if parsed.curves
            else (selection or {}).get("selected_sheet_or_segment")
        ),
        "role_mapping": _role_matches_for_template(template, missing_roles=[]),
        "series_count": len(parsed.curves),
        "metric_count": len(parsed.metrics or {}),
        "matrix_row_count": 0 if parsed.matrix_rows is None else len(parsed.matrix_rows.index),
        "sample_rows": rows[:14],
        "warnings": list(parsed.warnings),
        "errors": [],
    }, containers


def _frame_from_sample_rows(rows: list[list[object]]) -> pd.DataFrame | None:
    if not rows:
        return None
    headers = [str(item) for item in rows[0]]
    data_rows = rows[1:] if len(rows) > 1 else []
    return pd.DataFrame(data_rows, columns=headers)


def _workbook_data_containers(workbook: DataStudioWorkbook) -> list[dict[str, Any]]:
    workbook_path = Path(workbook.workbook_path).expanduser()
    if not workbook_path.exists():
        return []
    try:
        frame = pd.read_excel(workbook_path, sheet_name=workbook.preferred_sheet, header=None).fillna("")
    except Exception:
        return []
    return [
        table_container_from_frame(
            frame,
            input_path=workbook_path,
            sheet=workbook.preferred_sheet,
            container_id=f"data-studio-workbook:{workbook_path.name}:{workbook.preferred_sheet}",
            label=f"{workbook.label} {workbook.preferred_sheet}",
            kind="transformed_view",
            help_text="Readonly Data Studio workbook output container.",
        )
    ]


def _source_format_from_payload(payload: dict[str, object]) -> TemplateSourceFormat:
    return TemplateSourceFormat(
        encoding=str(payload["encoding"]) if payload.get("encoding") is not None else None,
        delimiter=str(payload["delimiter"]) if payload.get("delimiter") is not None else None,
        sheet_name=str(payload["sheet_name"]) if payload.get("sheet_name") is not None else None,
    )


def _segment_selector_from_payload(payload: dict[str, object]) -> TemplateSegmentSelector:
    return TemplateSegmentSelector(
        id=str(payload["id"]),
        label=str(payload.get("label", payload["id"])),
        result_label=str(payload["result_label"]) if payload.get("result_label") is not None else None,
        interval_index=int(payload["interval_index"]) if payload.get("interval_index") is not None else None,
        header_row_index=int(payload["header_row_index"]) if payload.get("header_row_index") is not None else None,
        unit_row_index=int(payload["unit_row_index"]) if payload.get("unit_row_index") is not None else None,
        data_start_row_index=(
            int(payload["data_start_row_index"]) if payload.get("data_start_row_index") is not None else None
        ),
        start_row=int(payload["start_row"]) if payload.get("start_row") is not None else None,
        end_row=int(payload["end_row"]) if payload.get("end_row") is not None else None,
    )


def _field_binding_from_payload(payload: dict[str, object]) -> TemplateFieldBinding:
    return TemplateFieldBinding(
        id=str(payload["id"]),
        role=str(payload["role"]),
        label=str(payload["label"]),
        sheet_name=str(payload["sheet_name"]) if payload.get("sheet_name") is not None else None,
        block_id=str(payload["block_id"]) if payload.get("block_id") is not None else None,
        column_name=str(payload["column_name"]) if payload.get("column_name") is not None else None,
        column_index=int(payload["column_index"]) if payload.get("column_index") is not None else None,
        row_label_contains=(
            str(payload["row_label_contains"]) if payload.get("row_label_contains") is not None else None
        ),
        cell_value_contains=tuple(str(item) for item in payload.get("cell_value_contains", ()) or ()),
        unit_hint=str(payload["unit_hint"]) if payload.get("unit_hint") is not None else None,
        sample_name=str(payload["sample_name"]) if payload.get("sample_name") is not None else None,
        optional=bool(payload.get("optional", False)),
    )


def _condition_from_payload(payload: dict[str, object]) -> TemplateMatchCondition:
    return TemplateMatchCondition(
        sheet_name_contains=tuple(str(item) for item in payload.get("sheet_name_contains", ()) or ()),
        text_contains=tuple(str(item) for item in payload.get("text_contains", ()) or ()),
        field_kinds=tuple(str(item) for item in payload.get("field_kinds", ()) or ()),
        minimum_score=float(payload.get("minimum_score", 0.0) or 0.0),
    )


def import_data_studio_workbook(path: str | Path):
    return import_workbook(path)


def import_data_studio_workbooks(path: str | Path):
    return import_workbooks(path)


def preview_data_studio_workbook(path: str | Path, *, specimen_states=None):
    return preview_workbook(path, specimen_states=specimen_states)


def list_data_studio_recipes(workbook_paths: list[str | Path], *, group_states=None):
    return comparison_recipes_for_workbooks(workbook_paths, group_states=group_states)


def preview_data_studio_comparison(
    workbook_paths: list[str | Path],
    recipe_id: str,
    *,
    group_states=None,
    specimen_states=None,
):
    return preview_comparison_recipe(
        workbook_paths,
        recipe_id,
        group_states=group_states,
        specimen_states=specimen_states,
    )


def preview_data_studio_comparison_context(
    workbook_paths: list[str | Path],
    *,
    group_states=None,
    specimen_states=None,
):
    return materialize_comparison_context(
        workbook_paths,
        group_states=group_states,
        specimen_states=specimen_states,
    )


def export_data_studio_comparison(
    workbook_paths: list[str | Path],
    output_dir: str | Path,
    *,
    group_states=None,
    specimen_states=None,
    selected_recipe_ids: list[str] | None = None,
    figure_options_by_recipe_id: dict[str, dict[str, object]] | None = None,
    figure_fit_options_by_recipe_id: dict[str, dict[str, object]] | None = None,
):
    return export_comparison_bundle(
        workbook_paths,
        output_dir,
        group_states=group_states,
        specimen_states=specimen_states,
        selected_recipe_ids=selected_recipe_ids,
        figure_options_by_recipe_id=figure_options_by_recipe_id,
        figure_fit_options_by_recipe_id=figure_fit_options_by_recipe_id,
    )


__all__ = [
    "build_data_studio_workbook",
    "create_data_studio_template",
    "delete_data_studio_template",
    "export_data_studio_comparison",
    "import_data_studio_workbook",
    "import_data_studio_workbooks",
    "list_data_studio_recipes",
    "list_data_studio_template_recommendations",
    "list_data_studio_template_recommendations_payload",
    "list_data_studio_templates",
    "load_template",
    "normalize_session_payload",
    "preview_data_studio_template",
    "preview_data_studio_workbook",
    "preview_data_studio_comparison",
    "preview_data_studio_comparison_context",
    "update_data_studio_template",
]
