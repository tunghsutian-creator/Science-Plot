"""Explicit command refusal; an uncertain native outcome is never retried."""


class ProjectCommandError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ProjectCommandUnknown(ProjectCommandError):
    def __init__(self) -> None:
        super().__init__("project_command_outcome_unknown",
                         "This command already entered execution; inspect its saved outcome without reapplying it.")
