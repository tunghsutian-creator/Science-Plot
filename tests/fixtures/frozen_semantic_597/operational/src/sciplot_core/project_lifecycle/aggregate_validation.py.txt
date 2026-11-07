"""Validate a newly committed Managed aggregate without reading original tables.

Old heads stay readable under their historical seals. At the new persistence
boundary the existing pure compiler checks resolved dataset membership, column
identity, mapping references, units and complete represented presentation.
"""
from pathlib import Path
from typing import Any
from collections.abc import Callable


def validate_snapshot(root: Path, document: dict[str, Any], *, read_snapshot: Callable[[Path], dict[str, Any]]) -> None:
    if document.get("plot_type") != "ManagedPlot":
        return
    from .content_references import resolve_document_content
    from sciplot_core.plot_ir import compile_document

    expanded = resolve_document_content(root, document, read_snapshot=read_snapshot)
    compile_document(document, expanded["scientific"]["provenance"].get("datasets"))
