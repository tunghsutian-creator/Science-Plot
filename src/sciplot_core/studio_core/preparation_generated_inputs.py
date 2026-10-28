"""One invocation-local candidate port for successful private input producers."""

from __future__ import annotations

from collections.abc import Iterable
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Protocol

from sciplot_core.project_commands import PreparedFile
from sciplot_core.project_commands.resources import resource_key
from sciplot_core.project_store import ProjectConflict


class GeneratedInputCandidate(Protocol):
    project_dir: Path
    snapshot: dict[str, Any]
    generated_inputs: dict[str, PreparedFile]

    def read_member(self, relative: str) -> PreparedFile: ...


_ACTIVE: ContextVar[GeneratedInputCandidate | None] = ContextVar("studio_preparation_candidate", default=None)


def record_generated_preparation_inputs(project: Path, sources: Iterable[Path]) -> None:
    """Freeze the successful producer's exact new members in this invocation."""
    candidate = _ACTIVE.get()
    if candidate is None:
        return  # Pure task materializers do not acquire active publication rights.
    if project.expanduser().resolve() != candidate.project_dir:
        raise ProjectConflict("A generated preparation input cannot borrow another candidate context.")
    captured: dict[str, PreparedFile] = {}
    for source in sources:
        if not source.is_absolute() or not source.is_relative_to(candidate.project_dir):
            raise ProjectConflict("A generated preparation input must belong to its private candidate.")
        relative = source.relative_to(candidate.project_dir).as_posix()
        resource_key(relative)
        if (relative.split("/", 1)[0] in {"raw", "source", ".sciplot_store"}
                or relative in candidate.snapshot["files"]
                or relative in candidate.snapshot.get("input_resources", [])
                or relative in candidate.snapshot.get("history_resources", [])):
            raise ProjectConflict("A generated preparation input cannot replace an admitted member.")
        value = candidate.read_member(relative)
        previous = captured.get(relative, candidate.generated_inputs.get(relative))
        if previous is not None and previous != value:
            raise ProjectConflict("A generated preparation input changed after its producer completed.")
        captured[relative] = value
    candidate.generated_inputs.update(captured)
