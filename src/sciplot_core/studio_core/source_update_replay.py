"""Recreate a disposable view of a sealed source preview without preparing again."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate


@contextmanager
def frozen_source_candidate(store: FileProjectStore, snapshot: dict[str, Any], record: dict[str, Any]) -> Iterator[Path]:
    with studio_preparation_candidate(store, snapshot=snapshot) as candidate:
        for name, entry in record["draft"]["writes"].items():
            if name.startswith("@"):
                continue
            if entry is None:
                candidate.remove_member(name)
            else:
                path = Path(record["staged_paths"][name])
                data = path.read_bytes()
                if len(data) != entry["size"] or file_sha256(path) != entry["sha256"]:
                    raise ValueError("The sealed source candidate changed before its preview was reconstructed")
                candidate.write_member(name, data, mode=entry["mode"])
        yield candidate.project_dir
