"""Performance Veusz contract and compatibility facade."""

from __future__ import annotations

from sciplot_core.performance_veusz.style import (  # noqa: F401
    _RADAR_AXIS_LIMIT,
    _RADAR_LABEL_HORIZONTAL_RADIUS_LEFT,
    _RADAR_LABEL_HORIZONTAL_RADIUS_RIGHT,
    _RADAR_LABEL_VERTICAL_RADIUS,
    _RADAR_ENDPOINT_LABEL_RADIUS,
    _RADAR_RING_LEVELS,
    _RADAR_FIVE_AXIS_ANGLES,
    _RADAR_FIVE_AXIS_TITLE_X_MM,
    _RADAR_FIVE_AXIS_TITLE_CENTRE_Y_MM,
    _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM,
    _RADAR_FIVE_AXIS_ENDPOINT_OFFSETS_MM,
    _LEGEND_PAIRED_SLOT_OFFSET_MM,
    _pt,
    _cm_from_mm,
    _literal_text,
    _style_payload,
    _axis_payload,
    _expanded_axis_bounds,
    _performance_render_options,
    _inside_legend_contract,
)
from sciplot_core.performance_veusz.geometry import (  # noqa: F401
    _radar_cartesian,
    performance_series_records,
    _performance_polygons,
    _marker_polygon,
    _performance_lines,
)
from sciplot_core.performance_veusz.legend_layout import (  # noqa: F401
    _label_contract,
    _legend_layout,
)
from sciplot_core.performance_veusz.labels import (  # noqa: F401
    _performance_labels,
    _five_axis_radar_labels,
)
from sciplot_core.performance_veusz.spec_builder import (  # noqa: F401
    build_performance_veusz_spec,
)
from sciplot_core.performance_veusz.contracts import (  # noqa: F401
    performance_polygon_contracts,
    performance_line_contracts,
    performance_label_contracts,
)
from sciplot_core.performance_veusz.widget_apply import (  # noqa: F401
    _add_label,
    _add_axis,
    _apply_inside_key_position,
    _add_inside_key,
    _add_xy_series,
    _add_polygon,
    _add_line,
)
from sciplot_core.performance_veusz.apply import (  # noqa: F401
    apply_performance_veusz_spec,
)
