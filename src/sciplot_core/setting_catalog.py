from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INSPECTOR_EDITORS = {
    "boolean",
    "choice",
    "color",
    "dataset",
    "distance",
    "float_list",
    "integer",
    "number",
    "number_or_auto",
    "read_only",
    "scalar_list",
    "text",
}


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class InspectorFieldSpec:
    field_id: str
    section: str
    label: str
    suffix: str
    editor: str
    immediate: bool = False
    read_only: bool = False
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    decimals: int = 4
    help_text: str = ""

    def __post_init__(self) -> None:
        _required_text(self.field_id, "field_id")
        _required_text(self.section, "section")
        _required_text(self.label, "label")
        _required_text(self.suffix, "suffix")
        if self.editor not in INSPECTOR_EDITORS:
            raise ValueError(f"Unsupported inspector editor: {self.editor!r}")
        if self.editor in {"dataset", "read_only"} and not self.read_only:
            raise ValueError(f"{self.editor} fields must be read-only.")
        if self.read_only and self.immediate:
            raise ValueError("Read-only inspector fields cannot be immediate.")
        if self.minimum is not None and self.maximum is not None:
            if float(self.minimum) > float(self.maximum):
                raise ValueError("Inspector field minimum cannot exceed maximum.")
        if not 0 <= self.decimals <= 12:
            raise ValueError("Inspector field decimals must be between 0 and 12.")


def _field(
    field_id: str,
    section: str,
    label: str,
    suffix: str,
    editor: str,
    *,
    immediate: bool = False,
    read_only: bool = False,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
    step: float | int | None = None,
    decimals: int = 4,
    help_text: str = "",
) -> InspectorFieldSpec:
    return InspectorFieldSpec(
        field_id=field_id,
        section=section,
        label=label,
        suffix=suffix,
        editor=editor,
        immediate=immediate,
        read_only=read_only,
        minimum=minimum,
        maximum=maximum,
        step=step,
        decimals=decimals,
        help_text=help_text,
    )


COMMON_VISIBILITY = _field(
    "hidden",
    "Object",
    "Hidden",
    "hide",
    "boolean",
    immediate=True,
    help_text="Hide this object without deleting it.",
)

OBJECT_INSPECTOR_SPECS: dict[str, tuple[InspectorFieldSpec, ...]] = {
    "page": (
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
    ),
    "graph": (
        COMMON_VISIBILITY,
        _field("left_margin", "Layout", "Left margin", "leftMargin", "distance"),
        _field(
            "right_margin", "Layout", "Right margin", "rightMargin", "distance"
        ),
        _field("top_margin", "Layout", "Top margin", "topMargin", "distance"),
        _field(
            "bottom_margin", "Layout", "Bottom margin", "bottomMargin", "distance"
        ),
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
    ),
    "axis": (
        COMMON_VISIBILITY,
        _field("axis_label", "Axis", "Label", "label", "text"),
        _field(
            "axis_min",
            "Range",
            "Minimum",
            "min",
            "number_or_auto",
            help_text='Use "Auto" for deterministic automatic range.',
        ),
        _field(
            "axis_max",
            "Range",
            "Maximum",
            "max",
            "number_or_auto",
            help_text='Use "Auto" for deterministic automatic range.',
        ),
        _field("axis_log", "Range", "Log scale", "log", "boolean", immediate=True),
        _field(
            "axis_autorange",
            "Range",
            "Auto-range padding",
            "autoRange",
            "choice",
            immediate=True,
        ),
        _field(
            "axis_reflect",
            "Placement",
            "Reflect ticks and text",
            "reflect",
            "boolean",
            immediate=True,
        ),
        _field(
            "axis_label_size",
            "Typography",
            "Label size",
            "Label/size",
            "distance",
        ),
        _field(
            "axis_label_color",
            "Typography",
            "Label color",
            "Label/color",
            "color",
        ),
        _field(
            "axis_label_bold",
            "Typography",
            "Bold label",
            "Label/bold",
            "boolean",
            immediate=True,
        ),
        _field(
            "tick_label_size",
            "Ticks",
            "Tick-label size",
            "TickLabels/size",
            "distance",
        ),
        _field(
            "tick_label_rotation",
            "Ticks",
            "Tick-label rotation",
            "TickLabels/rotate",
            "choice",
            immediate=True,
        ),
        _field(
            "tick_label_format",
            "Ticks",
            "Number format",
            "TickLabels/format",
            "text",
        ),
        _field(
            "major_tick_count",
            "Ticks",
            "Major ticks",
            "MajorTicks/number",
            "integer",
            minimum=2,
            maximum=24,
        ),
        _field(
            "major_tick_length",
            "Ticks",
            "Major tick length",
            "MajorTicks/length",
            "distance",
        ),
        _field(
            "minor_tick_count",
            "Ticks",
            "Minor ticks",
            "MinorTicks/number",
            "integer",
            minimum=0,
            maximum=100,
        ),
        _field(
            "minor_ticks_hidden",
            "Ticks",
            "Minor ticks hidden",
            "MinorTicks/hide",
            "boolean",
            immediate=True,
        ),
        _field(
            "grid_hidden",
            "Grid",
            "Major grid hidden",
            "GridLines/hide",
            "boolean",
            immediate=True,
        ),
        _field(
            "grid_color",
            "Grid",
            "Grid color",
            "GridLines/color",
            "color",
        ),
        _field(
            "grid_style",
            "Grid",
            "Grid style",
            "GridLines/style",
            "choice",
            immediate=True,
        ),
    ),
    "colorbar": (
        COMMON_VISIBILITY,
        _field("colorbar_label", "Color scale", "Label", "label", "text"),
        _field(
            "colorbar_min", "Range", "Minimum", "min", "number_or_auto"
        ),
        _field(
            "colorbar_max", "Range", "Maximum", "max", "number_or_auto"
        ),
        _field(
            "colorbar_log", "Range", "Log scale", "log", "boolean", immediate=True
        ),
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
        _field(
            "colorbar_width", "Placement", "Width", "width", "distance"
        ),
        _field(
            "colorbar_height", "Placement", "Height", "height", "distance"
        ),
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
    ),
    "xy": (
        COMMON_VISIBILITY,
        _field("series_name", "Series", "Legend name", "key", "text"),
        _field(
            "series_x_data",
            "Data authority",
            "X data",
            "xData",
            "dataset",
            read_only=True,
        ),
        _field(
            "series_y_data",
            "Data authority",
            "Y data",
            "yData",
            "dataset",
            read_only=True,
        ),
        _field(
            "series_marker",
            "Markers",
            "Marker",
            "marker",
            "choice",
            immediate=True,
        ),
        _field(
            "series_marker_size",
            "Markers",
            "Marker size",
            "markerSize",
            "distance",
        ),
        _field("series_color", "Markers", "Master color", "color", "color"),
        _field(
            "series_line_hidden",
            "Line",
            "Line hidden",
            "PlotLine/hide",
            "boolean",
            immediate=True,
        ),
        _field(
            "series_line_color",
            "Line",
            "Line color",
            "PlotLine/color",
            "color",
        ),
        _field(
            "series_line_width",
            "Line",
            "Line width",
            "PlotLine/width",
            "distance",
        ),
        _field(
            "series_line_style",
            "Line",
            "Line style",
            "PlotLine/style",
            "choice",
            immediate=True,
        ),
        _field(
            "series_interpolation",
            "Line",
            "Interpolation",
            "PlotLine/interpType",
            "choice",
            immediate=True,
        ),
        _field(
            "series_fill_hidden",
            "Marker fill",
            "Fill hidden",
            "MarkerFill/hide",
            "boolean",
            immediate=True,
        ),
        _field(
            "series_fill_color",
            "Marker fill",
            "Fill color",
            "MarkerFill/color",
            "color",
        ),
        _field(
            "series_fill_transparency",
            "Marker fill",
            "Transparency",
            "MarkerFill/transparency",
            "integer",
            minimum=0,
            maximum=100,
        ),
        _field(
            "series_error_style",
            "Errors",
            "Error style",
            "errorStyle",
            "choice",
            immediate=True,
        ),
    ),
    "boxplot": (
        COMMON_VISIBILITY,
        _field(
            "boxplot_values",
            "Data authority",
            "Value datasets",
            "values",
            "dataset",
            read_only=True,
        ),
        _field(
            "boxplot_width",
            "Geometry",
            "Box width",
            "fillfraction",
            "number",
            minimum=0.05,
            maximum=1.0,
            step=0.02,
        ),
        _field(
            "boxplot_outlier_marker",
            "Markers",
            "Outlier marker",
            "outliersmarker",
            "choice",
            immediate=True,
        ),
        _field(
            "boxplot_marker_size",
            "Markers",
            "Marker size",
            "markerSize",
            "distance",
        ),
        _field("boxplot_fill_color", "Fill", "Fill color", "Fill/color", "color"),
        _field(
            "boxplot_fill_transparency",
            "Fill",
            "Transparency",
            "Fill/transparency",
            "integer",
            minimum=0,
            maximum=100,
        ),
        _field(
            "boxplot_fill_hidden",
            "Fill",
            "Fill hidden",
            "Fill/hide",
            "boolean",
            immediate=True,
        ),
        _field(
            "boxplot_border_color",
            "Outline",
            "Border color",
            "Border/color",
            "color",
        ),
        _field(
            "boxplot_border_width",
            "Outline",
            "Border width",
            "Border/width",
            "distance",
        ),
        _field(
            "boxplot_border_style",
            "Outline",
            "Border style",
            "Border/style",
            "choice",
            immediate=True,
        ),
        _field(
            "boxplot_whisker_color",
            "Whiskers",
            "Whisker color",
            "Whisker/color",
            "color",
        ),
        _field(
            "boxplot_whisker_width",
            "Whiskers",
            "Whisker width",
            "Whisker/width",
            "distance",
        ),
    ),
    "key": (
        COMMON_VISIBILITY,
        _field("legend_title", "Legend", "Title", "title", "text"),
        _field(
            "legend_columns",
            "Legend",
            "Columns",
            "columns",
            "integer",
            minimum=1,
            maximum=12,
        ),
        _field(
            "legend_horizontal",
            "Placement",
            "Horizontal position",
            "horzPosn",
            "choice",
            immediate=True,
        ),
        _field(
            "legend_vertical",
            "Placement",
            "Vertical position",
            "vertPosn",
            "choice",
            immediate=True,
        ),
        _field(
            "legend_manual_x",
            "Placement",
            "Manual X",
            "horzManual",
            "number",
            minimum=0.0,
            maximum=1.0,
            step=0.01,
        ),
        _field(
            "legend_manual_y",
            "Placement",
            "Manual Y",
            "vertManual",
            "number",
            minimum=0.0,
            maximum=1.0,
            step=0.01,
        ),
        _field(
            "legend_reverse",
            "Order",
            "Reverse order",
            "orderswap",
            "boolean",
            immediate=True,
        ),
        _field(
            "legend_symbol_swap",
            "Order",
            "Symbols on right",
            "symbolswap",
            "boolean",
            immediate=True,
        ),
        _field(
            "legend_text_size",
            "Typography",
            "Text size",
            "Text/size",
            "distance",
        ),
        _field(
            "legend_text_color",
            "Typography",
            "Text color",
            "Text/color",
            "color",
        ),
        _field(
            "legend_background_hidden",
            "Appearance",
            "Background hidden",
            "Background/hide",
            "boolean",
            immediate=True,
        ),
        _field(
            "legend_background_color",
            "Appearance",
            "Background color",
            "Background/color",
            "color",
        ),
        _field(
            "legend_border_hidden",
            "Appearance",
            "Border hidden",
            "Border/hide",
            "boolean",
            immediate=True,
        ),
        _field(
            "legend_border_color",
            "Appearance",
            "Border color",
            "Border/color",
            "color",
        ),
        _field(
            "legend_border_width",
            "Appearance",
            "Border width",
            "Border/width",
            "distance",
        ),
    ),
    "image": (
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
    ),
    "contour": (
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
    ),
    "label": (
        COMMON_VISIBILITY,
        _field("annotation_text", "Annotation", "Text", "label", "text"),
        _field(
            "annotation_x",
            "Position",
            "X position",
            "xPos",
            "scalar_list",
            minimum=-10.0,
            maximum=10.0,
        ),
        _field(
            "annotation_y",
            "Position",
            "Y position",
            "yPos",
            "scalar_list",
            minimum=-10.0,
            maximum=10.0,
        ),
        _field(
            "annotation_coordinate_mode",
            "Position",
            "Coordinate mode",
            "positioning",
            "choice",
            immediate=True,
        ),
        _field(
            "annotation_align_horizontal",
            "Position",
            "Horizontal alignment",
            "alignHorz",
            "choice",
            immediate=True,
        ),
        _field(
            "annotation_align_vertical",
            "Position",
            "Vertical alignment",
            "alignVert",
            "choice",
            immediate=True,
        ),
        _field(
            "annotation_angle",
            "Position",
            "Rotation",
            "angle",
            "number",
            minimum=-360.0,
            maximum=360.0,
            step=5.0,
        ),
        _field(
            "annotation_text_size",
            "Typography",
            "Text size",
            "Text/size",
            "distance",
        ),
        _field(
            "annotation_text_color",
            "Typography",
            "Text color",
            "Text/color",
            "color",
        ),
        _field(
            "annotation_bold",
            "Typography",
            "Bold",
            "Text/bold",
            "boolean",
            immediate=True,
        ),
        _field(
            "annotation_italic",
            "Typography",
            "Italic",
            "Text/italic",
            "boolean",
            immediate=True,
        ),
    ),
}

SUPPORTED_INSPECTOR_TYPES = frozenset(OBJECT_INSPECTOR_SPECS)


def specs_for_object_type(object_type: str) -> tuple[InspectorFieldSpec, ...]:
    return OBJECT_INSPECTOR_SPECS.get(str(object_type), ())


__all__ = [
    "INSPECTOR_EDITORS",
    "OBJECT_INSPECTOR_SPECS",
    "SUPPORTED_INSPECTOR_TYPES",
    "InspectorFieldSpec",
    "specs_for_object_type",
]
