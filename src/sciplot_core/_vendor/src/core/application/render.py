from src.rendering.cache import read_raw_table_cached
from src.rendering.constants import (
    DEFAULT_SIZE_BY_TEMPLATE,
    PALETTE_PRESET_CHOICES,
    SIZE_CHOICES,
    STYLE_PRESET_CHOICES,
    TEMPLATE_CHOICES,
)
from src.rendering.dataset_models import (
    NormalizedDataset,
    build_normalized_dataset,
    dataframe_sample_rows,
    normalized_dataset_payload,
)
from src.rendering.io import (
    coerce_sheet,
    default_output_dir,
    ensure_input_path,
    list_sheet_names,
    normalize_input_path_text,
    resolve_output_dir,
)
from src.rendering.models import (
    InputInspection,
    PreflightResult,
    Recommendation,
    RenderedPlot,
    RenderOptions,
    TemplateRenderer,
)
from src.rendering.options import resolve_render_options, validate_template_name
from src.rendering.preflight import preflight_render_request
from src.rendering.recommendation import inspect_input_file
from src.rendering.recommender_models import TemplateRecommendation
from src.rendering.render_registry import TEMPLATE_RENDERERS
from src.rendering.render_service import (
    build_rendered_plots,
    build_rendered_plots_from_options,
    close_rendered_plots,
    export_rendered_plots,
    render_template,
)
from src.rendering.template_lifecycle import resolve_template_id, template_identity
from src.submission import build_render_submission_report

__all__ = [
    "DEFAULT_SIZE_BY_TEMPLATE",
    "InputInspection",
    "NormalizedDataset",
    "PALETTE_PRESET_CHOICES",
    "PreflightResult",
    "Recommendation",
    "RenderedPlot",
    "RenderOptions",
    "SIZE_CHOICES",
    "STYLE_PRESET_CHOICES",
    "TEMPLATE_CHOICES",
    "TEMPLATE_RENDERERS",
    "TemplateRecommendation",
    "TemplateRenderer",
    "build_normalized_dataset",
    "build_render_submission_report",
    "build_rendered_plots",
    "build_rendered_plots_from_options",
    "close_rendered_plots",
    "coerce_sheet",
    "dataframe_sample_rows",
    "default_output_dir",
    "ensure_input_path",
    "export_rendered_plots",
    "inspect_input_file",
    "list_sheet_names",
    "normalize_input_path_text",
    "normalized_dataset_payload",
    "preflight_render_request",
    "read_raw_table_cached",
    "render_template",
    "resolve_output_dir",
    "resolve_render_options",
    "resolve_template_id",
    "template_identity",
    "validate_template_name",
]
