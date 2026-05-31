from src.rendering.cache import clear_input_cache
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
    clear_normalized_dataset_cache,
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
from src.rendering.recommendation import clear_inspection_cache, inspect_input_file
from src.rendering.recommender_models import TemplateRecommendation
from src.rendering.render_registry import TEMPLATE_RENDERERS
from src.rendering.render_service import (
    build_rendered_plots,
    close_rendered_plots,
    export_rendered_plots,
    render_template,
)
from src.rendering.tensile_compare import (
    export_tensile_comparison_bundle,
    inspect_tensile_workbook,
)

__all__ = [
    "DEFAULT_SIZE_BY_TEMPLATE",
    "InputInspection",
    "NormalizedDataset",
    "PALETTE_PRESET_CHOICES",
    "PreflightResult",
    "Recommendation",
    "TemplateRecommendation",
    "RenderOptions",
    "RenderedPlot",
    "SIZE_CHOICES",
    "STYLE_PRESET_CHOICES",
    "TEMPLATE_CHOICES",
    "TEMPLATE_RENDERERS",
    "TemplateRenderer",
    "build_rendered_plots",
    "build_normalized_dataset",
    "clear_inspection_cache",
    "clear_input_cache",
    "clear_normalized_dataset_cache",
    "close_rendered_plots",
    "coerce_sheet",
    "default_output_dir",
    "ensure_input_path",
    "export_rendered_plots",
    "export_tensile_comparison_bundle",
    "inspect_input_file",
    "inspect_tensile_workbook",
    "list_sheet_names",
    "normalize_input_path_text",
    "preflight_render_request",
    "render_template",
    "resolve_output_dir",
    "resolve_render_options",
    "validate_template_name",
]
