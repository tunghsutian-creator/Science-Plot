"""Exact IO witnesses for the finite, immutable confirmed-mapping inputs.

The active read set is invocation-local. Only the existing project generation
and its PreparedSources persist bytes; this module never installs a file view.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path, selected_source_resolver
from sciplot_core.project_commands import PreparedSource
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.io import read_file, sha
from sciplot_core.project_store.source_resolver import ProjectSourceResolver


@dataclass(frozen=True)
class MappingInput:
    literal: str
    data: bytes
    mode: int

    @property
    def sha256(self) -> str:
        return sha(self.data)


@dataclass
class MappingInputReadSet:
    execution: str
    files: dict[str, MappingInput] = field(default_factory=dict)
    sealed: bool = False

    def seal(self) -> None:
        if self.execution not in self.files:
            raise ProjectConflict("A mapping read set must include its verified execution.")
        self.sealed = True

    def require_current(self) -> None:
        for literal, observed in self.files.items():
            current, _actual = _read(Path(literal), observed.sha256)
            if current != observed:
                raise ProjectConflict("A confirmed mapping input changed after its exact read.")

    def prepared_sources(self, snapshot: dict[str, Any]) -> tuple[PreparedSource, ...]:
        if not self.sealed or self.execution not in self.files:
            raise ProjectConflict("A mapped preparation requires its actual execution read witness.")
        self.require_current()
        result = []
        for literal, item in sorted(self.files.items()):
            identities = [identity for identity, versions in snapshot["sources"].items()
                if any(entry.get("locator") == literal for entry in versions.values())]
            if len(identities) > 1:
                raise ProjectConflict("A mapping input has ambiguous registered source identities.")
            identity = identities[0] if identities else canonical_json_sha256(
                {"project_id": snapshot["project_id"], "locator": literal})[:32]
            result.append(PreparedSource(identity, literal, item.sha256, item.data, mode=item.mode))
        return tuple(result)


_READ_SET: ContextVar[MappingInputReadSet | None] = ContextVar("sciplot_mapping_input_reads", default=None)


@contextmanager
def mapping_input_reads(execution: str | None) -> Iterator[MappingInputReadSet | None]:
    """Capture before preparation and keep every later read on those bytes."""
    if not execution:
        yield None
        return
    literal = str(mapping_literal(Path(execution)))
    previous = _READ_SET.get()
    if previous is not None:
        if previous.execution != literal:
            raise ProjectConflict("A mapping read scope cannot switch its confirmed execution.")
        yield previous
        return
    selected = selected_source_resolver()
    if isinstance(selected, ProjectSourceResolver):
        registered = [entry for versions in selected.snapshot["sources"].values()
            for entry in versions.values() if entry.get("locator") == literal]
        requests = []
        entry = selected.snapshot["files"].get("plot_request.json")
        if entry is not None:
            with selected.store._locked() as (io, _current):
                requests.append(json.loads(io.get(entry)))
        from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver

        if isinstance(selected, ProjectCandidateResolver):
            actual = selected.resolve_path(selected.store.root / "plot_request.json")
            requests.append(json.loads(actual.read_bytes()))
        if not registered and not any(request.get("data_mapping_execution") == literal for request in requests):
            raise ProjectConflict("The mapping execution is not declared by this exact canonical request.")
    observed = MappingInputReadSet(literal)
    token = _READ_SET.set(observed)
    try:
        yield observed
        observed.require_current()
    finally:
        _READ_SET.reset(token)


def mapping_literal(path: Path) -> Path:
    # Check aliases before any resolve() can erase them. Preserved JSON paths
    # remain literals; source resolution below chooses only their actual IO.
    return Path(literal_source_path(canonical_path(path)))


def _registered(literal: str, expected: str | None) -> tuple[str | None, str | None, int | None]:
    selected = selected_source_resolver()
    if not isinstance(selected, ProjectSourceResolver):
        return None, expected, None
    matches = [(identity, version, entry) for identity, versions in selected.snapshot["sources"].items()
        for version, entry in versions.items() if entry.get("locator") == literal
        and (expected is None or expected == version)]
    if len(matches) > 1:
        raise ProjectConflict("An immutable mapping locator does not bind one exact source version.")
    if not matches:
        if expected is None and _READ_SET.get() is None:
            raise ProjectConflict("Unregistered mapping metadata requires its canonical preparation read set.")
        return None, expected, None
    identity, version, entry = matches[0]
    return identity, version, entry["mode"]


def _read(path: Path, expected: str | None = None) -> tuple[MappingInput, Path]:
    literal = str(mapping_literal(path))
    active = _READ_SET.get()
    previous = active.files.get(literal) if active is not None else None
    if active is not None and active.sealed and previous is None:
        raise ProjectConflict("A verified mapping read set cannot expand its immutable input closure.")
    if previous is not None:
        if expected is not None and expected != previous.sha256:
            raise ProjectConflict("One mapping invocation requested different versions of an immutable input.")
        expected = previous.sha256
    identity, expected, original_mode = _registered(literal, expected)
    actual = canonical_path(resolve_source_path(literal, expected_sha256=expected, source_id=identity))
    parent = os.open(actual.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        data, mode = read_file(parent, actual.name)
    finally:
        os.close(parent)
    if expected is not None and sha(data) != expected:
        raise ProjectConflict("A confirmed mapping input content hash changed from its exact source version.")
    if original_mode is not None and actual == Path(literal) and mode != original_mode:
        raise ProjectConflict("A confirmed mapping input changed its registered permissions.")
    item = MappingInput(literal, data, original_mode if original_mode is not None else mode)
    if previous is not None and previous != item:
        raise ProjectConflict("A confirmed mapping input changed during preparation.")
    if active is not None:
        active.files[literal] = item
    return item, actual


def mapping_file_path(path: Path, *, expected_sha256: str | None = None) -> Path:
    return _read(path, expected_sha256)[1]


def mapping_file_sha256(path: Path, *, expected_sha256: str | None = None) -> str:
    return _read(path, expected_sha256)[0].sha256


def mapping_file_bytes(path: Path, *, expected_sha256: str | None = None) -> bytes:
    return _read(path, expected_sha256)[0].data


def mapping_read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(mapping_file_bytes(path))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def mapping_execution_is_sealed(reference: str | Path) -> bool:
    """Readonly query fact for this exact execution, without a source view.

    A query must not run numeric replay through a materializing source reader
    when this selected metadata version is an explicit imported sealed input.
    """
    from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver

    selected = selected_source_resolver()
    if not isinstance(selected, ProjectSourceResolver) or isinstance(selected, ProjectCandidateResolver):
        return False
    literal = str(mapping_literal(Path(reference)))
    matches = [(identity, version, entry) for identity, versions in selected.snapshot["sources"].items()
        for version, entry in versions.items() if entry.get("locator") == literal]
    if not matches:
        return False
    if len(matches) != 1:
        raise ProjectConflict("An immutable mapping locator does not bind one exact source version.")
    identity, version, entry = matches[0]
    with selected.store._locked() as (io, _current):
        local = io.read("local_sources.json")
        if local is None or local.get("versions", {}).get(identity, {}).get(version) != entry["sha256"]:
            return False
        io.get(entry)
        return True
