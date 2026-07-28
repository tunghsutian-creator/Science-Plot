"""Native object inspector setting catalog API."""

from sciplot_core.setting_catalog.model import (
    INSPECTOR_EDITORS,
    InspectorFieldSpec,
)
from sciplot_core.setting_catalog.registry import (
    OBJECT_INSPECTOR_SPECS,
    SUPPORTED_INSPECTOR_TYPES,
    specs_for_object_type,
)

__all__ = [
    "INSPECTOR_EDITORS",
    "OBJECT_INSPECTOR_SPECS",
    "SUPPORTED_INSPECTOR_TYPES",
    "InspectorFieldSpec",
    "specs_for_object_type",
]
