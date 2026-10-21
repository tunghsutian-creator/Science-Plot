"""Audit represented categorical presentation before touching native exports."""
import json
from pathlib import Path

from sciplot_core.studio_core.categorical_display import KEY
from sciplot_core.studio_core.document_edit_state import audit_edited_document


def require_categorical_display_current(document: Path, spec: Path) -> None:
    if not spec.is_file():
        return
    payload = json.loads(spec.read_bytes())
    if isinstance(payload, dict) and KEY in payload:
        audit_edited_document(document, spec)
