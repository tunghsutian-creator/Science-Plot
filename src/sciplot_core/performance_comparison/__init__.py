"""Public performance-comparison API and compatibility facade."""

from __future__ import annotations

from sciplot_core.performance_comparison.models import (  # noqa: F401
    PERFORMANCE_COMPARISON_RULE_ID,
    PERFORMANCE_SCATTER_TEMPLATE_ID,
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PerformanceComparisonError,
    PerformanceMetric,
    PerformanceMaterial,
    PerformanceComparison,
    _display_unit,
)
from sciplot_core.policy import (
    PERFORMANCE_PANEL_HEIGHT_MM as PERFORMANCE_PANEL_HEIGHT_MM,
    PERFORMANCE_PANEL_WIDTH_MM as PERFORMANCE_PANEL_WIDTH_MM,
)
from sciplot_core.performance_comparison.source_values import (  # noqa: F401
    _HEADER_ALIASES,
    _REQUIRED_COLUMNS,
    _ROLE_ALIASES,
    _DIRECTION_ALIASES,
    _token,
    _text,
    _year_text,
    _finite_float,
    _optional_float,
)
from sciplot_core.performance_comparison.source_tables import (  # noqa: F401
    _resolve_source,
    _read_text_table,
    _read_source_frame,
    _canonical_header_map,
    _required_headers_present,
    _source_has_required_headers,
    is_performance_comparison_source,
)
from sciplot_core.performance_comparison.field_validation import (  # noqa: F401
    _unique_text,
    _unique_float,
    _unique_bool,
    _normalized_role,
    _normalized_direction,
    _normalized_scatter_axis,
    _normalized_marker,
    _normalized_marker_fill_color,
    _normalized_marker_line_color,
)
from sciplot_core.performance_comparison.source_loading import (  # noqa: F401
    load_performance_comparison,
)
from sciplot_core.performance_comparison.geometry import (  # noqa: F401
    _axis_bounds,
    _convex_hull,
    _circle_polygon,
    _capsule_polygon,
    _chaikin_closed_polygon,
    _irregularize_polygon,
    _expanded_envelope,
)
from sciplot_core.performance_comparison.styles import (  # noqa: F401
    _sample_group_colors,
    _reference_group_colors,
    _material_styles,
)
from sciplot_core.performance_comparison.layout import (  # noqa: F401
    _legend_items,
    _layout_payload,
    _uses_compact_inside_legend,
    _deterministic_scatter_x_values,
)
from sciplot_core.performance_comparison.scatter import (  # noqa: F401
    build_performance_scatter_payload,
)
from sciplot_core.performance_comparison.radar import (  # noqa: F401
    _normalized_radar_value,
    build_performance_radar_payload,
)
from sciplot_core.performance_comparison.public_api import (  # noqa: F401
    prepare_performance_comparison,
    performance_transform_parameters,
)

__all__ = [
    "PERFORMANCE_COMPARISON_RULE_ID",
    "PERFORMANCE_PANEL_HEIGHT_MM",
    "PERFORMANCE_PANEL_WIDTH_MM",
    "PERFORMANCE_RADAR_TEMPLATE_ID",
    "PERFORMANCE_SCATTER_TEMPLATE_ID",
    "PerformanceComparison",
    "PerformanceComparisonError",
    "PerformanceMaterial",
    "PerformanceMetric",
    "build_performance_radar_payload",
    "build_performance_scatter_payload",
    "is_performance_comparison_source",
    "load_performance_comparison",
    "performance_transform_parameters",
    "prepare_performance_comparison",
]
