"""Declare smoke expectations and inspect exact-current document evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe


RUNTIME_SMOKE_VERSION = 25


EXPECTED_RULE_ID = "ftir_spectrum"


MANUAL_EDIT_MARKER = "# SciPlot runtime smoke manual-edit preservation probe"


EXPECTED_SCALAR_VISUAL_ATTACK_IDS = frozenset(
    {
        "axis_label_size_zero",
        "axis_line_width_zero",
        "axis_major_tick_length_zero",
        "axis_major_tick_width_zero",
        "axis_minor_tick_length_zero",
        "axis_minor_tick_width_zero",
        "axis_ticklabels_size_zero",
        "colorbar_background_deleted",
        "colorbar_background_fill_changed",
        "colorbar_background_geometry_changed",
        "colorbar_background_hidden",
        "colorbar_background_transparency_changed",
        "colorbar_border_hidden",
        "colorbar_border_transparent",
        "colorbar_border_width_zero",
        "colorbar_foreground_changed",
        "colorbar_label_hidden",
        "colorbar_label_size_zero",
        "colorbar_line_hidden",
        "colorbar_line_transparent",
        "colorbar_line_width_zero",
        "colorbar_major_tick_length_zero",
        "colorbar_major_tick_width_zero",
        "colorbar_major_ticks_hidden",
        "colorbar_minor_tick_length_zero",
        "colorbar_minor_tick_width_zero",
        "colorbar_minor_ticks_hidden",
        "colorbar_minor_ticks_transparent",
        "colorbar_ticklabels_hidden",
        "colorbar_ticklabels_size_zero",
        "colorbar_ticks_transparent",
        "colorbar_zero_width",
        "contour_lines_hidden",
        "image_transparency",
        "reference_guide_made_opaque",
        "reference_line_geometry_changed",
        "reference_line_hidden",
        "reference_line_style_changed",
        "reference_line_width_changed",
        "unmanaged_line_overlay",
        "unmanaged_opaque_overlay",
    }
)


def _check(
    check_id: str, label: str, passed: bool, *, detail: Any = None
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _inspect_veusz_document_state(document_path: Path) -> dict[str, Any]:
    """Reopen a VSZ in the isolated Veusz worker and return widget settings."""

    from sciplot_core.veusz_runtime import veusz_worker_environment

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sciplot_core.veusz_worker",
            "inspect-document-state",
            str(document_path.expanduser().resolve()),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
        env=veusz_worker_environment(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise ValueError(
            "Veusz attack materialization inspection failed: "
            f"{detail[-1] if detail else completed.returncode}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Veusz attack materialization inspection returned invalid JSON."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "sciplot_veusz_document_state"
        or payload.get("version") != 1
        or payload.get("status") != "passed"
        or not isinstance(payload.get("widgets"), dict)
    ):
        raise ValueError("Veusz attack materialization inspection did not pass.")
    return payload


def _delivery_artifact(delivery: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    artifacts = (
        delivery.get("artifacts") if isinstance(delivery.get("artifacts"), list) else []
    )
    for item in artifacts:
        if isinstance(item, dict) and item.get("id") == artifact_id:
            return item
    return {}
