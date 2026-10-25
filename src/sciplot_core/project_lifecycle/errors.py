"""Small corrective replies; complete traces belong to durable local evidence."""

from typing import Any


class EngineError(ValueError):
    def __init__(self, code: str, message: str, *, action: str = "inspect_document",
                 **details: Any) -> None:
        super().__init__(message)
        self.reason_code = code
        self.issues: list[dict[str, Any]] = []
        self.repair = {"action": action, **details}
