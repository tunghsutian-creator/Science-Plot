"""Observe pinned source facts without creating filesystem source views."""
from dataclasses import dataclass
import os
import stat
from pathlib import Path
from collections.abc import Set
from typing import Any

from . import commands, directories, locators, state
from .errors import ProjectConflict, ProjectStoreError, ProjectSourceVersionMismatch
from .io import StoreIO, directory, parts, read_file, sha
from .incoming_sources import expectation_payload, expectation_trees, selected_expectations
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from .paths import LocatorStore
from .root_bindings import require as require_roots
from .source_tree_io import observe
from .repository import FileProjectStore


@dataclass(frozen=True)
class SourceFileObservation:
    """None physical means an explicit sealed binding, never a live-file claim."""
    sha256: str
    physical: Path | None


def _scoped_parent(value: dict[str, Any], literal: Path) -> bool:
    payload = selected_expectations(value)
    if payload is None:
        return False
    _, sources = expectation_payload(payload)
    return (any(Path(item.literal).is_relative_to(literal) for item in sources)
            or any(literal.is_relative_to(item.tree.locator) or Path(item.tree.locator).is_relative_to(literal)
                   for item in expectation_trees(payload)))


def inspect_invocation_file(store: LocatorStore, original: str | Path, *, expected_sha256: str | None = None,
                            source_id: str | None = None, generation: str | None = None,
                            tree: bool = False) -> SourceFileObservation | None:
    """Retain explicit source-phase precedence over a candidate's own members."""
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        require_roots(io, current)
        literal = Path(original).expanduser().absolute()
        fact = _invocation_file(io, value, literal, expected_sha256, source_id)
        if tree and fact is None and _scoped_parent(value, literal):
            raise ProjectStoreError("Invocation file scope cannot be replaced by the parent source directory.")
        return fact


def inspect_invocation_tree(store: FileProjectStore, original: str | Path, *,
                            generation: str | None = None, allowed: Set[str] | None = None) -> str | None:
    """Only a declared whole-tree witness can expose its complete namespace."""
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        require_roots(io, current)
        payload = selected_expectations(value)
        if payload is None:
            return None
        mode, _sources = expectation_payload(payload)
        literal = Path(original).expanduser().absolute()
        for item in expectation_trees(payload):
            actual = item.view(store) if mode == "sealed" else item.live(store, generation=value["generation"])
            if literal not in {Path(item.tree.locator), actual}:
                continue
            # live()/view() already verified the exact admitted origin or bound
            # imported census. Its sealed member facts also include empty dirs;
            # a file-only caller must match the entire ordinary file set.
            record = state.command(io, item.command_id, item.command_digest)
            if record is None:
                raise ProjectConflict("The complete tree lost its exact admitted command.")
            proof = state.sealed_draft(io, record)["source_tree_origins"][item.tree.locator]
            members = {name for name, entry in proof["members"].items() if stat.S_ISREG(entry["mode"])}
            if allowed is not None and set(allowed) != members:
                raise ProjectConflict("The requested complete tree differs from its exact admitted member set.")
            return item.tree.tree_sha256
        return None


def physical_file(path: Path, expected_sha256: str | None = None) -> SourceFileObservation:
    path = path.expanduser().absolute()
    if any(part in {".", ".."} for part in path.parts):
        raise ProjectStoreError("A source observation requires an exact canonical file.")
    root = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with directory(root, path.parts[1:-1]) as parent:
            data, _mode = read_file(parent, path.name)
    finally:
        os.close(root)
    digest = sha(data)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ProjectSourceVersionMismatch(str(path), expected_sha256, digest,
            "The exact original source differs from its registered version.")
    return SourceFileObservation(digest, path)


def _invocation_file(io: StoreIO, value: dict[str, Any], literal: Path,
                     expected: str | None, source_id: str | None) -> SourceFileObservation | None:
    payload = selected_expectations(value)
    if payload is None:
        return None
    mode, sources = expectation_payload(payload)
    selected = next((item for item in sources if item.literal == str(literal)), None)
    if selected is None:
        if any(literal.is_relative_to(item.tree.locator) or Path(item.tree.locator).is_relative_to(literal)
               for item in expectation_trees(payload)):
            raise ProjectStoreError("Read-only query requires explicit file facts for an invocation tree.")
        return None
    if (expected is not None and expected != selected.sha256
            or source_id is not None and source_id != selected.source_id):
        raise ProjectConflict("The requested source identity/version differs from the explicit invocation expectation.")
    if mode == "incoming":
        with io.validation_fence():
            return physical_file(literal, selected.sha256)
    entry = value["sources"].get(selected.source_id, {}).get(selected.sha256)
    if entry is None:
        raise ProjectStoreError("The selected sealed source version is not in this generation.")
    io.get(entry)
    return SourceFileObservation(selected.sha256, None)


def inspect_file(store: LocatorStore, original: str | Path, *, expected_sha256: str | None = None,
                 source_id: str | None = None, generation: str | None = None) -> SourceFileObservation:
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        require_roots(io, current)
        literal = Path(original).expanduser().absolute()
        explicit = _invocation_file(io, value, literal, expected_sha256, source_id)
        if explicit is not None:
            return explicit
        cached = locators.owned_source_view(io, value, literal,
            expected_sha256=expected_sha256, source_id=source_id)
        if cached is not None:
            literal = Path(cached[1])
        logical = locators.logical_for_literal(value, str(literal))
        if logical is None:
            try:
                actual = store.logical_path(literal)
            except ProjectStoreError:
                actual = None
            if actual is not None and actual in value["files"]:
                logical = actual
        if generation is not None and generation != current["generation"] and source_id is not None and expected_sha256 is not None:
            origin = locators.original_for_logical(value, logical) if logical else str(literal)
            _identity, version, entry = locators.source_entry(io, value, origin,
                expected_sha256=expected_sha256, source_id=source_id)
            io.get(entry)
            return SourceFileObservation(version, None)
        if logical is not None:
            entry = locators.checked_member(io, value, logical, expected_sha256)
            if source_id is not None:
                locators.source_entry(io, value, locators.original_for_logical(value, logical),
                    expected_sha256=entry["sha256"], source_id=source_id)
            components = parts(logical)
            key = components[0][1:] if components[0].startswith("@") else ""
            path = (io.locations[key] if key else io.root).joinpath(*(components[1:] if key else components))
            return SourceFileObservation(entry["sha256"], path)
        identity, version, entry = locators.source_entry(io, value, str(literal),
            expected_sha256=expected_sha256, source_id=source_id)
        local = io.read("local_sources.json") or {"versions": {}}
        if local["versions"].get(identity, {}).get(version) == entry["sha256"]:
            io.get(entry)
            return SourceFileObservation(version, None)
        try:
            commands.verify_sources(io, {identity: {version: entry}})
        except ProjectConflict as exc:
            raise ProjectConflict(f"The registered version is unavailable or changed: {exc}") from exc
        return SourceFileObservation(version, literal)


def inspect_tree(store: LocatorStore, original: str | Path, *, generation: str | None = None,
                 allowed: Set[str] | None = None) -> str:
    """Observe a registered whole namespace or an already-bound closed source set."""
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        require_roots(io, current)
        literal = Path(original).expanduser().absolute()
        payload = selected_expectations(value)
        if payload is not None:
            explicit = _invocation_file(io, value, literal, None, None)
            if explicit is not None:
                return canonical_json_sha256({"kind": "file", "content_sha256": explicit.sha256}, allow_nan=False)
            if _scoped_parent(value, literal):
                raise ProjectStoreError("Invocation file scope cannot be replaced by the parent source directory.")
        logical = locators.logical_for_literal(value, str(literal))
        if logical is None:
            try:
                actual = store.logical_path(literal)
            except ProjectStoreError:
                actual = None
            if actual is not None and actual in value["files"]:
                logical = actual
        if logical is not None:
            entry = locators.checked_member(io, value, logical, None)
            return canonical_json_sha256({"kind": "file", "content_sha256": entry["sha256"]}, allow_nan=False)
        selected = directories._prefix(value, literal, {"": io.root, **io.locations})
        if selected is not None:
            prefix, _origin = selected
            components = tuple(prefix.rstrip("/").split("/")) if prefix else ()
            key = components[0][1:] if components and components[0].startswith("@") else ""
            if io.location_members.get(key) is not None:
                raise ProjectStoreError("A finite file grant cannot expose a source directory.")
            checked = directories._checked_prefix(io, value, literal)
            if checked is None or checked[0] != prefix:
                raise ProjectConflict("The current source directory has no exact namespace witness.")
            literal = (io.locations[key] if key else io.root).joinpath(*(components[1:] if key else components))
        elif allowed is None:
            raise ProjectStoreError("A source directory needs a registered namespace or complete source-version set.")
        return observe(str(literal), allowed=set(allowed) if allowed is not None else None)[0]
