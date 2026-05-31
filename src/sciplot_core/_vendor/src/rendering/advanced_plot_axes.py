from __future__ import annotations

from typing import cast

from matplotlib.axes import Axes

from src.rendering.models import RenderedPlot

PRIMARY_AXIS_GID = "sciplot-primary-axis"
EXTRA_X_AXIS_GID = "sciplot-extra-x-axis"
EXTRA_Y_AXIS_GID = "sciplot-extra-y-axis"


def mark_primary_axis(ax: Axes) -> None:
    ax.set_gid(PRIMARY_AXIS_GID)


def mark_extra_axis(ax: Axes, *, axis_name: str) -> None:
    if axis_name == "x":
        ax.set_gid(EXTRA_X_AXIS_GID)
    else:
        ax.set_gid(EXTRA_Y_AXIS_GID)


def primary_axis(rendered: RenderedPlot) -> Axes | None:
    if not rendered.figure.axes:
        return None
    axis = rendered.figure.axes[0]
    mark_primary_axis(axis)
    return axis


def secondary_y_axis(rendered: RenderedPlot) -> Axes | None:
    for axis in rendered.figure.axes[1:]:
        if axis.get_gid() == EXTRA_Y_AXIS_GID:
            return cast(Axes, axis)
    primary = primary_axis(rendered)
    if primary is None:
        return None
    for axis in primary.child_axes:
        if axis.get_gid() == EXTRA_Y_AXIS_GID:
            return cast(Axes, axis)
    return None


__all__ = [
    "EXTRA_X_AXIS_GID",
    "EXTRA_Y_AXIS_GID",
    "PRIMARY_AXIS_GID",
    "mark_extra_axis",
    "mark_primary_axis",
    "primary_axis",
    "secondary_y_axis",
]
