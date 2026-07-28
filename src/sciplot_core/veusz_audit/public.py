"""Audit a set of exact-current Veusz documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.veusz_audit.document import _audit_document


def audit_veusz_documents(paths: list[Path]) -> dict[str, Any]:
    """Load and audit exact VSZ documents through Veusz's own layout engine."""

    audits = [_audit_document(path) for path in paths]
    return {
        "kind": "sciplot_veusz_document_audit_set",
        "version": 1,
        "documents": audits,
        "coverage_complete": bool(audits)
        and all(bool(item["stroke_inventory"]["coverage_complete"]) for item in audits),
    }
