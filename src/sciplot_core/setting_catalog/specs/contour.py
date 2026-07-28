"""Declare editable fields for native Veusz contour objects."""

from sciplot_core.setting_catalog.model import COMMON_VISIBILITY, _field

CONTOUR_INSPECTOR_FIELDS = (
    COMMON_VISIBILITY,
    _field(
        "contour_data",
        "Data authority",
        "Field dataset",
        "data",
        "dataset",
        read_only=True,
    ),
    _field("contour_min", "Levels", "Minimum", "min", "number_or_auto"),
    _field("contour_max", "Levels", "Maximum", "max", "number_or_auto"),
    _field(
        "contour_scaling",
        "Levels",
        "Level mode",
        "scaling",
        "choice",
        immediate=True,
    ),
    _field(
        "contour_count",
        "Levels",
        "Level count",
        "numLevels",
        "integer",
        minimum=1,
        maximum=50,
    ),
    _field(
        "contour_manual_levels",
        "Levels",
        "Manual levels",
        "manualLevels",
        "float_list",
        help_text="Comma-separated numeric contour levels.",
    ),
    _field(
        "contour_labels_hidden",
        "Labels",
        "Labels hidden",
        "ContourLabels/hide",
        "boolean",
        immediate=True,
    ),
    _field(
        "contour_label_size",
        "Labels",
        "Label size",
        "ContourLabels/size",
        "distance",
    ),
    _field(
        "contour_label_color",
        "Labels",
        "Label color",
        "ContourLabels/color",
        "color",
    ),
)
