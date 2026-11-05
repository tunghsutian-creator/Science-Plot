"""Pure selected-generation role facts: descriptions never confer host IO rights."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from collections.abc import Iterable, Mapping
from typing import Any

from .resources import _identity, _sha, resource_key


class ResourceRole(StrEnum):
    SOURCE_REFERENCE = "source_reference"
    IMMUTABLE_INPUT = "immutable_input"
    NATIVE_AUTHORITY = "native_authority"
    SCIENTIFIC_SPEC = "scientific_spec"
    REQUEST = "request"
    CATALOG = "catalog"
    INTENT = "intent"
    GENERATED_MEDIA = "generated_media"
    HISTORY = "history"
    RETIRED_NAMESPACE = "retired_namespace"


@dataclass(frozen=True)
class SourceVersionRef:
    locator: str
    version: str
    source_id: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.locator, str) or not self.locator or not _sha(self.version)
                or self.source_id is not None and not _identity(self.source_id)):
            raise ValueError("A source reference requires its original literal and exact byte version.")


@dataclass(frozen=True)
class ResourceFacts:
    project_id: str
    generation: str
    resource: str
    sha256: str | None
    mode: int | None
    roles: frozenset[ResourceRole]
    source_refs: tuple[SourceVersionRef, ...] = ()

    def __post_init__(self) -> None:
        resource_key(self.resource)
        if (not _identity(self.project_id) or not _identity(self.generation)
                or (self.sha256 is None) != (self.mode is None)
                or self.sha256 is not None and not _sha(self.sha256)
                or self.mode is not None and (type(self.mode) is not int or not 0 <= self.mode <= 0o777)
                or not isinstance(self.roles, frozenset) or any(not isinstance(role, ResourceRole) for role in self.roles)
                or not isinstance(self.source_refs, tuple) or any(not isinstance(ref, SourceVersionRef) for ref in self.source_refs)):
            raise ValueError("Resource facts require a selected real generation and exact canonical file facts.")


def _literal(generation: Mapping[str, Any], resource: str) -> str | None:
    if resource.startswith("@"):
        key, relative = resource[1:].split("/", 1)
    else:
        key, relative = "", resource
    origin = generation.get("locators", {}).get(key)
    return str(PurePosixPath(origin) / relative) if isinstance(origin, str) else None


def resource_facts(generation: Mapping[str, Any], resource: str, *,
                   declared_roles: Iterable[ResourceRole] = ()) -> ResourceFacts:
    """Interpret existing metadata only, never import/repair/query a Store."""
    resource_key(resource)
    roles = set(declared_roles)
    if resource in generation.get("input_resources", ()):
        roles.add(ResourceRole.IMMUTABLE_INPUT)
    if resource in generation.get("history_resources", ()):
        roles.add(ResourceRole.HISTORY)
    if any(resource.startswith(prefix + "/") for prefix in generation.get("retired_namespace_prefixes", ())):
        roles.add(ResourceRole.RETIRED_NAMESPACE)
    original = _literal(generation, resource)
    refs = []
    for identity, versions in generation.get("sources", {}).items():
        for version, entry in versions.items():
            if entry.get("logical") == resource or original is not None and entry.get("locator") == original:
                roles.add(ResourceRole.SOURCE_REFERENCE)
                refs.append(SourceVersionRef(entry["locator"], version, identity))
    entry = generation["files"].get(resource)
    return ResourceFacts(generation["project_id"], generation["generation"], resource,
                         entry["sha256"] if entry else None, entry["mode"] if entry else None,
                         frozenset(roles), tuple(refs))


def is_native_save_as_excluded(facts: ResourceFacts, *, selected_catalogs: Iterable[str] = ()) -> bool:
    return bool(facts.roles & {ResourceRole.SOURCE_REFERENCE, ResourceRole.IMMUTABLE_INPUT,
                              ResourceRole.HISTORY, ResourceRole.RETIRED_NAMESPACE}
                or facts.resource in selected_catalogs)
