"""Declare editable fields for native Veusz graph objects."""

from sciplot_core.setting_catalog.model import COMMON_VISIBILITY, _field

GRAPH_INSPECTOR_FIELDS = (
    COMMON_VISIBILITY,
    _field("left_margin", "Layout", "Left margin", "leftMargin", "distance"),
    _field("right_margin", "Layout", "Right margin", "rightMargin", "distance"),
    _field("top_margin", "Layout", "Top margin", "topMargin", "distance"),
    _field("bottom_margin", "Layout", "Bottom margin", "bottomMargin", "distance"),
    _field(
        "aspect",
        "Layout",
        "Aspect ratio",
        "aspect",
        "number_or_auto",
        minimum=0.01,
        maximum=100.0,
    ),
    _field(
        "graph_background_color",
        "Appearance",
        "Plot background",
        "Background/color",
        "color",
    ),
    _field(
        "graph_background_hidden",
        "Appearance",
        "Background hidden",
        "Background/hide",
        "boolean",
        immediate=True,
    ),
    _field(
        "graph_border_color",
        "Appearance",
        "Border color",
        "Border/color",
        "color",
    ),
    _field(
        "graph_border_width",
        "Appearance",
        "Border width",
        "Border/width",
        "distance",
    ),
    _field(
        "graph_border_hidden",
        "Appearance",
        "Border hidden",
        "Border/hide",
        "boolean",
        immediate=True,
    ),
)
