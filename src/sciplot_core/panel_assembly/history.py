"""In-memory content undo/redo with monotonic document revisions."""

from copy import deepcopy
from typing import Any

from .errors import AssemblyError
from .model import apply_operations, validate_document


class AssemblyHistory:
    def __init__(self, document: Any) -> None:
        self._document = validate_document(document)
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []

    @property
    def document(self) -> dict[str, Any]:
        return deepcopy(self._document)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def apply(self, operations: Any) -> dict[str, Any]:
        candidate = apply_operations(self._document, operations)
        self._undo.append(self._document)
        self._document = candidate
        self._redo.clear()
        return self.document

    def _restore(self, source: list[dict[str, Any]], target: list[dict[str, Any]]) -> dict[str, Any]:
        if not source:
            raise AssemblyError("assembly_history_empty", "No history entry is available.")
        restored = deepcopy(source[-1])
        restored["revision"] = self._document["revision"] + 1
        restored = validate_document(restored)
        target.append(self._document)
        source.pop()
        self._document = restored
        return self.document

    def undo(self) -> dict[str, Any]:
        return self._restore(self._undo, self._redo)

    def redo(self) -> dict[str, Any]:
        return self._restore(self._redo, self._undo)
