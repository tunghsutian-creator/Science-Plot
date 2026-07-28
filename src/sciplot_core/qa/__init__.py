"""Publication QA API and first-party compatibility facade."""

from __future__ import annotations

from sciplot_core.qa.artifacts import (  # noqa: F401
    _raster_visual_qa,
    _canonical_artifacts,
)
from sciplot_core.qa.format_pairing import (  # noqa: F401
    _normalized_export_format,
    _required_export_formats,
    _canonical_pairing_report,
)
from sciplot_core.qa.pdf_text import (  # noqa: F401
    _font_resource_info,
    _span_is_visible,
    _span_text_role,
    _text_object_info,
)
from sciplot_core.qa.pdf_graphics import (  # noqa: F401
    _embedded_raster_info,
    _stroke_info,
    _vector_color_info,
)
from sciplot_core.qa.pdf_inspection import (  # noqa: F401
    _pdf_info,
)
from sciplot_core.qa.tiff_inspection import (  # noqa: F401
    _tiff_info,
)
from sciplot_core.qa.audit_support import (  # noqa: F401
    _check,
    _normalized_font_name,
    _FONT_FAMILY_ALIASES,
    _font_family_key,
    _font_face_key,
    _font_allowed,
    _font_embedding_evidence,
    _matching_pdf,
    _candidate_path,
    _discover_veusz_documents,
    _run_veusz_audit,
    _publication_intent,
    _close,
    _bounds_close,
)
from sciplot_core.qa.fixed_frame import (  # noqa: F401
    _fixed_frame_report,
)
from sciplot_core.qa.semantic_labels import (  # noqa: F401
    _VEUSZ_SYMBOLS,
    _SUPERSCRIPT_TRANSLATION,
    _plain_veusz_label,
    _normalized_label,
    _flatten_label_values,
    _semantic_label_report,
    _scientific_unit_expression_report,
    _panel_typography_report,
)
from sciplot_core.qa.color_math import (  # noqa: F401
    _CVD_MATRICES,
    _srgb_to_linear,
    _linear_to_srgb,
    _simulate_cvd,
    _lab,
    _delta_e,
    _relative_luminance,
    _rgb_matches,
    _sample_color_scale,
    _turn_count,
)
from sciplot_core.qa.accessibility import (  # noqa: F401
    _series_accessibility_report,
)
from sciplot_core.qa.stroke_contract import (  # noqa: F401
    _vsz_stroke_report,
)
from sciplot_core.qa.publication_qa import (  # noqa: F401
    _publication_qa,
)
from sciplot_core.qa.run import (  # noqa: F401
    run_qa,
)
