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
from .source_inspection import SourceFileObservation


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
                            generation: str | None = None,
                            trees: Sequence[SealedSourceTree] = ()) -> AbstractContextManager[ProjectSourceResolver]:
    """Trusted host's explicit incoming version; no stored source version changes."""
    return _source_runtime(store, sources, "incoming", generation, trees)


def sealed_source_runtime(store: FileProjectStore, sources: Sequence[SourceExpectation], *,
                          generation: str | None = None,
                          trees: Sequence[SealedSourceTree] = ()) -> AbstractContextManager[ProjectSourceResolver]:
    """Read one reviewed baseline version without reconnecting its live literal."""
    return _source_runtime(store, sources, "sealed", generation, trees)


# Host adapters use the same port as pure source consumers.
resolve_runtime_path = resolve_source_path
literal_runtime_path = literal_source_path


def literal_runtime_project_root(original: str | Path) -> str:
    """Locate an existing host resource root, without asserting its contents."""
    from .candidate_runtime import ProjectCandidateResolver
    from .errors import ProjectStoreError
    from .physical_projection import literal_project_root

    selected = selected_source_resolver()
    if isinstance(selected, ProjectCandidateResolver):
        raise ProjectStoreError("A private candidate cannot identify the current host project root.")
    if isinstance(selected, ProjectSourceResolver):
        return literal_project_root(selected.store, original, generation=selected.generation)
    return literal_source_path(Path(original))


def projected_runtime_project_root(original: str | Path) -> Path:
    """Select an existing whole host root without claiming current member bytes."""
    from .candidate_runtime import ProjectCandidateResolver
    from .errors import ProjectStoreError
    from .physical_projection import projected_project_root

    selected = selected_source_resolver()
    if isinstance(selected, ProjectCandidateResolver):
        raise ProjectStoreError("A private candidate cannot identify the current host project root.")
    if isinstance(selected, ProjectSourceResolver):
        return projected_project_root(selected.store, original, generation=selected.generation)
    return Path(original)


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


def projected_runtime_artifact(original: str | Path) -> Path:
    """Keep current registered artifacts physical and private-stage IO unchanged."""
    from .candidate_runtime import ProjectCandidateResolver
    from .physical_projection import projected_artifact

    selected = selected_source_resolver()
    if isinstance(selected, ProjectCandidateResolver):
        return resolve_source_path(original)
    if isinstance(selected, ProjectSourceResolver):
        physical = projected_artifact(selected.store, original, generation=selected.generation)
        if physical is not None:
            return physical
    # This is the original port for nonregistered private stage paths, not a
    # retry after failed ownership, member, hash, mode or source-cache checks.
    return resolve_source_path(original)


def inspect_runtime_source_file(original: str | Path, *, expected_sha256: str | None = None,
                                source_id: str | None = None) -> SourceFileObservation:
    """Read a current physical version or an explicitly selected sealed binding."""
    from .candidate_runtime import ProjectCandidateResolver
    from .source_inspection import inspect_file, inspect_invocation_file, physical_file

    selected = selected_source_resolver()
    if isinstance(selected, ProjectSourceResolver):
        source_id = selected.source_identity(original, expected_sha256, source_id)
        explicit = inspect_invocation_file(selected.store, original, expected_sha256=expected_sha256,
            source_id=source_id, generation=selected.inspection_generation)
        if explicit is not None:
            return explicit
    if isinstance(selected, ProjectCandidateResolver) and selected.logical_resource(original) is not None:
        return physical_file(selected.resolve_path(original, expected_sha256=expected_sha256,
            source_id=source_id), expected_sha256)
    if isinstance(selected, ProjectSourceResolver):
        return inspect_file(selected.store, original, expected_sha256=expected_sha256,
                            source_id=source_id, generation=selected.inspection_generation)
    return physical_file(resolve_source_path(original, expected_sha256=expected_sha256,
                         source_id=source_id), expected_sha256)


def inspect_runtime_source_tree(original: str | Path, *, allowed: set[str] | None = None) -> str:
    """Observe a complete current namespace without resolving a cached view."""
    from .candidate_runtime import ProjectCandidateResolver
    from .source_inspection import inspect_tree, inspect_invocation_file, inspect_invocation_tree
    from .source_tree_io import observe
    from .io import digest

    selected = selected_source_resolver()
    if isinstance(selected, ProjectSourceResolver):
        whole = inspect_invocation_tree(selected.store, original, generation=selected.inspection_generation, allowed=allowed)
        if whole is not None:
            return whole
        explicit = inspect_invocation_file(selected.store, original, generation=selected.inspection_generation, tree=True)
        if explicit is not None:
            return digest({"kind": "file", "content_sha256": explicit.sha256})
    if isinstance(selected, ProjectCandidateResolver) and selected.logical_resource(original) is not None:
        return observe(str(selected.resolve_path(original)), allowed=allowed)[0]
    if isinstance(selected, ProjectSourceResolver):
        return inspect_tree(selected.store, original, generation=selected.inspection_generation, allowed=allowed)
    return observe(str(resolve_source_path(original).expanduser().absolute()), allowed=allowed)[0]


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
