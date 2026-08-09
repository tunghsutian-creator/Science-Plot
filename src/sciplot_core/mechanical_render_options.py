"""Project primary figure style onto fixed mechanical summary tasks."""

from __future__ import annotations

from typing import Any, Final

from sciplot_core.mechanical_figure_contract import MechanicalFigureTaskContract
from sciplot_core.policy import CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS


SHARED_FIGURE_STYLE_KEYS: Final = frozenset(
    {
        "size",
        "visual_theme_id",
        "style_preset",
        "palette_preset",
        "marker_alpha",
    }
)


def shared_figure_style_options(options: dict[str, Any]) -> dict[str, Any]:
    """Return only options that may be shared by independent task types."""

    return {
        key: value for key, value in options.items() if key in SHARED_FIGURE_STYLE_KEYS
    }


def mechanical_summary_render_options(
    task: MechanicalFigureTaskContract,
    *,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Resolve one median/IQR box-strip task without curve-option leakage."""

    return {
        **CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
        **shared_figure_style_options(options),
        "legend_position": "none",
        "series_label_mode": "none",
        "x_label_override": task.x_label,
        "y_label_override": task.y_label,
        "summary_statistic": "median_iqr",
        "x_metric": task.x_metric,
        "y_metric": task.y_metric,
    }


def mechanical_task_explicit_option_keys(
    request: dict[str, Any],
    *,
    render_options: dict[str, Any],
    summary: bool,
) -> tuple[str, ...]:
    """Project explicit provenance only onto options a child task retained."""

    value = request.get("explicit_render_option_keys")
    requested = value if isinstance(value, list | tuple | set) else ()
    allowed = SHARED_FIGURE_STYLE_KEYS if summary else frozenset(render_options)
    return tuple(
        sorted(
            {
                str(key)
                for key in requested
                if str(key) in allowed and str(key) in render_options
            }
        )
    )


__all__ = [
    "SHARED_FIGURE_STYLE_KEYS",
    "mechanical_summary_render_options",
    "mechanical_task_explicit_option_keys",
    "shared_figure_style_options",
]
