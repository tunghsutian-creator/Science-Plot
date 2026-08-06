"""Validate the public render request and dispatch to Veusz."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.style_contract import validate_veusz_template_id
from sciplot_core.terminal_source_binding import (
    MaterializedTerminalSourceBinding,
)

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
    _terminal_source_binding: MaterializedTerminalSourceBinding | None = None,
) -> dict[str, Any]:
    reserved = {"_terminal_source_binding", "_terminal_source_prepared"}
    if isinstance(request_context, dict) and reserved.intersection(request_context):
        raise ValueError(
            "Internal terminal-source authority cannot appear in request context."
        )
    if _terminal_source_binding is not None and not isinstance(
        _terminal_source_binding, MaterializedTerminalSourceBinding
    ):
        raise TypeError("_terminal_source_binding must be a typed binding.")
    if _terminal_source_binding is not None and split_policy is not None:
        raise ValueError("A materialized terminal source cannot be auto-split.")
    template = validate_veusz_template_id(template)
    binding_option = (
        {"_terminal_source_binding": _terminal_source_binding}
        if _terminal_source_binding is not None
        else {}
    )
    return _render_to_dir_veusz(
        input_path,
        template=template,
        output_dir=output_dir,
        sheet=sheet,
        options=options,
        export_formats=export_formats,
        split_policy=split_policy,
        request_context=request_context,
        **binding_option,
    )
