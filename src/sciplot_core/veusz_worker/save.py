"""Create a Veusz document from one materialized specification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_spec(document_path: Path, spec_path: Path) -> dict[str, Any]:
    """Create a VSZ from an already-materialized SciPlot Veusz spec."""

    from sciplot_core.studio_core.veusz_save import save_veusz_document_from_spec

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"Expected JSON object: {spec_path}")
    resolved_document = document_path.expanduser().resolve()
    save_veusz_document_from_spec(
        resolved_document,
        spec,
        spec_path=spec_path.expanduser().resolve(),
    )
    return {
        "kind": "sciplot_veusz_save_spec",
        "document": str(resolved_document),
        "exists": resolved_document.exists(),
    }
