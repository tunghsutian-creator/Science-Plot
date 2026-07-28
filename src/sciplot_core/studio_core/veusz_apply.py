"""Apply a renderer-neutral plot specification to a live Veusz document."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_render.models import CATEGORICAL_SERIES_KINDS

from sciplot_core.studio_core.veusz_bar_error import add_veusz_error_bars
from sciplot_core.studio_core.veusz_boxplots import add_veusz_native_boxplots
from sciplot_core.studio_core.veusz_canvas_finish import (
    add_veusz_categorical_axis_provider,
    finish_veusz_export_canvas,
)
from sciplot_core.studio_core.veusz_data_import import import_veusz_spec_data
from sciplot_core.studio_core.veusz_graph_setup import (
    add_veusz_graph_annotations,
    create_veusz_page_and_graph,
)
from sciplot_core.studio_core.veusz_guides import _add_veusz_reference_guides
from sciplot_core.studio_core.veusz_primitives import _add_veusz_xy_series
from sciplot_core.studio_core.veusz_stacked_bars import add_veusz_stacked_bars


def _apply_veusz_spec(interface: Any, spec: dict[str, Any]) -> None:
    """Create datasets and graph widgets in their required paint order."""

    if isinstance(spec.get("performance_comparison"), dict):
        from sciplot_core.performance_veusz import apply_performance_veusz_spec

        apply_performance_veusz_spec(interface, spec)
        return

    style = spec["style"]
    axes = spec["axes"]
    size_mm = spec["size_mm"]
    categorical = (
        spec.get("categorical") if isinstance(spec.get("categorical"), dict) else None
    )
    series = spec["series"]
    import_veusz_spec_data(
        interface,
        series=series,
        axes=axes,
        categorical=categorical,
    )
    create_veusz_page_and_graph(
        interface,
        style=style,
        axes=axes,
        size_mm=size_mm,
    )
    add_veusz_graph_annotations(
        interface,
        spec=spec,
        categorical=categorical,
        style=style,
    )

    # Categorical replicate markers are added before their filled summaries so
    # reverse Veusz child painting keeps them as the topmost data layer.
    for item in series:
        if item.get("presentation_kind") in CATEGORICAL_SERIES_KINDS:
            _add_veusz_xy_series(interface, item, style)
    add_veusz_native_boxplots(interface, categorical)
    if not add_veusz_error_bars(
        interface,
        spec=spec,
        categorical=categorical,
    ):
        add_veusz_stacked_bars(interface, categorical)

    for item in series:
        if item.get("presentation_kind") in CATEGORICAL_SERIES_KINDS:
            continue
        _add_veusz_xy_series(interface, item, style)
    add_veusz_categorical_axis_provider(interface, categorical)

    # Add guides after data plotters so reverse painting puts them behind data.
    _add_veusz_reference_guides(interface, spec)
    finish_veusz_export_canvas(interface)
