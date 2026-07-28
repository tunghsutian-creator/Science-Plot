"""Paint visible pages and capture physical widget bounds."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_audit.measurements import _bounds_mm, _rounded


def collect_page_geometry(
    doc: Any, paint_helper_type: Any
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    state_by_path: dict[str, dict[str, Any]] = {}

    pages: list[dict[str, Any]] = []

    helpers_by_page: dict[int, Any] = {}

    for page_index in doc.getVisiblePages():
        size = doc.pageSize(page_index, dpi=(72.0, 72.0), integer=False)
        helper = paint_helper_type(doc, size, dpi=(72.0, 72.0))
        doc.paintTo(helper, page_index)
        helpers_by_page[page_index] = helper
        page_widget = doc.getPage(page_index)
        page_path = str(page_widget.path)
        for (widget, layer), state in helper.states.items():
            if layer != 0:
                continue
            state_by_path[str(widget.path)] = {
                "page": page_index + 1,
                "bounds_mm": _bounds_mm(state.bounds),
                "helper": helper,
            }
        pages.append(
            {
                "page": page_index + 1,
                "path": page_path,
                "size_mm": [
                    _rounded(float(size[0]) / 72.0 * 25.4),
                    _rounded(float(size[1]) / 72.0 * 25.4),
                ],
                "bounds_mm": [
                    0.0,
                    0.0,
                    _rounded(float(size[0]) / 72.0 * 25.4),
                    _rounded(float(size[1]) / 72.0 * 25.4),
                ],
            }
        )
    return state_by_path, pages
