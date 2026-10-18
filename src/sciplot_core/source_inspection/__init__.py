"""Public API for source-shape recognition and template recommendation."""

from __future__ import annotations

from sciplot_core.source_inspection.inspection import (
    clear_inspection_cache,
    inspect_input_file,
)
from sciplot_core.source_inspection.models import (
    InputInspection,
    SourceIntent,
    TemplateRecommendation,
)
from sciplot_core.source_inspection.input_errors import SourceInputError


__all__ = [
    "InputInspection",
    "SourceIntent",
    "SourceInputError",
    "TemplateRecommendation",
    "clear_inspection_cache",
    "inspect_input_file",
]
