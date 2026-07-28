"""Declare editable fields for native Veusz page objects."""

from sciplot_core.setting_catalog.model import COMMON_VISIBILITY, _field

PAGE_INSPECTOR_FIELDS = (
    COMMON_VISIBILITY,
    _field(
        "page_width",
        "Publication frame",
        "Width",
        "width",
        "read_only",
        read_only=True,
        help_text="Managed by the SciPlot figure-size contract.",
    ),
    _field(
        "page_height",
        "Publication frame",
        "Height",
        "height",
        "read_only",
        read_only=True,
        help_text="Managed by the SciPlot figure-size contract.",
    ),
    _field(
        "page_background_color",
        "Appearance",
        "Page background",
        "Background/color",
        "color",
    ),
    _field(
        "page_background_hidden",
        "Appearance",
        "Background hidden",
        "Background/hide",
        "boolean",
        immediate=True,
    ),
)
