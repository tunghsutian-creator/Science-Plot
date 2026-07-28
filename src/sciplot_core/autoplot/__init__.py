"""Fully automated project lifecycle API."""

from __future__ import annotations

from sciplot_core.autoplot.contracts import (  # noqa: F401
    AUTOPLOT_MODEL_KIND,
    AUTOPLOT_MODEL_VERSION,
    _VALID_STATES,
)
from sciplot_core.autoplot.publish_integrity import (  # noqa: F401
    _manifest_publish_integrity,
)
from typing import Any

from sciplot_core.autoplot.summary import (
    build_autoplot_summary as _build_autoplot_summary_impl,
)
from sciplot_core.autoplot.run import (  # noqa: F401
    run_autoplot,
)
from sciplot_core.readiness import validated_envelope_evaluation_ready


def build_autoplot_summary(one_step_result: dict[str, Any]) -> dict[str, Any]:
    """Build a summary while preserving the historical module patch seam."""

    return _build_autoplot_summary_impl(
        one_step_result,
        _validated_envelope_ready=validated_envelope_evaluation_ready,
    )


__all__ = [
    "AUTOPLOT_MODEL_KIND",
    "AUTOPLOT_MODEL_VERSION",
    "build_autoplot_summary",
    "run_autoplot",
]
