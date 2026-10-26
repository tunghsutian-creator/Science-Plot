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
from sciplot_core.project_commands import PreparedSource, SourceTreeRead, InputRead
from sciplot_core.project_store.errors import ProjectConflict, ProjectSourceVersionMismatch
from sciplot_core.project_store.io import read_file, sha
from sciplot_core.project_store.source_resolver import ProjectSourceResolver
from sciplot_core.project_store.sealed_source_trees import SealedSourceTree


@dataclass(frozen=True)
class MappingInput:
    literal: str
    data: bytes
    mode: int
    actual_mode: int = field(compare=False)
    actual: Path = field(compare=False)

    @property
    def sha256(self) -> str:
        return sha(self.data)


@dataclass
class MappingInputReadSet:
    execution: str
    expected_source: Path | None = None
    files: dict[str, MappingInput] = field(default_factory=dict)
    sealed: bool = False
    trees: dict[str, SourceTreeRead] = field(default_factory=dict)
    sealed_trees: dict[str, SealedSourceTree] = field(default_factory=dict)
    tree_actuals: dict[str, Path] = field(default_factory=dict)
    metadata: set[str] = field(default_factory=set)
    committed_generation: str | None = None

    def publication_complete(self, receipt: dict[str, Any]) -> None:
        """Stop post-commit live checks only after this publisher returns its durable complete receipt."""
        if receipt.get("phase") != "complete" or not isinstance(receipt.get("generation"), str):
            raise ProjectConflict("A mapping publication must finish its durable generation before releasing its read scope.")
        for literal, item in self.files.items():
            entries = [entry for versions in receipt["draft"]["sources"].values() for entry in versions.values()
                       if entry.get("locator") == literal and entry["sha256"] == item.sha256]
            if len(entries) != 1:
                raise ProjectConflict("The complete publication does not contain this exact mapping input version.")
        self.committed_generation = receipt["generation"]

    def seal(self) -> None:
        if self.execution not in self.files:
            raise ProjectConflict("A mapping read set must include its verified execution.")
        self.sealed = True

    def require_current(self) -> None:
        actuals = {}
        for literal, observed in self.files.items():
            current, _actual = _read(Path(literal), observed.sha256, metadata=literal in self.metadata)
            actuals[literal] = _actual
            if current != observed:
                raise ProjectConflict("A confirmed mapping input changed after its exact read.")
        from sciplot_core.project_store.source_tree_io import observe

        selected = selected_source_resolver()
        for literal, tree in self.trees.items():
            binding = self.sealed_trees.get(literal)
            actual = actuals.get(literal) or (binding.view(selected.store)
                if binding is not None and isinstance(selected, ProjectSourceResolver) else self.tree_actuals.get(literal) or resolve_source_path(literal))
            if observe(str(actual))[0] != tree.tree_sha256:
                raise ProjectConflict("The confirmed mapping directory changed its complete membership.")

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

    def input_reads(self, snapshot: dict[str, Any]) -> tuple[InputRead, ...]:
        from sciplot_core.project_store.locators import logical_for_literal

        result = []
        for literal in sorted(self.metadata):
            logical = logical_for_literal(snapshot, literal)
            if logical is not None:
                known = [identity for identity, versions in snapshot["sources"].items()
                    if any(entry.get("locator") == literal for entry in versions.values())]
                if len(known) > 1:
                    raise ProjectConflict("A metadata input has ambiguous source identities.")
                identity = known[0] if known else canonical_json_sha256(
                    {"project_id": snapshot["project_id"], "locator": literal})[:32]
                result.append(InputRead(logical, identity, self.files[literal].sha256))
        return tuple(result)


_READ_SET: ContextVar[MappingInputReadSet | None] = ContextVar("sciplot_mapping_input_reads", default=None)


@contextmanager
def mapping_input_reads(execution: str | None, *, expected_source: Path | None = None) -> Iterator[MappingInputReadSet | None]:
    """Capture before preparation and keep every later read on those bytes."""
    if not execution:
        yield None
        return
    literal = str(mapping_execution_path(execution))
    previous = _READ_SET.get()
    if previous is not None:
        if previous.execution != literal:
            raise ProjectConflict("A mapping read scope cannot switch its confirmed execution.")
        if expected_source is not None and previous.expected_source not in (None, mapping_literal(expected_source)):
            raise ProjectConflict("A mapping read scope cannot change its selected original source.")
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
        if not registered and expected_source is None and not any(
                request.get("data_mapping_execution") and str(mapping_execution_path(request["data_mapping_execution"])) == literal
                for request in requests):
            raise ProjectConflict("The mapping execution is not declared by this exact canonical request.")
    observed = MappingInputReadSet(literal, expected_source=mapping_literal(expected_source) if expected_source is not None else None,
                                   metadata={literal})
    token = _READ_SET.set(observed)
    try:
        yield observed
        if observed.committed_generation is None:
            observed.require_current()
    finally:
        _READ_SET.reset(token)


def mapping_literal(path: Path) -> Path:
    # Check aliases before any resolve() can erase them. Preserved JSON paths
    # remain literals; source resolution below chooses only their actual IO.
    return Path(literal_source_path(canonical_path(path)))


def mapping_execution_path(reference: str | Path) -> Path:
    path = mapping_literal(Path(reference))
    if path.is_dir():
        return path / "execution.json"
    selected = selected_source_resolver()
    member = path / "execution.json"
    if not path.exists() and isinstance(selected, ProjectSourceResolver) and any(
            entry.get("locator") == str(member) for versions in selected.snapshot["sources"].values()
            for entry in versions.values()):
        return member  # An exact registered member, never a basename search.
    return path


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


def _read(path: Path, expected: str | None = None, *, metadata: bool = False) -> tuple[MappingInput, Path]:
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
    selected = selected_source_resolver()
    if isinstance(selected, ProjectSourceResolver) and actual.is_relative_to(selected.store.root / ".sciplot_store/sources"):
        selected.store.resolve_path(actual, expected_sha256=expected, source_id=identity, generation=selected.generation)
    parent = os.open(actual.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        data, mode = read_file(parent, actual.name)
    finally:
        os.close(parent)
    if expected is not None and sha(data) != expected:
        raise ProjectSourceVersionMismatch(literal, expected, sha(data), "A confirmed mapping input content hash changed from its exact source version.")
    metadata = metadata or active is not None and literal in active.metadata
    if metadata and original_mode is not None and actual == Path(literal) and mode != original_mode:
        raise ProjectConflict("A confirmed mapping input changed its registered permissions.")
    item = MappingInput(literal, data, previous.mode if previous is not None else
                        original_mode if original_mode is not None else mode, mode, actual)
    if previous is not None and (previous != item or previous.actual == actual and previous.actual_mode != mode):
        fields = [name for name in ("literal", "data", "mode", "actual_mode")
                  if getattr(previous, name) != getattr(item, name)]
        raise ProjectConflict("A confirmed mapping input changed during preparation: " + ", ".join(fields))
    if active is not None:
        active.files[literal] = item
        if metadata:
            active.metadata.add(literal)
            active.trees[literal] = SourceTreeRead(literal, canonical_json_sha256(
                {"kind": "file", "content_sha256": item.sha256}, allow_nan=False))
    return item, actual


def mapping_file_path(path: Path, *, expected_sha256: str | None = None) -> Path:
    return _read(path, expected_sha256)[1]


def mapping_file_sha256(path: Path, *, expected_sha256: str | None = None) -> str:
    return _read(path, expected_sha256)[0].sha256


def mapping_file_bytes(path: Path, *, expected_sha256: str | None = None) -> bytes:
    return _read(path, expected_sha256)[0].data


def mapping_read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(_read(path, metadata=True)[0].data)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def require_mapping_original_source(root: Path, files: dict[str, str], seed: dict[str, Any]) -> None:
    """Check the explicit planning intent before any original data are read."""
    active = _READ_SET.get()
    expected = active.expected_source if active is not None else None
    if expected is None:
        return
    members = {mapping_literal(root / name): digest for name, digest in files.items()}
    if (not isinstance(seed.get("input"), str) or mapping_literal(Path(seed["input"])) != expected
            or not members or any(not path.is_relative_to(expected) for path in members)):
        raise ProjectConflict("The confirmed mapping does not bind the exact selected original task source.")
    if set(members) != {expected}:
        from sciplot_core.project_store.source_tree_io import observe

        version = canonical_json_sha256({"kind": "directory", "files": [
            {"path": path.relative_to(expected).as_posix(), "content_sha256": digest}
            for path, digest in sorted(members.items())]}, allow_nan=False)
        allowed = {path.relative_to(expected).as_posix() for path in members}
        if observe(str(resolve_source_path(expected)), allowed=allowed)[0] != version:
            raise ProjectConflict("The selected original directory differs from its complete confirmed member inventory.")
        assert active is not None
        active.trees[str(expected)] = SourceTreeRead(str(expected), version)


def mapping_execution_header(path: Path, kind: str) -> dict[str, Any]:
    payload = mapping_read_json(path)
    if payload.get("kind") != kind:
        raise ValueError("Not a SciPlot data mapping execution manifest.")
    version = payload.get("version")
    if type(version) is not int or version not in {1, 2, 3}:
        raise ValueError(f"Unsupported data mapping execution version: {version!r}")
    if payload.get("status") != "passed":
        raise ValueError("Data mapping execution is not in passed state.")
    return payload


def mark_mapping_metadata(path: Path) -> Path:
    active = _READ_SET.get()
    if active is not None:
        literal = str(mapping_literal(path))
        active.metadata.add(literal)
        item = active.files.get(literal)
        if item is not None:
            active.trees[literal] = SourceTreeRead(literal, canonical_json_sha256(
                {"kind": "file", "content_sha256": item.sha256}, allow_nan=False))
    return path


def mapping_execution_is_sealed(reference: str | Path) -> bool:
    """Readonly query fact for this exact execution, without a source view.

    A query must not run numeric replay through a materializing source reader
    when this selected metadata version is an explicit imported sealed input.
    """
    from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver

    selected = selected_source_resolver()
    if not isinstance(selected, ProjectSourceResolver) or isinstance(selected, ProjectCandidateResolver):
        return False
    return mapping_imported_execution(reference)


def mapping_imported_execution(reference: str | Path) -> bool:
    """Explicit immutable execution binding for native preparation, including its private image."""
    selected = selected_source_resolver()
    if not isinstance(selected, ProjectSourceResolver):
        return False
    literal = str(mapping_execution_path(reference))
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


def mapping_effective_source(reference: str | Path, effective: str | Path) -> tuple[str | None, str] | None:
    """Readonly exact composite-file fact after the caller's full numeric replay."""
    from sciplot_core.project_store.source_inspection import inspect_file

    selected = selected_source_resolver()
    if not isinstance(selected, ProjectSourceResolver):
        return None
    execution = str(mapping_execution_path(reference))
    literal = str(mapping_literal(Path(effective)))
    active = _READ_SET.get()
    if active is not None and active.sealed and active.execution == execution:
        active.require_current()
        payload = json.loads(active.files[execution].data)
        if payload["effective_input"] != literal:
            raise ProjectConflict("The observed composite is not this verified execution's effective input.")
        if payload["effective_input"] == payload["data_dir"]:
            return None
        observed = active.files[literal]
        identity, version, _mode = _registered(literal, observed.sha256)
        return identity, observed.sha256
    identity, version, _mode = _registered(execution, None)
    if identity is None or version is None:
        raise ProjectConflict("A composite mapping fact requires its exact registered execution version.")
    inspect_file(selected.store, execution, expected_sha256=version, source_id=identity, generation=selected.generation)
    with selected.store._locked() as (io, _current):
        payload = json.loads(io.get(selected.snapshot["sources"][identity][version]))
    if payload["effective_input"] != literal:
        raise ProjectConflict("The observed composite is not this verified execution's effective input.")
    if payload["effective_input"] == payload["data_dir"]:
        return None
    identity, version, _mode = _registered(literal, None)
    if identity is None or version is None:
        raise ProjectConflict("The verified composite lacks one exact registered source version.")
    return identity, version


@contextmanager
def mapping_input_scope(readset: MappingInputReadSet | None) -> Iterator[None]:
    """Keep the original witness active through later QA/style workers."""
    if readset is None:
        yield
        return
    if not readset.sealed:
        raise ProjectConflict("The native mapping scope lacks complete verification.")
    readset.require_current()
    token = _READ_SET.set(readset)
    try:
        yield
        readset.require_current()
    finally:
        _READ_SET.reset(token)


@contextmanager
def without_mapping_inputs() -> Iterator[None]:
    token = _READ_SET.set(None)
    try:
        yield
    finally:
        _READ_SET.reset(token)
