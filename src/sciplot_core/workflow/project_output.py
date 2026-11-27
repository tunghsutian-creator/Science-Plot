"""Retain the managed-output rollback contract inside a private project image."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import shutil
from typing import Any

from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate
from sciplot_core.studio_core.preparation_candidate_files import _files
from sciplot_core.workflow.request_io import _managed_output_transaction


@contextmanager
def private_run_output(candidate: StudioPreparationCandidate, logical: str) -> Iterator[Path]:
    directory = candidate.resource_path(logical + "/manifest.json").parent
    previous = any(name.startswith(logical + "/") for name in candidate.snapshot["files"])
    if previous:
        # Primary members were copied by the candidate. External members stay
        # untouched; the same managed-name replacement is captured below.
        with _managed_output_transaction(directory, private=True):
            yield directory
    else:
        directory.mkdir(parents=True, exist_ok=True)
        yield directory


def install_private_delivery(stage: Path, target: Path) -> None:
    """Replace only the contents of the host-bound private delivery view."""
    target.mkdir(parents=True, exist_ok=True)
    for obsolete in target.iterdir():
        if obsolete.is_dir() and not obsolete.is_symlink():
            shutil.rmtree(obsolete)
        else:
            obsolete.unlink()
    for member in stage.iterdir():
        member.replace(target / member.name)


def archive_failed_delivery(stage: Path, failed: Path, record: dict[str, Any]) -> None:
    """Retain named diagnostics; the earlier bound delivery was never touched."""
    produced = {row["path"] for key in ("data_csvs", "figures", "project_documents")
                for row in record.get(key, []) if isinstance(row, dict) and isinstance(row.get("path"), str)}
    produced.update(record[key] for key in ("identity", "open_in_veusz", "open_in_sciplot")
                    if isinstance(record.get(key), str))
    for relative in _files(stage):
        source = stage / relative
        if str(source) in produced:
            target = failed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
