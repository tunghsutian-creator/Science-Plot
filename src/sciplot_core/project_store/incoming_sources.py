"""Finite host expectations for fresh input or explicitly sealed baseline reads.

These invocation-local capabilities never register a source version or publish
bytes. Incoming reads verify the selected live file; sealed reads verify one
already registered immutable version. Ordinary runtime resolution is unchanged.
"""
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Literal

from .errors import ProjectConflict, ProjectStoreError
from .io import STORE, directory, read_file, sha
from .locators import logical_for_literal
from .repository import FileProjectStore
from .sealed_source_trees import SealedSourceTree, resolve_tree_view

SourceReadMode = Literal["incoming", "sealed"]


@dataclass(frozen=True)
class SourceExpectation:
    literal: str
    source_id: str
    sha256: str

    def __post_init__(self) -> None:
        if (not isinstance(self.literal, str) or len(self.literal) > 8192 or "\x00" in self.literal
                or not Path(self.literal).is_absolute() or str(Path(self.literal)) != self.literal
                or ".." in Path(self.literal).parts
                or not isinstance(self.source_id, str) or re.fullmatch(r"[0-9a-f]{32}", self.source_id) is None
                or not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None):
            raise ProjectStoreError("A source expectation requires an exact literal, source UUID and version hash.")

    def to_payload(self) -> dict[str, str]:
        return {"literal": self.literal, "source_id": self.source_id, "sha256": self.sha256}

    @classmethod
    def from_payload(cls, value: Any) -> "SourceExpectation":
        if not isinstance(value, dict) or set(value) != {"literal", "source_id", "sha256"}:
            raise ProjectStoreError("Invalid closed source expectation.")
        return cls(value["literal"], value["source_id"], value["sha256"])


@dataclass(frozen=True)
class _Selection:
    project_id: str
    generation: str
    mode: SourceReadMode
    sources: tuple[SourceExpectation, ...]
    trees: tuple[SealedSourceTree, ...] = ()


_SELECTED: ContextVar[_Selection | None] = ContextVar("project_source_expectations", default=None)


def selected_expectations(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    selected = _SELECTED.get()
    if selected is None or (selected.project_id, selected.generation) != (snapshot["project_id"], snapshot["generation"]):
        return None
    payload: dict[str, Any] = {"mode": selected.mode, "sources": [source.to_payload() for source in selected.sources]}
    if selected.trees:
        payload["trees"] = [tree.to_payload() for tree in selected.trees]
    return payload


def expectation_trees(value: dict[str, Any]) -> tuple[SealedSourceTree, ...]:
    items = value.get("trees", [])
    if not isinstance(items, list) or len(items) > 64:
        raise ProjectStoreError("Source-tree expectations must be an explicit finite list.")
    return tuple(SealedSourceTree.from_payload(item) for item in items)


def expectation_payload(value: Any) -> tuple[SourceReadMode, tuple[SourceExpectation, ...]]:
    fields = {"mode", "sources"} | ({"trees"} if isinstance(value, dict) and "trees" in value else set())
    if (not isinstance(value, dict) or set(value) != fields
            or not isinstance(value["mode"], str) or value["mode"] not in {"incoming", "sealed"}
            or not isinstance(value["sources"], list)
            or len(value["sources"]) > 64):
        raise ProjectStoreError("Invalid finite source expectation capability.")
    mode: SourceReadMode = "incoming" if value["mode"] == "incoming" else "sealed"
    trees = expectation_trees(value)
    if not (value["sources"] or trees):
        raise ProjectStoreError("A source scope requires explicit file or complete tree witnesses.")
    return mode, tuple(SourceExpectation.from_payload(item) for item in value["sources"])


@contextmanager
def source_expectation_scope(snapshot: dict[str, Any], mode: SourceReadMode,
                             sources: Sequence[SourceExpectation], *, trees: Sequence[SealedSourceTree] = (),
                             store: FileProjectStore | None = None) -> Iterator[None]:
    frozen = tuple(sources)
    sealed_trees = tuple(trees)
    if (mode not in {"incoming", "sealed"} or not (frozen or sealed_trees)
            or len(frozen) > 64 or len(sealed_trees) > 64
            or any(not isinstance(item, SourceExpectation) for item in frozen)
            or len({item.literal for item in frozen}) != len(frozen)):
        raise ProjectStoreError("Source expectations must be finite and unambiguous by exact literal.")
    if (any(not isinstance(item, SealedSourceTree) for item in sealed_trees)
            or sealed_trees and store is None
            or len({item.tree.locator for item in sealed_trees}) != len(sealed_trees)
            or {item.tree.locator for item in sealed_trees} & {item.literal for item in frozen}):
        raise ProjectStoreError("Complete trees need one explicit store and unambiguous typed roots.")
    for tree in sealed_trees:
        assert store is not None
        if mode == "sealed":
            tree.view(store)
        else:
            tree.live(store, generation=snapshot["generation"])
    for item in frozen:
        identities = {identity for identity, versions in snapshot["sources"].items()
                      if any(entry.get("locator") == item.literal for entry in versions.values())}
        if identities != {item.source_id}:
            raise ProjectConflict("The expectation must retain this literal's unique registered source identity.")
        if mode == "incoming" and logical_for_literal(snapshot, item.literal) is not None:
            raise ProjectConflict("Incoming external reads cannot bypass a registered project input resource.")
        if mode == "sealed":
            entry = snapshot["sources"][item.source_id].get(item.sha256)
            if entry is None or entry.get("locator") != item.literal:
                raise ProjectConflict("A sealed baseline requires its exact registered source version and literal.")
    token = _SELECTED.set(_Selection(snapshot["project_id"], snapshot["generation"], mode, frozen, sealed_trees))
    try:
        yield
    finally:
        _SELECTED.reset(token)


def require_unambiguous_scope() -> None:
    if _SELECTED.get() is not None:
        raise ProjectConflict("Separate baseline and incoming source reads into distinct invocation scopes.")


@contextmanager
def without_source_expectations() -> Iterator[None]:
    """A worker request cannot inherit unbound capabilities from a previous call."""
    token = _SELECTED.set(None)
    try:
        yield
    finally:
        _SELECTED.reset(token)


def _verify_file(path: Path, expected: str) -> None:
    root = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with directory(root, path.parts[1:-1]) as parent:
            data = read_file(parent, path.name)[0]
    finally:
        os.close(root)
    if sha(data) != expected:
        raise ProjectConflict("The selected source bytes differ from the explicit invocation expectation.")


def resolve_expected_source(store: FileProjectStore, snapshot: dict[str, Any], original: str | Path, *,
                            expected_sha256: str | None, source_id: str | None) -> Path | None:
    payload = selected_expectations(snapshot)
    if payload is None:
        return None
    mode, sources = expectation_payload(payload)
    literal = str(original)
    matched = next((item for item in sources if item.literal == literal), None)
    if matched is None:
        tree = resolve_tree_view(store, expectation_trees(payload), original, expected_sha256=expected_sha256,
                                 sealed=mode == "sealed", generation=snapshot["generation"])
        if tree is None:
            return None
        actual, origin, root = tree
        if source_id is not None:
            member = next((item for item in sources if item.literal == origin), None)
            if (root or member is None or member.source_id != source_id
                    or expected_sha256 is not None and expected_sha256 != member.sha256):
                raise ProjectConflict("A complete tree cannot invent a scientific file identity or version.")
            _verify_file(actual, member.sha256)
        return actual
    if (expected_sha256 is not None and expected_sha256 != matched.sha256
            or source_id is not None and source_id != matched.source_id):
        raise ProjectConflict("The requested source identity/version differs from the explicit invocation expectation.")
    actual = Path(literal) if mode == "incoming" else store.resolve_source(matched.source_id, matched.sha256)
    _verify_file(actual, matched.sha256)
    return actual


def selected_sealed_view(store: FileProjectStore, snapshot: dict[str, Any], actual: Path, *,
                         expected_sha256: str | None = None, source_id: str | None = None) -> Path | None:
    """A candidate can reread/reverse only the selected immutable baseline views."""
    payload = selected_expectations(snapshot)
    if payload is None or payload["mode"] != "sealed":
        return None
    _, sources = expectation_payload(payload)
    for item in sources:
        view = store.root / STORE / "sources" / item.source_id / item.sha256 / Path(item.literal).name
        if actual == view:
            return resolve_expected_source(store, snapshot, item.literal,
                expected_sha256=expected_sha256, source_id=source_id)
    tree = resolve_tree_view(store, expectation_trees(payload), actual, expected_sha256=expected_sha256)
    if tree is None:
        return None
    return resolve_expected_source(store, snapshot, actual, expected_sha256=expected_sha256, source_id=source_id)


def literal_sealed_tree(store: FileProjectStore, snapshot: dict[str, Any], actual: Path) -> str | None:
    payload = selected_expectations(snapshot)
    if payload is None:
        return None
    tree = resolve_tree_view(store, expectation_trees(payload), actual,
                             sealed=payload["mode"] == "sealed", generation=snapshot["generation"])
    return tree[1] if tree is not None else None
