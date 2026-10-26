"""Snapshot the exact document argument, separately from scientific sources."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_store.native_artifacts import (
    NativeArtifactInput, native_artifact_binding, native_artifact_runtime, resolve_native_artifact,
)
from sciplot_core.project_store.source_resolver import ProjectSourceResolver
from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver
from sciplot_core.project_store.locators import logical_for_literal, original_for_logical
from .file_snapshots import _physical_file_snapshot, _require_snapshot_identity


def native_document_snapshot(path: Path, *, label: str, expected_sha256: str | None = None) -> dict[str, Any]:
    actual = resolve_native_artifact(path, role="document", expected_sha256=expected_sha256)
    resolver = selected_source_resolver()
    literal = str(path.expanduser().absolute())
    if isinstance(resolver, ProjectCandidateResolver):
        literal = resolver.literal_path(actual)
    elif isinstance(resolver, ProjectSourceResolver):
        logical = logical_for_literal(resolver.snapshot, literal)
        if logical is None and (actual.is_relative_to(resolver.store.root)
                or any(actual.is_relative_to(root) for root in resolver.store.locations.values())):
            member = resolver.store.logical_path(actual)
            logical = member if member in resolver.snapshot["files"] else None
        if logical is not None:
            literal = original_for_logical(resolver.snapshot, logical)
    return {**_physical_file_snapshot(actual, literal=Path(literal),
        label=label, expected_sha256=expected_sha256), "native_argument": str(path)}


def assert_native_document_current(snapshot: dict[str, Any], *, label: str) -> None:
    current = native_document_snapshot(Path(snapshot.get("native_argument", snapshot["path"])),
        label=label, expected_sha256=snapshot["sha256"])
    _require_snapshot_identity(snapshot, current, label=label)


@contextmanager
def observed_native_document(argv: list[str], path: Path, *, expected_sha256: str | None = None) -> Iterator[None]:
    """Trusted native composition freezes one argument; no source grant changes."""
    resolver = selected_source_resolver()
    if not isinstance(resolver, ProjectSourceResolver):
        yield
        return
    if native_artifact_binding(argv, resolver) is not None:
        snapshot = native_document_snapshot(path, label="Observed native document", expected_sha256=expected_sha256)
        yield
        assert_native_document_current(snapshot, label="Observed native document")
        return
    snapshot = _physical_file_snapshot(path, literal=path.expanduser().absolute(),
        label="Observed native document", expected_sha256=expected_sha256)
    item = NativeArtifactInput("document", path, snapshot["sha256"], snapshot["identity"]["mode"] & 0o777)
    with native_artifact_runtime(argv, inputs=[item]):
        yield
        assert_native_document_current(snapshot, label="Observed native document")
