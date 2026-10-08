"""Short, structured errors from the renderer-independent document contract."""

from typing import Any, NoReturn


class DocumentError(ValueError):
    def __init__(self, reason_code: str, message: str, *,
                 issues: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.issues = issues or []
        self.repair: dict[str, Any] = {"action": "correct_patch", "issues": self.issues}


def fail(code: str, message: str, path: str, constraint: str, **details: Any) -> NoReturn:
    raise DocumentError(code, message, issues=[{"path": path, "constraint": constraint, **details}])
