"""Bounded assembly errors shared by document, source and export owners."""

from typing import Any


class AssemblyError(ValueError):
    def __init__(self, code: str, message: str, *, issues: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.reason_code = code
        self.issues = issues or []
