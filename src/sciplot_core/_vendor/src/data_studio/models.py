from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Literal


def serialize_model(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: serialize_model(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: serialize_model(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_model(item) for item in value]
    return value


@dataclass(frozen=True)
class DataStudioRange:
    sheet_name: str
    start_row: int
    end_row: int
    start_col: int
    end_col: int


@dataclass(frozen=True)
class SheetBlock:
    id: str
    sheet_name: str
    label: str
    row_count: int
    col_count: int
    range: DataStudioRange
    header_row_index: int | None = None
    unit_row_index: int | None = None
    data_start_row_index: int | None = None
    sample_rows: tuple[tuple[Any, ...], ...] = ()


@dataclass(frozen=True)
class FieldCandidate:
    id: str
    kind: str
    label: str
    confidence: float
    rationale: str
    sheet_name: str
    block_id: str | None = None
    range: DataStudioRange | None = None
    sample_values: tuple[str, ...] = ()
    unit_hint: str | None = None


@dataclass(frozen=True)
class PreviewRange:
    sheet_name: str
    block_id: str | None
    start_row: int
    end_row: int
    start_col: int
    end_col: int
    role: str


@dataclass(frozen=True)
class BindingSuggestion:
    id: str
    kind: str
    title: str
    summary: str
    sheet_name: str
    block_id: str | None
    candidate_ids: tuple[str, ...]
    preview_ranges: tuple[PreviewRange, ...] = ()
    default_selected: bool = False
    rationale: str = ""
    confidence: float | None = None


@dataclass(frozen=True)
class RawSheetPreview:
    sheet_name: str
    row_count: int
    col_count: int
    sample_rows: tuple[tuple[Any, ...], ...]
    blocks: tuple[SheetBlock, ...]


@dataclass(frozen=True)
class RawFilePreview:
    source_path: Path
    file_type: str
    encoding: str | None
    delimiter: str | None
    sheet_names: tuple[str, ...]
    sheets: tuple[RawSheetPreview, ...]
    field_candidates: tuple[FieldCandidate, ...]
    binding_suggestions: tuple[BindingSuggestion, ...] = ()
    recommended_template_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


TemplateFieldRole = Literal[
    "curve_x",
    "curve_y",
    "metadata",
    "metric",
    "summary_metric",
    "header",
    "unit",
    "group",
    "sample",
    "matrix_x",
    "matrix_y",
    "matrix_z",
]


@dataclass(frozen=True)
class TemplateFieldBinding:
    id: str
    role: TemplateFieldRole
    label: str
    sheet_name: str | None = None
    block_id: str | None = None
    column_name: str | None = None
    column_index: int | None = None
    row_label_contains: str | None = None
    cell_value_contains: tuple[str, ...] = ()
    unit_hint: str | None = None
    sample_name: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class TemplateMatchCondition:
    sheet_name_contains: tuple[str, ...] = ()
    text_contains: tuple[str, ...] = ()
    field_kinds: tuple[str, ...] = ()
    minimum_score: float = 0.0


@dataclass(frozen=True)
class TemplateSourceFormat:
    encoding: str | None = None
    delimiter: str | None = None
    sheet_name: str | None = None


@dataclass(frozen=True)
class TemplateSegmentSelector:
    id: str
    label: str
    result_label: str | None = None
    interval_index: int | None = None
    header_row_index: int | None = None
    unit_row_index: int | None = None
    data_start_row_index: int | None = None
    start_row: int | None = None
    end_row: int | None = None


@dataclass(frozen=True)
class TemplateDefinition:
    version: int
    id: str
    label: str
    family: str
    builtin: bool
    description: str
    file_types: tuple[str, ...]
    parse_strategy: str
    match_conditions: tuple[TemplateMatchCondition, ...] = ()
    field_bindings: tuple[TemplateFieldBinding, ...] = ()
    workbook_metric_ids: tuple[str, ...] = ()
    default_group_name_strategy: str = "common_prefix"
    preferred_sheet_name: str = "Representative_Curve"
    output_kind: str = "curve_metrics"
    comparison_enabled: bool = True
    source_format: TemplateSourceFormat = field(default_factory=TemplateSourceFormat)
    segment_policy: str = "single_table"
    segment_selectors: tuple[TemplateSegmentSelector, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateMatch:
    template_id: str
    label: str
    family: str
    confidence: float
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    matched_sheet_names: tuple[str, ...] = ()
    auto_selected: bool = False
    matched_roles: tuple[dict[str, Any], ...] = ()
    missing_roles: tuple[str, ...] = ()
    ambiguous_roles: tuple[str, ...] = ()
    matched_structure_id: str | None = None
    diagnostics: tuple[dict[str, Any], ...] = ()
    recommendation_source: str = "rule"


@dataclass(frozen=True)
class TemplatePreviewSegment:
    id: str
    label: str
    curve_count: int = 0
    metric_count: int = 0
    row_count: int = 0


@dataclass(frozen=True)
class TemplateApplyPreview:
    template_id: str
    output_kind: str
    parsed_sample_count: int
    failed_sample_count: int
    series_count: int
    metric_count: int
    matrix_row_count: int
    missing_roles: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    segments: tuple[TemplatePreviewSegment, ...] = ()
    normalized_output_preview: dict[str, Any] | None = None
    data_containers: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class WorkbookMetricSummary:
    id: str
    label: str
    unit: str
    mean: float | None
    std: float | None


@dataclass(frozen=True)
class WorkbookSample:
    id: str
    source_path: Path
    filename: str
    parsed: bool
    warnings: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    metrics: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class DataStudioCurvePoint:
    x: float
    y: float


@dataclass(frozen=True)
class DataStudioSpecimenState:
    workbook_path: str
    specimen_id: str
    included: bool = True
    selected_as_representative: bool = False


@dataclass(frozen=True)
class DataStudioSpecimenPreview:
    specimen_id: str
    label: str
    filename: str
    source_path: Path | None
    included: bool
    metrics: dict[str, float | None] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    mini_curve_points: tuple[DataStudioCurvePoint, ...] = ()
    triad_complete: bool = False
    suggested_exclusion: bool = False
    composite_signed_score: float | None = None
    distance_from_mean_score: float | None = None
    score_side: str = "ineligible"
    auto_rule_role: str = "ineligible"
    eligible_for_auto_filter: bool = False


@dataclass(frozen=True)
class DataStudioWorkbook:
    workbook_id: str
    workbook_path: Path
    label: str
    template_match: TemplateMatch
    source_files: tuple[Path, ...]
    sheet_names: tuple[str, ...]
    preferred_sheet: str
    parsed_sample_count: int
    failed_sample_count: int
    representative_filename: str
    metrics: tuple[WorkbookMetricSummary, ...]
    warnings: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    samples: tuple[WorkbookSample, ...] = ()
    data_containers: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DataStudioWorkbookPreview:
    workbook_path: Path
    label: str
    supported: bool
    unsupported_reason: str = ""
    total_specimen_count: int = 0
    included_specimen_count: int = 0
    excluded_specimen_count: int = 0
    representative_specimen_id: str | None = None
    representative_filename: str | None = None
    metrics: tuple[WorkbookMetricSummary, ...] = ()
    specimens: tuple[DataStudioSpecimenPreview, ...] = ()
    warnings: tuple[str, ...] = ()
    suggested_exclusion_ids: tuple[str, ...] = ()
    suggestion_supported: bool = False
    suggestion_support_reason: str = ""


@dataclass(frozen=True)
class DataStudioGroupState:
    workbook_path: str
    display_name: str
    include_in_compare: bool = True
    sort_order: int = 0


@dataclass(frozen=True)
class ComparisonRecipe:
    id: str
    label: str
    category: str
    template_id: str
    sheet_name: str
    metric_id: str | None = None
    enabled_by_default: bool = True
    supported: bool = True
    support_reason: str = ""


@dataclass(frozen=True)
class DataStudioFigureOutput:
    path: Path
    label: str
    category: str
    template_id: str
    sheet_name: str
    metric_id: str | None = None
    recipe_id: str | None = None


@dataclass(frozen=True)
class DataStudioFilteredWorkbookOutput:
    path: Path
    label: str
    source_workbook_path: Path
    representative_filename: str


@dataclass(frozen=True)
class ComparisonSet:
    id: str
    label: str
    workbook_paths: tuple[Path, ...]
    workbook_labels: tuple[str, ...]
    comparison_workbook_path: Path
    recipes: tuple[ComparisonRecipe, ...]


@dataclass(frozen=True)
class DataStudioFigurePreference:
    family_id: str
    selected_template_id: str | None
    options_by_template: dict[str, dict[str, Any]] = field(default_factory=dict)
    fit_options_by_template: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class DataStudioSessionPayload:
    version: int
    selected_template_id: str | None
    selected_workbook_id: str | None
    primary_workbook_id: str | None
    selected_recipe_id: str | None
    workbook_paths: tuple[str, ...]
    comparison_recipe_ids: tuple[str, ...]
    selected_figure_family_id: str | None = None
    selected_figure_template_id: str | None = None
    group_states: tuple[DataStudioGroupState, ...] = ()
    specimen_states: tuple[DataStudioSpecimenState, ...] = ()
    figure_preferences: tuple[DataStudioFigurePreference, ...] = ()
    imported_paths: tuple[str, ...] = ()
    template_draft_path: str | None = None


__all__ = [
    "ComparisonRecipe",
    "ComparisonSet",
    "DataStudioFilteredWorkbookOutput",
    "DataStudioFigurePreference",
    "DataStudioFigureOutput",
    "DataStudioGroupState",
    "DataStudioRange",
    "DataStudioSessionPayload",
    "DataStudioWorkbook",
    "BindingSuggestion",
    "FieldCandidate",
    "PreviewRange",
    "RawFilePreview",
    "RawSheetPreview",
    "SheetBlock",
    "TemplateDefinition",
    "TemplateApplyPreview",
    "TemplateFieldBinding",
    "TemplateMatch",
    "TemplateMatchCondition",
    "TemplatePreviewSegment",
    "TemplateSegmentSelector",
    "TemplateSourceFormat",
    "WorkbookMetricSummary",
    "WorkbookSample",
    "serialize_model",
]
