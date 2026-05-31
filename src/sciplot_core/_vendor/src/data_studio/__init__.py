from __future__ import annotations

from importlib import import_module
from typing import Any

from src.data_studio import template_store
from src.data_studio.models import (
    ComparisonRecipe,
    ComparisonSet,
    DataStudioCurvePoint,
    DataStudioFigureOutput,
    DataStudioFigurePreference,
    DataStudioFilteredWorkbookOutput,
    DataStudioGroupState,
    DataStudioSessionPayload,
    DataStudioSpecimenPreview,
    DataStudioSpecimenState,
    DataStudioWorkbook,
    DataStudioWorkbookPreview,
    FieldCandidate,
    RawFilePreview,
    SheetBlock,
    TemplateDefinition,
    TemplateMatch,
    WorkbookMetricSummary,
    WorkbookSample,
)

_LAZY_EXPORTS = {
    "build_comparison_set": ("src.data_studio.comparison", "build_comparison_set"),
    "comparison_recipes_for_workbooks": ("src.data_studio.comparison", "comparison_recipes_for_workbooks"),
    "export_comparison_bundle": ("src.data_studio.comparison", "export_comparison_bundle"),
    "materialize_comparison_context": ("src.data_studio.comparison", "materialize_comparison_context"),
    "preview_comparison_recipe": ("src.data_studio.comparison", "preview_comparison_recipe"),
    "build_data_studio_workbook": ("src.data_studio.service", "build_data_studio_workbook"),
    "create_data_studio_template": ("src.data_studio.service", "create_data_studio_template"),
    "delete_data_studio_template": ("src.data_studio.service", "delete_data_studio_template"),
    "export_data_studio_comparison": ("src.data_studio.service", "export_data_studio_comparison"),
    "import_data_studio_workbook": ("src.data_studio.service", "import_data_studio_workbook"),
    "list_data_studio_recipes": ("src.data_studio.service", "list_data_studio_recipes"),
    "list_data_studio_templates": ("src.data_studio.service", "list_data_studio_templates"),
    "normalize_session_payload": ("src.data_studio.service", "normalize_session_payload"),
    "preview_and_recommend": ("src.data_studio.ingest", "preview_and_recommend"),
    "preview_data_studio_workbook": ("src.data_studio.service", "preview_data_studio_workbook"),
    "preview_data_studio_comparison": ("src.data_studio.service", "preview_data_studio_comparison"),
    "preview_data_studio_comparison_context": ("src.data_studio.service", "preview_data_studio_comparison_context"),
    "preview_raw_file": ("src.data_studio.ingest", "preview_raw_file"),
    "update_data_studio_template": ("src.data_studio.service", "update_data_studio_template"),
    "load_template": ("src.data_studio.template_store", "load_template"),
    "create_template_from_candidates": ("src.data_studio.workbooks", "create_template_from_candidates"),
}

__all__ = [
    "ComparisonRecipe",
    "ComparisonSet",
    "DataStudioCurvePoint",
    "DataStudioFilteredWorkbookOutput",
    "DataStudioFigurePreference",
    "DataStudioFigureOutput",
    "DataStudioGroupState",
    "DataStudioSpecimenPreview",
    "DataStudioSpecimenState",
    "DataStudioSessionPayload",
    "DataStudioWorkbook",
    "DataStudioWorkbookPreview",
    "FieldCandidate",
    "RawFilePreview",
    "SheetBlock",
    "TemplateDefinition",
    "TemplateMatch",
    "WorkbookMetricSummary",
    "WorkbookSample",
    "template_store",
    *_LAZY_EXPORTS.keys(),
]


def __getattr__(name: str) -> Any:
    if name == "template_store":
        return template_store
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attribute)
    globals()[name] = value
    return value
