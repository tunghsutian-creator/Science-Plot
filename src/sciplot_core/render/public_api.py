"""Validate the public render request and dispatch to Veusz."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.style_contract import validate_veusz_template_id

from sciplot_core.render.panel_render import (
    _render_to_dir_veusz,
)


def render_to_dir(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
    export_formats: list[str] | tuple[str, ...] | None = None,
    split_policy: dict[str, Any] | None = None,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    template = validate_veusz_template_id(template)
    return _render_to_dir_veusz(
        input_path,
        template=template,
        output_dir=output_dir,
        sheet=sheet,
        options=options,
        export_formats=export_formats,
        split_policy=split_policy,
        request_context=request_context,
    )
