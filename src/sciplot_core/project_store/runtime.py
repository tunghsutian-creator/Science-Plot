"""Bind a trusted selected project generation to the pure scientific IO port."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sciplot_core.foundation.source_locations import (
    literal_source_path, resolve_source_path, selected_source_resolver, source_location_scope,
)
from .repository import FileProjectStore
from .source_resolver import ProjectSourceResolver as ProjectSourceResolver


@contextmanager
def project_runtime(store: FileProjectStore, generation: str | None = None) -> Iterator[ProjectSourceResolver]:
    resolver = ProjectSourceResolver(store, generation)
    with source_location_scope(resolver):
        yield resolver


# Host adapters use the same port as pure source consumers.
resolve_runtime_path = resolve_source_path
literal_runtime_path = literal_source_path


def selected_project_store() -> FileProjectStore | None:
    """Return only the currently host-bound concrete store, preserving its caps."""
    selected = selected_source_resolver()
    return selected.store if isinstance(selected, ProjectSourceResolver) else None


@contextmanager
def project_candidate_runtime(store: FileProjectStore, candidate_root: Path, *,
                              generation: str | None = None) -> Iterator[ProjectSourceResolver]:
    """Bind a complete private clone without creating a second persistent owner."""
    from .candidate_runtime import ProjectCandidateResolver

    resolver = ProjectCandidateResolver(store, candidate_root, generation)
    with source_location_scope(resolver):
        yield resolver
