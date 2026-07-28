"""Exact-current Veusz audit API and compatibility facade."""

from sciplot_core.veusz_audit.colors import _group_color, _resolved_rgb  # noqa: F401
from sciplot_core.veusz_audit.document import _audit_document  # noqa: F401
from sciplot_core.veusz_audit.measurements import (  # noqa: F401
    _bounds_mm,
    _distance_pt,
    _distance_value_pt,
    _rounded,
    _setting_hidden,
)
from sciplot_core.veusz_audit.public import audit_veusz_documents
from sciplot_core.veusz_audit.strokes import _line_group_item  # noqa: F401
from sciplot_core.veusz_audit.widget_tree import (  # noqa: F401
    _iter_widgets,
    _owner_widget,
)

__all__ = ["audit_veusz_documents"]
