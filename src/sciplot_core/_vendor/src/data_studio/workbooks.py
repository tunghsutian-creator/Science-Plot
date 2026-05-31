from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.data_studio.builtin import tensile as tensile_builtin
from src.data_studio.io_utils import ensure_input_path, list_sheet_names
from src.data_studio.models import DataStudioWorkbook, DataStudioWorkbookPreview, TemplateDefinition, TemplateMatch
from src.data_studio.template_store import load_template
from src.data_studio.workbook_building import _representative_scores, build_workbook, parse_structured_sample
from src.data_studio.workbook_comparison_bundle import (
    import_source_workbooks_from_metadata,
    looks_like_comparison_bundle,
    materialize_comparison_bundle_groups,
)
from src.data_studio.workbook_constants import (
    FILTERED_WORKBOOK_CURVE_DECIMAL_PLACES,
    FILTERED_WORKBOOK_DECIMAL_PLACES,
    GENERIC_TEMPLATE_PARSE_STRATEGY,
)
from src.data_studio.workbook_export import export_filtered_workbook_from_context
from src.data_studio.workbook_previewing import (
    FilteredWorkbookContext,
    LoadedWorkbookSpecimen,
    LoadedWorkbookSpecimenBundle,
    build_filtered_workbook_context,
    build_loaded_workbook_specimen_bundle,
    metric_summaries_from_workbook,
    preview_loaded_workbook_bundle,
)
from src.data_studio.workbook_template_authoring import create_template_from_candidates


def _workbook_cache_key(path: str | Path) -> tuple[str, int]:
    workbook_path = ensure_input_path(str(Path(path).expanduser()))
    return str(workbook_path.resolve()), workbook_path.stat().st_mtime_ns


def _import_workbook_from_path(workbook_path: Path) -> DataStudioWorkbook:
    metadata = tensile_builtin.load_metadata_sheet(workbook_path)
    template_id = str(metadata.get("template_id", "")).strip()
    if template_id == tensile_builtin.TENSILE_TEMPLATE_ID:
        return tensile_builtin.inspect_tensile_workbook(workbook_path)

    sheet_names = tuple(list_sheet_names(workbook_path))
    if not sheet_names:
        raise ValueError(f"{workbook_path.name} is not a valid Excel workbook.")
    if tensile_builtin.REQUIRED_TENSILE_WORKBOOK_SHEETS.issubset(set(sheet_names)):
        return tensile_builtin.inspect_tensile_workbook(workbook_path)
    label = str(metadata.get("label", workbook_path.stem)).strip() or workbook_path.stem
    template = load_template(template_id) if template_id else TemplateDefinition(
        version=1,
        id="imported/unknown",
        label="Imported Workbook",
        family="imported_workbook",
        builtin=False,
        description="Imported Data Studio workbook without a template reference.",
        file_types=("xlsx",),
        parse_strategy=GENERIC_TEMPLATE_PARSE_STRATEGY,
    )
    metric_summaries = metric_summaries_from_workbook(workbook_path)
    representative_filename = str(metadata.get("representative_filename", workbook_path.name))
    sample_count = int(metadata.get("sample_count", 0) or 0)
    source_files = tuple(Path(item) for item in metadata.get("source_files", ()))
    warnings = tuple(str(item) for item in metadata.get("warnings", ()))
    if tensile_builtin.REPRESENTATIVE_CURVE_SHEET in sheet_names:
        preferred_sheet = tensile_builtin.REPRESENTATIVE_CURVE_SHEET
    elif tensile_builtin.ALL_CURVES_SHEET in sheet_names:
        preferred_sheet = tensile_builtin.ALL_CURVES_SHEET
    elif tensile_builtin.SUMMARY_SHEET in sheet_names:
        preferred_sheet = tensile_builtin.SUMMARY_SHEET
    else:
        preferred_sheet = sheet_names[0]
    return DataStudioWorkbook(
        workbook_id=str(workbook_path),
        workbook_path=workbook_path,
        label=label,
        template_match=TemplateMatch(
            template_id=template.id,
            label=template.label,
            family=template.family,
            confidence=0.9,
            reasons=("Loaded Data Studio workbook metadata.",),
            auto_selected=True,
        ),
        source_files=source_files,
        sheet_names=sheet_names,
        preferred_sheet=preferred_sheet,
        parsed_sample_count=sample_count,
        failed_sample_count=0,
        representative_filename=representative_filename,
        metrics=tuple(metric_summaries),
        warnings=warnings,
        samples=(),
    )


@lru_cache(maxsize=64)
def _import_workbook_cached(resolved_path: str, mtime_ns: int) -> DataStudioWorkbook:
    _ = mtime_ns
    return _import_workbook_from_path(Path(resolved_path))


def import_workbook(path: str | Path) -> DataStudioWorkbook:
    return _import_workbook_cached(*_workbook_cache_key(path))


def import_workbooks(path: str | Path) -> tuple[DataStudioWorkbook, ...]:
    workbook_path = ensure_input_path(str(Path(path).expanduser()))
    metadata = tensile_builtin.load_metadata_sheet(workbook_path)
    if looks_like_comparison_bundle(workbook_path, metadata):
        imported = import_source_workbooks_from_metadata(
            workbook_path,
            metadata,
            import_workbook=import_workbook,
        )
        if imported:
            return imported
        materialized = materialize_comparison_bundle_groups(
            workbook_path,
            metadata,
            import_workbook=import_workbook,
        )
        if materialized:
            return materialized
        raise ValueError(
            f"{workbook_path.name} looks like a comparison workbook, but Data Studio could not recover any "
            "single-group workbooks from it."
        )
    return (import_workbook(workbook_path),)


def preview_workbook(
    path: str | Path,
    *,
    specimen_states=None,
) -> DataStudioWorkbookPreview:
    bundle = load_workbook_specimen_bundle(path)
    return preview_loaded_workbook_bundle(bundle, specimen_states=specimen_states)


@lru_cache(maxsize=64)
def _load_workbook_specimen_bundle_cached(resolved_path: str, mtime_ns: int) -> LoadedWorkbookSpecimenBundle:
    _ = mtime_ns
    workbook = _import_workbook_cached(resolved_path, mtime_ns)
    return build_loaded_workbook_specimen_bundle(workbook)


def load_workbook_specimen_bundle(
    path: str | Path,
    *,
    workbook: DataStudioWorkbook | None = None,
) -> LoadedWorkbookSpecimenBundle:
    if workbook is not None:
        return build_loaded_workbook_specimen_bundle(workbook)
    return _load_workbook_specimen_bundle_cached(*_workbook_cache_key(path))


def load_filtered_workbook_context(
    path: str | Path,
    *,
    specimen_states=None,
    allow_empty: bool = False,
    bundle: LoadedWorkbookSpecimenBundle | None = None,
) -> FilteredWorkbookContext:
    active_bundle = bundle or load_workbook_specimen_bundle(path)
    return build_filtered_workbook_context(
        active_bundle,
        specimen_states=specimen_states,
        allow_empty=allow_empty,
    )


__all__ = [
    "FILTERED_WORKBOOK_DECIMAL_PLACES",
    "FILTERED_WORKBOOK_CURVE_DECIMAL_PLACES",
    "FilteredWorkbookContext",
    "LoadedWorkbookSpecimen",
    "LoadedWorkbookSpecimenBundle",
    "GENERIC_TEMPLATE_PARSE_STRATEGY",
    "_representative_scores",
    "build_workbook",
    "create_template_from_candidates",
    "export_filtered_workbook_from_context",
    "import_workbook",
    "import_workbooks",
    "load_filtered_workbook_context",
    "load_workbook_specimen_bundle",
    "parse_structured_sample",
    "preview_workbook",
]
