"""Retain the managed-output rollback contract inside a private project image."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sciplot_core.project_commands import PreparedFile
from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate
from sciplot_core.workflow.request_io import (
    _MANAGED_OUTPUT_DIRECTORIES, _MANAGED_OUTPUT_FILES, _managed_output_transaction,
)


@contextmanager
def private_run_output(candidate: StudioPreparationCandidate, logical: str) -> Iterator[Path]:
    directory = candidate.resource_path(logical + "/manifest.json").parent
    previous = any(name.startswith(logical + "/") for name in candidate.snapshot["files"])
    if previous:
        # Primary members were copied by the candidate. External members stay
        # untouched; the same managed-name replacement is captured below.
        with _managed_output_transaction(directory):
            yield directory
    else:
        directory.mkdir(parents=True, exist_ok=True)
        yield directory


def output_replacements(candidate: StudioPreparationCandidate, logical: str,
                        writes: dict[str, bytes | PreparedFile | None]) -> dict[str, bytes | PreparedFile | None]:
    """Delete only the prior managed run members that this exact output replaces."""
    if not logical.startswith("@"):
        return writes  # Primary deletions are already in the complete capture.
    prefix = logical + "/"
    retired: dict[str, None] = {}
    for name in candidate.snapshot["files"]:
        if not name.startswith(prefix):
            continue
        relative = name[len(prefix):]
        if relative in _MANAGED_OUTPUT_FILES or relative.split("/", 1)[0] in _MANAGED_OUTPUT_DIRECTORIES:
            retired[name] = None
    return {**retired, **writes}
