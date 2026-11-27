"""Retain the managed-output rollback contract inside a private project image."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.project_store.io import sha
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


def archive_failed_delivery(
    candidate: StudioPreparationCandidate, logical: str, delivery: Path,
    failed: Path, record: dict[str, Any],
) -> set[str]:
    """Keep the failed producer's files, not the resource view or its old files."""
    prefix = logical + "/"
    before = {name.removeprefix(prefix): entry for name, entry in candidate.snapshot["files"].items()
              if name.startswith(prefix)}
    produced = {row["path"] for key in ("data_csvs", "figures", "project_documents")
                for row in record.get(key, []) if isinstance(row, dict) and isinstance(row.get("path"), str)}
    produced.update(record[key] for key in ("identity", "open_in_veusz", "open_in_sciplot")
                    if isinstance(record.get(key), str))

    current = _files(delivery)
    for relative, captured in current.items():
        source = delivery / relative
        if str(source) in produced:
            target = failed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(captured.data)
            target.chmod(captured.mode)
        if relative not in before:
            source.unlink()

    # CandidateResources bound this directory's inode before execution;
    # restore its preimage memberwise instead of moving or replacing the root.
    for relative, entry in before.items():
        version = current.get(relative)
        if version is None or sha(version.data) != entry["sha256"] or version.mode != entry["mode"]:
            restored = delivery / relative
            restored.parent.mkdir(parents=True, exist_ok=True)
            restored.write_bytes(candidate.store.read_bytes(prefix + relative, generation=candidate.snapshot["generation"]))
            restored.chmod(entry["mode"])
    return {str(delivery / relative) for relative in before} - produced
