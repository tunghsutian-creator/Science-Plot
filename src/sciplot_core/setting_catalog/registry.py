"""Expose the closed per-object native inspector registry."""

from __future__ import annotations

from sciplot_core.setting_catalog.model import InspectorFieldSpec
from sciplot_core.setting_catalog.specs.page import PAGE_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.graph import GRAPH_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.axis import AXIS_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.colorbar import COLORBAR_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.xy import XY_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.boxplot import BOXPLOT_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.key import KEY_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.image import IMAGE_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.contour import CONTOUR_INSPECTOR_FIELDS
from sciplot_core.setting_catalog.specs.label import LABEL_INSPECTOR_FIELDS

OBJECT_INSPECTOR_SPECS: dict[str, tuple[InspectorFieldSpec, ...]] = {
    "page": PAGE_INSPECTOR_FIELDS,
    "graph": GRAPH_INSPECTOR_FIELDS,
    "axis": AXIS_INSPECTOR_FIELDS,
    "colorbar": COLORBAR_INSPECTOR_FIELDS,
    "xy": XY_INSPECTOR_FIELDS,
    "boxplot": BOXPLOT_INSPECTOR_FIELDS,
    "key": KEY_INSPECTOR_FIELDS,
    "image": IMAGE_INSPECTOR_FIELDS,
    "contour": CONTOUR_INSPECTOR_FIELDS,
    "label": LABEL_INSPECTOR_FIELDS,
}

SUPPORTED_INSPECTOR_TYPES = frozenset(OBJECT_INSPECTOR_SPECS)


def specs_for_object_type(
    object_type: str,
) -> tuple[InspectorFieldSpec, ...]:
    return OBJECT_INSPECTOR_SPECS.get(str(object_type), ())
