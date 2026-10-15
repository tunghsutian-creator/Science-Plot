"""Public assembly document ports and session-bound persistence entry points."""

from pathlib import Path
from typing import Any

from .document import (
    _AssemblyDocument as _AssemblyDocument,
    apply_operations,
    new_document,
    operation_capabilities,
    resolve_document,
    validate_document,
)
from .storage import load, save

__all__ = ["apply_operations", "new_document", "operation_capabilities", "resolve_document",
           "validate_document", "load_document", "save_document"]


def load_document(path: str | Path) -> dict[str, Any]:
    return load(Path(path))


def save_document(document: Any, path: str | Path, expected_revision: int | None = None) -> Path:
    return save(validate_document(document), Path(path), expected_revision=expected_revision)
