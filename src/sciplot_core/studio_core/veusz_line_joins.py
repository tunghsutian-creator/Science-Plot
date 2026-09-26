"""Persist optional XY pen joins in SciPlot's native Veusz runtime."""

from __future__ import annotations

from typing import Any


def ensure_veusz_line_joins() -> None:
    """Add a native setting without changing existing documents' bevel joins.

    Only the QPen join changes; curve interpolation, coordinates, caps and
    widths remain upstream-owned. Saved round joins require this SciPlot
    runtime extension, installed before document construction and loading.
    """
    from veusz import qtall as qt, setting

    line_type = setting.XYPlotLine
    original_init = line_type.__init__
    if getattr(original_init, "_sciplot_line_joins", False):
        return
    original_pen = line_type.makeQPen

    def initialize(line: Any, *args: Any, **kwargs: Any) -> None:
        original_init(line, *args, **kwargs)
        line.add(setting.Choice(
            "joinStyle", ["bevel", "round"], "bevel",
            descr="Connection shape between line segments",
            usertext="Line join", formatting=True,
        ))

    def make_pen(line: Any, painter: Any) -> Any:
        pen = original_pen(line, painter)
        if line.joinStyle == "round":
            pen.setJoinStyle(qt.Qt.PenJoinStyle.RoundJoin)
        return pen

    initialize._sciplot_line_joins = True  # type: ignore[attr-defined]
    line_type.__init__ = initialize
    line_type.makeQPen = make_pen
