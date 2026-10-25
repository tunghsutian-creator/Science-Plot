"""Frozen source admission and invocation-only new-creation read declarations."""
from collections.abc import Iterable
from contextlib import contextmanager
from collections.abc import Iterator
import hashlib
import os
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import PreparedSource
from sciplot_core.project_store.io import read_file
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import ProjectSourceResolver
from .errors import EngineError
from .repository import digest


def record_sources(logical: str, value: Any) -> list[dict[str, Any]]:
    """Only canonical record fields declare sources; arbitrary CAS metadata cannot."""
    if not isinstance(value, dict):
        return []
    relative = Path(logical)
    if "models" in relative.parts and value.get("kind") == "sciplot_document":
        return list(value["scientific"]["data_sources"])
    if ("revisions" in relative.parts or relative.name in {"transaction.json", "managed-creation.json", "creation.json"}):
        result = []
        for field in ("document", "before"):
            document = value.get(field)
            if isinstance(document, dict) and document.get("kind") == "sciplot_document":
                result.extend(document["scientific"]["data_sources"])
        return result
    return []


def capture_source(path: Path) -> tuple[bytes, int]:
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        data, mode = read_file(parent, path.name)
    finally:
        os.close(parent)
    return data, mode


def _read_source(path: Path, version: str) -> tuple[bytes, int]:
    data, mode = capture_source(path)
    if hashlib.sha256(data).hexdigest() != version:
        raise EngineError("semantic_attachment_source_unavailable", "Restore the exact sealed source version before attaching this project.",
                          source=str(path), version=version)
    return data, mode


def prepared_sources(store: FileProjectStore, sources: Iterable[dict[str, Any]], *,
                     force: frozenset[tuple[str, str]] = frozenset()) -> tuple[PreparedSource, ...]:
    snapshot = store.snapshot()
    collected: dict[tuple[str, str], set[str]] = {}
    for source in sources:
        aliases = collected.setdefault((source["path"], source["sha256"]), set())
        if isinstance(source.get("source_id"), str):
            aliases.add(source["source_id"])
    result = []
    for (literal, version), aliases in sorted(collected.items()):
        matches = [(identity, entry) for identity, versions in snapshot["sources"].items()
                   for sha, entry in versions.items() if sha == version and entry.get("locator") == literal]
        if len(matches) > 1:
            raise EngineError("semantic_attachment_source_ambiguous", "The exact source version has competing stable identities.")
        if matches:
            identity, entry = matches[0]
            known = set(entry.get("aliases", ())) | {identity}
            if aliases <= known and (literal, version) not in force:
                continue
            data, _view_mode = _read_source(store.resolve_source(identity, version), version)
            mode = entry["mode"]
            aliases.update(entry.get("aliases", ()))
        else:
            identities = {identity for identity, versions in snapshot["sources"].items()
                          if any(entry.get("locator") == literal for entry in versions.values())}
            if len(identities) > 1:
                raise EngineError("semantic_attachment_source_ambiguous", "The original source locator has competing stable identities.")
            identity = next(iter(identities)) if identities else digest([snapshot["project_id"], "source", literal])[:32]
            from sciplot_core.foundation.source_locations import selected_source_resolver

            resolver = selected_source_resolver()
            actual = resolver.resolve_path(literal, expected_sha256=version, source_id=next(iter(aliases), None)) if isinstance(resolver, AttachmentSourceResolver) else Path(literal)
            data, mode = _read_source(actual, version)
        result.append(PreparedSource(identity, literal, version, data, tuple(sorted(aliases)), mode))
    return tuple(result)


class AttachmentSourceResolver(ProjectSourceResolver):
    """A lease-local capability, advanced only after durable source publication."""
    def __init__(self, store: FileProjectStore, pending: Iterable[dict[str, Any]] = ()) -> None:
        super().__init__(store)
        self.pending = tuple(dict(source) for source in pending)

    def refresh(self) -> None:
        ProjectSourceResolver.__init__(self, self.store)
        self.pending = ()

    @contextmanager
    def declaration_scope(self, sources: Iterable[dict[str, Any]]) -> Iterator[None]:
        previous = self.pending
        self.pending = tuple(dict(source) for source in sources)
        try:
            yield
        finally:
            self.pending = previous

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path:
        matches = [item for item in self.pending if item["path"] == str(original)]
        if matches:
            allowed = [item for item in matches if expected_sha256 in {None, item["sha256"]} and source_id in {None, item["source_id"]}]
            if not allowed and expected_sha256 is not None and expected_sha256 not in {item["sha256"] for item in matches}:
                return super().resolve_path(original, expected_sha256=expected_sha256, source_id=source_id)
            if not allowed or len({item["sha256"] for item in allowed}) != 1:
                raise EngineError("semantic_source_declaration_conflict", "A new source read must match its exact declared identity and bytes.")
            actual = Path(allowed[0].get("actual", str(original)))
            _read_source(actual, allowed[0]["sha256"])
            return actual
        return super().resolve_path(original, expected_sha256=expected_sha256, source_id=source_id)
