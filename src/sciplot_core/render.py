from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from sciplot_core._bootstrap import ensure_legacy_core

ensure_legacy_core()

from src.rendering.recommendation import inspect_input_file  # noqa: E402
from src.rendering.render_service import (  # noqa: E402
    build_rendered_plots,
    close_rendered_plots,
    export_rendered_plots,
)


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def inspect_payload(input_path: Path, *, sheet: str | int = 0) -> dict[str, Any]:
    return json_safe(inspect_input_file(input_path, sheet))


def render_to_dir(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = dict(options or {})
    rendered = build_rendered_plots(template, input_path, sheet, **options)
    try:
        outputs = export_rendered_plots(rendered, output_dir, close=False)
        return {
            "template": template,
            "input": str(input_path),
            "sheet": sheet,
            "outputs": [str(path) for path in outputs],
            "qa_reports": [json_safe(plot.qa_report) for plot in rendered],
        }
    finally:
        close_rendered_plots(rendered)


__all__ = ["inspect_payload", "json_safe", "render_to_dir"]
