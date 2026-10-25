"""Pure logical resources, selected observations and captured source versions."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256

def _identity(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None

def _sha(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None

def resource_key(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or PurePosixPath(value).is_absolute() or any(part in {"", ".", ".."} for part in value.split("/"))
            or str(PurePosixPath(value)) != value):
        raise ValueError("A resource must be a canonical relative logical path in a host-selected root.")
    if value.startswith("@") and ("/" not in value or not _identity(value.split("/", 1)[0][1:])):
        raise ValueError("An external resource requires an explicit host-selected root ID.")
    return value

@dataclass(frozen=True)
class ProjectionRead:
    resource: str
    kind: str
    key: str
    sha256: str

    def __post_init__(self) -> None:
        resource_key(self.resource)
        if (self.kind not in {"studio_figure_v1", "native_suite_figure_v1"}
                or not _identity(self.key) or not _sha(self.sha256)):
            raise ValueError("A projected read requires a supported fixed selector and an exact digest.")

    def to_payload(self) -> dict[str, str]:
        return {"resource": self.resource, "kind": self.kind, "key": self.key, "sha256": self.sha256}

@dataclass(frozen=True)
class NativeAdoption:
    resource: str
    before_sha256: str
    observed_sha256: str
    audit_sha256: str

    def __post_init__(self) -> None:
        resource_key(self.resource)
        if (PurePosixPath(self.resource).suffix.lower() != ".vsz"
                or not all(_sha(value) for value in (self.before_sha256, self.observed_sha256, self.audit_sha256))):
            raise ValueError("Native adoption binds an exact saved VSZ, previous bytes and domain audit receipt.")

    def to_payload(self) -> dict[str, str]:
        return {"resource": self.resource, "before_sha256": self.before_sha256,
                "observed_sha256": self.observed_sha256, "audit_sha256": self.audit_sha256}


@dataclass(frozen=True)
class SourceAdoption:
    resource: str
    source_id: str
    before_sha256: str
    observed_sha256: str

    def __post_init__(self) -> None:
        resource_key(self.resource)
        if (not isinstance(self.source_id, str) or re.fullmatch(r"[a-f0-9]{32}", self.source_id) is None
                or not _sha(self.before_sha256) or not _sha(self.observed_sha256)):
            raise ValueError("A source observation requires its exact registered identity and old/new versions.")

    def to_payload(self) -> dict[str, str]:
        return {"resource": self.resource, "source_id": self.source_id,
                "before_sha256": self.before_sha256, "observed_sha256": self.observed_sha256}


@dataclass(frozen=True)
class NamespaceMember:
    relative: str
    sha256: str
    size: int
    mode: int

    def __post_init__(self) -> None:
        resource_key(self.relative)
        if (self.relative.startswith("@") or self.relative == ".sciplot_semantic_owner.json"
                or not _sha(self.sha256) or type(self.size) is not int or self.size < 0
                or type(self.mode) is not int or not 0 <= self.mode <= 0o777):
            raise ValueError("An observed namespace member requires a relative file, exact bytes and ordinary mode.")

    def to_payload(self) -> dict[str, Any]:
        return {"relative": self.relative, "sha256": self.sha256, "size": self.size, "mode": self.mode}


@dataclass(frozen=True)
class NamespaceTransfer:
    prefix: str
    history_prefix: str
    attachment_id: str
    original_head_sha256: str
    refusal_sha256: str
    owner_sha256: str
    history_owner_sha256: str
    members: tuple[NamespaceMember, ...]
    physical_backup_prefix: str | None = None

    def __post_init__(self) -> None:
        resource_key(self.prefix)
        resource_key(self.history_prefix)
        old, history = PurePosixPath(self.prefix), PurePosixPath(self.history_prefix)
        if self.physical_backup_prefix is not None:
            resource_key(self.physical_backup_prefix)
            physical = PurePosixPath(self.physical_backup_prefix)
            if (physical.is_relative_to(old) or old.is_relative_to(physical)
                    or physical.parts[0] in {".sciplot_store", ".sciplot_resources"}):
                raise ValueError("The observed physical backup must be a disjoint exact host resource.")
        if (old.is_relative_to(history) or history.is_relative_to(old)
                or any(path.parts[0] in {".sciplot_store", ".sciplot_resources"} for path in (old, history))
                or not isinstance(self.attachment_id, str) or re.fullmatch(r"[a-f0-9]{32}", self.attachment_id) is None
                or not all(_sha(value) for value in (self.original_head_sha256, self.refusal_sha256,
                    self.owner_sha256, self.history_owner_sha256))
                or not isinstance(self.members, tuple) or not self.members
                or any(not isinstance(item, NamespaceMember) for item in self.members)
                or len({item.relative for item in self.members}) != len(self.members)
                or not any(item.relative == "head.json" and item.sha256 == self.original_head_sha256
                           for item in self.members)):
            raise ValueError("An ownership transfer binds disjoint exact namespaces and their frozen refusal/history bytes.")

    def to_payload(self) -> dict[str, Any]:
        return {"prefix": self.prefix, "history_prefix": self.history_prefix,
                "attachment_id": self.attachment_id, "original_head_sha256": self.original_head_sha256,
                "refusal_sha256": self.refusal_sha256, "owner_sha256": self.owner_sha256,
                "history_owner_sha256": self.history_owner_sha256,
                "members": [item.to_payload() for item in sorted(self.members, key=lambda item: item.relative)],
                "physical_backup_prefix": self.physical_backup_prefix}


def membership_digest(names: Iterable[str]) -> str:
    return canonical_json_sha256(sorted(set(names)), allow_nan=False)


@dataclass(frozen=True)
class PreparedFile:
    data: bytes
    mode: int

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or type(self.mode) is not int or not 0 <= self.mode <= 0o777:
            raise ValueError("A prepared file requires captured bytes and ordinary permission bits.")

    def descriptor(self) -> dict[str, Any]:
        self.__post_init__()
        return {"sha256": hashlib.sha256(self.data).hexdigest(), "size": len(self.data), "mode": self.mode}


@dataclass(frozen=True)
class MembershipRead:
    prefix: str
    members_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.prefix, str):
            raise ValueError("A membership prefix must be an explicit logical namespace.")
        if self.prefix and not (self.prefix.startswith("@") and "/" not in self.prefix and _identity(self.prefix[1:])):
            resource_key(self.prefix)
        if not _sha(self.members_sha256):
            raise ValueError("A membership read must bind an exact logical name set.")

    @classmethod
    def capture(cls, files: Mapping[str, Any], prefix: str = "") -> MembershipRead:
        names = [name for name in files if (name == prefix or name.startswith(prefix + "/"))
                 if prefix] if prefix else [name for name in files if not name.startswith("@")]
        return cls(prefix, membership_digest(names))

    def to_payload(self) -> dict[str, str]:
        return {"prefix": self.prefix, "members_sha256": self.members_sha256}


@dataclass(frozen=True)
class PreparedSource:
    source_id: str
    locator: str
    version: str
    data: bytes
    aliases: tuple[str, ...] = ()
    mode: int = 0o600

    def __post_init__(self) -> None:
        if (not isinstance(self.source_id, str) or re.fullmatch(r"[a-f0-9]{32}", self.source_id) is None
                or not isinstance(self.locator, str) or not PurePosixPath(self.locator).is_absolute()
                or "\x00" in self.locator or not _sha(self.version) or not isinstance(self.data, bytes)
                or hashlib.sha256(self.data).hexdigest() != self.version
                or type(self.mode) is not int or not 0 <= self.mode <= 0o777
                or not isinstance(self.aliases, tuple)
                or any(not isinstance(alias, str) or not 1 <= len(alias) <= 128 for alias in self.aliases)
                or len(set(self.aliases)) != len(self.aliases)):
            raise ValueError("A prepared source requires exact captured bytes, immutable version and explicit logical aliases.")

    def descriptor(self) -> dict[str, Any]:
        self.__post_init__()
        return {"source_id": self.source_id, "locator": self.locator, "version": self.version,
                "size": len(self.data), "aliases": list(self.aliases), "mode": self.mode}

    def to_storage_payload(self) -> dict[str, Any]:
        value = self.descriptor()
        value["data"] = self.data
        return value
