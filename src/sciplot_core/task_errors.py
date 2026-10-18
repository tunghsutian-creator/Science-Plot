"""Pure task boundary errors shared by contracts and flow adapters."""
from typing import Any


class TaskControlError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.repair: dict[str, Any] | None = None
        self.issues: list[dict[str, Any]] | None = None
