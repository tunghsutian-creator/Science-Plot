"""Public rendering API and first-party compatibility facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_values import json_safe as json_safe
from sciplot_core.source_inspection import (
    inspect_input_file as inspect_input_file,
)
from sciplot_core.semantic import classify_source as classify_source
from sciplot_core.render.inspection import (  # noqa: F401
    _GENERIC_PRESENTATION_WARNING_MARKERS,
    _GENERIC_DATA_RISK_WARNING_MARKERS,
    _GENERIC_PRESENTATION_ONLY_MISSING_PHRASES,
    _material_rule_recommendation,
    _generic_warning_is_superseded_by_ready_rule,
    _resolve_ready_rule_inspection_warnings,
    _semantic_only_inspection_payload,
    inspect_payload as _inspect_payload,
)
from sciplot_core.render.formats import (  # noqa: F401
    _EXPORT_FORMATS,
    DEFAULT_EXPORT_FORMATS,
    DEFAULT_RENDER_ENGINE,
    _normalize_export_formats,
    _export_path,
    _series_labels_for_split,
)
from sciplot_core.render.worker_runtime import (  # noqa: F401
    _veusz_worker_env,
    _read_json_if_exists,
    _terminal_transform_steps,
    _extend_unique_transform_steps,
)
from sciplot_core.render.target_paths import (  # noqa: F401
    _veusz_target_base,
    _render_studio_exports,
)
from sciplot_core.render.layout_report import (  # noqa: F401
    _veusz_layout_report,
)
from sciplot_core.render.export_files import (  # noqa: F401
    _copy_veusz_exports,
    _validate_export_records,
    _remove_stale_render_exports,
    _cleanup_worker_exports,
)
from sciplot_core.render.panel_render import (  # noqa: F401
    _render_veusz_panel,
    _render_to_dir_veusz,
)
from sciplot_core.render.public_api import (  # noqa: F401
    render_to_dir,
)


def inspect_payload(
    input_path: Path,
    *,
    sheet: str | int = 0,
) -> dict[str, Any]:
    """Preserve the legacy injectable inspection seam over the split implementation."""

    return _inspect_payload(
        input_path,
        sheet=sheet,
        inspect_source=inspect_input_file,
        classify=classify_source,
    )


__all__ = [
    "DEFAULT_EXPORT_FORMATS",
    "DEFAULT_RENDER_ENGINE",
    "inspect_payload",
    "json_safe",
    "render_to_dir",
]
