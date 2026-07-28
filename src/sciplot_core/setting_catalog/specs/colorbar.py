"""Declare editable fields for native Veusz colorbar objects."""

from sciplot_core.setting_catalog.model import COMMON_VISIBILITY, _field

COLORBAR_INSPECTOR_FIELDS = (
    COMMON_VISIBILITY,
    _field("colorbar_label", "Color scale", "Label", "label", "text"),
    _field("colorbar_min", "Range", "Minimum", "min", "number_or_auto"),
    _field("colorbar_max", "Range", "Maximum", "max", "number_or_auto"),
    _field("colorbar_log", "Range", "Log scale", "log", "boolean", immediate=True),
    _field(
        "colorbar_horizontal",
        "Placement",
        "Horizontal position",
        "horzPosn",
        "choice",
        immediate=True,
    ),
    _field(
        "colorbar_vertical",
        "Placement",
        "Vertical position",
        "vertPosn",
        "choice",
        immediate=True,
    ),
    _field("colorbar_width", "Placement", "Width", "width", "distance"),
    _field("colorbar_height", "Placement", "Height", "height", "distance"),
    _field(
        "colorbar_label_size",
        "Typography",
        "Label size",
        "Label/size",
        "distance",
    ),
    _field(
        "colorbar_tick_size",
        "Typography",
        "Tick-label size",
        "TickLabels/size",
        "distance",
    ),
    _field(
        "colorbar_border_color",
        "Appearance",
        "Border color",
        "Border/color",
        "color",
    ),
    _field(
        "colorbar_border_width",
        "Appearance",
        "Border width",
        "Border/width",
        "distance",
    ),
)
