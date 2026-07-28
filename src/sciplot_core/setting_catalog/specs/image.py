"""Declare editable fields for native Veusz image objects."""

from sciplot_core.setting_catalog.model import COMMON_VISIBILITY, _field

IMAGE_INSPECTOR_FIELDS = (
    COMMON_VISIBILITY,
    _field(
        "image_data",
        "Data authority",
        "Field dataset",
        "data",
        "dataset",
        read_only=True,
    ),
    _field("image_min", "Color range", "Minimum", "min", "number_or_auto"),
    _field("image_max", "Color range", "Maximum", "max", "number_or_auto"),
    _field(
        "image_scaling",
        "Color range",
        "Scaling",
        "colorScaling",
        "choice",
        immediate=True,
    ),
    _field("image_colormap", "Color", "Colormap", "colorMap", "text"),
    _field(
        "image_invert",
        "Color",
        "Invert colormap",
        "colorInvert",
        "boolean",
        immediate=True,
    ),
    _field(
        "image_transparency",
        "Color",
        "Transparency",
        "transparency",
        "integer",
        minimum=0,
        maximum=100,
    ),
    _field(
        "image_draw_mode",
        "Rendering",
        "Draw mode",
        "drawMode",
        "choice",
        immediate=True,
    ),
)
