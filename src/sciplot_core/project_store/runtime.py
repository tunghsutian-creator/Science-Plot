"""Bind a trusted selected project generation to the pure scientific IO port."""
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from sciplot_core.foundation.source_locations import (
    literal_source_path, resolve_source_path, selected_source_resolver, source_location_scope,
)
from .repository import FileProjectStore
from .incoming_sources import SourceExpectation, SourceReadMode, require_unambiguous_scope, source_expectation_scope
from .source_resolver import ProjectSourceResolver as ProjectSourceResolver
from .sealed_source_trees import SealedSourceTree


@contextmanager
def project_runtime(store: FileProjectStore, generation: str | None = None) -> Iterator[ProjectSourceResolver]:
    resolver = ProjectSourceResolver(store, generation)
    with source_location_scope(resolver):
        yield resolver


@contextmanager
def _source_runtime(store: FileProjectStore, sources: Sequence[SourceExpectation], mode: SourceReadMode,
                    generation: str | None, trees: Sequence[SealedSourceTree] = ()) -> Iterator[ProjectSourceResolver]:
    require_unambiguous_scope()
    resolver = ProjectSourceResolver(store, generation)
    with source_expectation_scope(resolver.snapshot, mode, sources, trees=trees, store=store), source_location_scope(resolver):
        yield resolver


def incoming_source_runtime(store: FileProjectStore, sources: Sequence[SourceExpectation], *,
                            generation: str | None = None) -> AbstractContextManager[ProjectSourceResolver]:
    """Trusted host's explicit incoming version; no stored source version changes."""
    return _source_runtime(store, sources, "incoming", generation)


def sealed_source_runtime(store: FileProjectStore, sources: Sequence[SourceExpectation], *,
                          generation: str | None = None,
                          trees: Sequence[SealedSourceTree] = ()) -> AbstractContextManager[ProjectSourceResolver]:
    """Read one reviewed baseline version without reconnecting its live literal."""
    return _source_runtime(store, sources, "sealed", generation, trees)


# Host adapters use the same port as pure source consumers.
resolve_runtime_path = resolve_source_path
literal_runtime_path = literal_source_path


def projected_runtime_directory(original: str | Path) -> Path:
    """Observe visible delivery bytes through an existing selected host cap.

    This neither admits output nor grants an executor access. Private candidates
    and immutable source-directory caches are not visible delivery evidence.
    """
    from .candidate_runtime import ProjectCandidateResolver
    from .errors import ProjectStoreError
    from .physical_projection import projected_directory

    selected = selected_source_resolver()
    if isinstance(selected, ProjectCandidateResolver):
        raise ProjectStoreError("A private candidate cannot certify the current visible delivery.")
    if isinstance(selected, ProjectSourceResolver):
        return projected_directory(selected.store, original, generation=selected.generation)
    return Path(original)


def selected_project_store() -> FileProjectStore | None:
    """Return only the currently host-bound concrete store, preserving its caps."""
    selected = selected_source_resolver()
    return selected.store if isinstance(selected, ProjectSourceResolver) else None


@contextmanager
def project_candidate_runtime(store: FileProjectStore, candidate_root: Path, *,
                              generation: str | None = None,
                              resources_root: Path | None = None) -> Iterator[ProjectSourceResolver]:
    """Bind a complete private clone without creating a second persistent owner."""
    from .candidate_runtime import ProjectCandidateResolver

    resolver = ProjectCandidateResolver(store, candidate_root, generation, resources_root=resources_root)
    with source_location_scope(resolver):
        yield resolver


def logical_runtime_resource(original: str | Path, *, private_only: bool = False) -> str | None:
    """Return the selected candidate's admitted logical key, including resources."""
    from .candidate_runtime import ProjectCandidateResolver

    selected = selected_source_resolver()
    return selected.logical_resource(original, private_only=private_only) if isinstance(selected, ProjectCandidateResolver) else None


def resolve_runtime_output_path(original: str | Path) -> Path:
    """Only command-declared output positions may create private candidate files."""
    from .candidate_runtime import ProjectCandidateResolver

    selected = selected_source_resolver()
    return selected.output_path(original) if isinstance(selected, ProjectCandidateResolver) else Path(original)
