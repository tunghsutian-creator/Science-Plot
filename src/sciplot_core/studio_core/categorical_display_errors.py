"""One expected categorical native-display conflict across existing workers."""
import json

from sciplot_core.studio_render.models import StudioPreparationBlocked

CODE = "categorical_presentation_conflict"


class CategoricalPresentationConflict(StudioPreparationBlocked):
    def __init__(self, message: str) -> None:
        super().__init__(CODE, message)


def raise_categorical_worker_rejection(returncode: int, stderr: str) -> None:
    """Only the existing exact four-key domain envelope is an expected conflict."""
    try:
        failure = json.loads(stderr)
    except (ValueError, TypeError):
        return
    if (returncode == 1 and isinstance(failure, dict)
            and set(failure) == {"kind", "version", "reason_code", "message"}
            and failure["kind"] == "sciplot_worker_preparation_blocked"
            and type(failure["version"]) is int and failure["version"] == 1
            and failure["reason_code"] == CODE
            and isinstance(failure["message"], str) and failure["message"].strip()):
        raise CategoricalPresentationConflict(failure["message"])
