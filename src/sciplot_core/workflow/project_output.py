"""Retain the managed-output rollback contract inside a private project image."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate
from sciplot_core.workflow.request_io import _managed_output_transaction


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
