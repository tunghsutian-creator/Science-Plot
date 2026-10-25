"""Pure, closed command identity and resource preconditions; no file discovery."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256

from .resources import (NativeAdoption as NativeAdoption, ProjectionRead as ProjectionRead,
                        MembershipRead as MembershipRead, PreparedSource as PreparedSource, _identity, _sha, resource_key)
from .resources import PreparedFile as PreparedFile
from .resources import SourceAdoption as SourceAdoption
from .resources import NamespaceMember as NamespaceMember, NamespaceTransfer as NamespaceTransfer


class CommandKind(StrEnum):
    CREATE = "create"
    DOCUMENT_EDIT = "document_edit"
    SOURCE_UPDATE = "source_update"
    FIGURE_SET = "figure_set"
    STYLE = "style"
    NATIVE_PATCH = "native_patch"
    NATIVE_CREATE = "native_create"
    NATIVE_EXPORT = "native_export"
    NATIVE_IMPORT = "native_import"
    EXPORT = "export"
    SAVE = "save"
    PUBLISH = "publish"
    UNDO = "undo"
    REDO = "redo"
    SEMANTIC_RECORD = "semantic_record"
    ATTACHMENT_IMPORT = "attachment_import"












@dataclass(frozen=True)
class ProjectCommand:
    kind: CommandKind
    key: str
    project_id: str
    expected_generation: str | None
    read_set: tuple[tuple[str, str | None], ...]
    write_set: tuple[str, ...]
    request_json: str
    expected_revision: str | int | None = None
    projected_reads: tuple[ProjectionRead, ...] = ()
    projected_writes: tuple[ProjectionRead, ...] = ()
    native_adoptions: tuple[NativeAdoption, ...] = ()
    read_memberships: tuple[MembershipRead, ...] = ()
    source_adoptions: tuple[SourceAdoption, ...] = ()
    namespace_transfers: tuple[NamespaceTransfer, ...] = ()

    def __post_init__(self) -> None:
        if (not isinstance(self.kind, CommandKind) or not isinstance(self.key, str) or not 1 <= len(self.key) <= 128
                or not _identity(self.project_id)
                or self.expected_generation is not None and not _identity(self.expected_generation)
                or self.expected_revision is not None and (type(self.expected_revision) not in {str, int}
                    or isinstance(self.expected_revision, str) and not self.expected_revision
                    or type(self.expected_revision) is int and self.expected_revision < 0)):
            raise ValueError("A command requires valid project, kind, key and revision identities.")
        reads = dict(self.read_set)
        if len(reads) != len(self.read_set) or len(set(self.write_set)) != len(self.write_set):
            raise ValueError("A command cannot declare a resource twice.")
        for name, digest in self.read_set:
            resource_key(name)
            if digest is not None and not _sha(digest):
                raise ValueError("A read precondition must be an exact SHA256 or explicit absence.")
        for name in self.write_set:
            resource_key(name)
        if any(not isinstance(item, ProjectionRead) for item in (*self.projected_reads, *self.projected_writes)):
            raise ValueError("Projected preconditions must be typed values.")
        projected_targets = {item.resource for item in self.projected_writes}
        if not set(self.write_set).issubset(set(reads) | projected_targets):
            raise ValueError("Every write must bind its previous bytes or explicit absence.")
        selectors = [(item.resource, item.kind, item.key) for item in self.projected_reads]
        if len(set(selectors)) != len(selectors):
            raise ValueError("Projected read selectors must be typed and unique.")
        if (any(item not in self.projected_reads for item in self.projected_writes)
                or len(set(self.projected_writes)) != len(self.projected_writes)
                or not projected_targets.issubset(self.write_set)):
            raise ValueError("Projected writes require unique, identical selected read guards and a declared write.")
        if (any(not isinstance(item, NativeAdoption) for item in self.native_adoptions)
                or bool(self.native_adoptions) != (self.kind == CommandKind.NATIVE_IMPORT)):
            raise ValueError("Only explicit native import may admit domain-audited saved VSZ bytes.")
        adopted = [item.resource for item in self.native_adoptions]
        if len(set(adopted)) != len(adopted) or not set(adopted).issubset(self.write_set):
            raise ValueError("Every native adoption must name one unique declared write.")
        if any(reads.get(item.resource) != item.before_sha256 for item in self.native_adoptions):
            raise ValueError("Native import must still bind its exact prior stored revision.")
        if (any(not isinstance(item, MembershipRead) for item in self.read_memberships)
                or len({item.prefix for item in self.read_memberships}) != len(self.read_memberships)):
            raise ValueError("Membership witnesses must be typed and unique per namespace.")
        if (any(not isinstance(item, SourceAdoption) for item in self.source_adoptions)
                or self.source_adoptions and self.kind not in {CommandKind.SOURCE_UPDATE, CommandKind.SEMANTIC_RECORD}):
            raise ValueError("Only an admitted scientific source update can register changed raw observations.")
        observed = [item.resource for item in self.source_adoptions]
        if (len(set(observed)) != len(observed)
                or any(item.resource in self.write_set or reads.get(item.resource) != item.before_sha256
                       for item in self.source_adoptions)):
            raise ValueError("Raw source observations bind prior reads and cannot become output writes.")
        if (any(not isinstance(item, NamespaceTransfer) for item in self.namespace_transfers)
                or len(self.namespace_transfers) > 1
                or self.namespace_transfers and self.kind != CommandKind.ATTACHMENT_IMPORT):
            raise ValueError("Only one explicit attachment import may transfer an exact old namespace.")
        for transfer in self.namespace_transfers:
            guards = {item.prefix: item for item in self.read_memberships}
            if (reads.get(transfer.prefix + "/head.json") is None
                    or transfer.prefix not in guards or transfer.history_prefix not in guards
                    or guards[transfer.history_prefix].members_sha256 != MembershipRead.capture({}, transfer.history_prefix).members_sha256
                    or not {transfer.prefix + "/head.json", transfer.prefix + "/.sciplot_semantic_owner.json",
                            transfer.history_prefix + "/.sciplot_semantic_owner.json"}.issubset(self.write_set)):
                raise ValueError("An ownership transfer must bind the original head, both member sets and its exact shell writes.")
        request = json.loads(self.request_json)
        if not isinstance(request, dict) or "idempotency_key" in request and request["idempotency_key"] != self.key:
            raise ValueError("The original request must agree with its command key.")
        canonical_json_sha256(request, allow_nan=False)

    @classmethod
    def create(cls, kind: CommandKind | str, key: str, *, project_id: str,
               expected_generation: str | None, read_set: Mapping[str, str | None],
               write_set: Sequence[str], request: dict[str, Any],
               expected_revision: str | int | None = None,
               projected_reads: Sequence[ProjectionRead] = (),
               projected_writes: Sequence[ProjectionRead] = (),
               native_adoptions: Sequence[NativeAdoption] = (),
               read_memberships: Sequence[MembershipRead] = (),
               source_adoptions: Sequence[SourceAdoption] = (),
               namespace_transfers: Sequence[NamespaceTransfer] = ()) -> ProjectCommand:
        return cls(CommandKind(kind), key, project_id, expected_generation,
                   tuple(sorted(read_set.items())), tuple(sorted(write_set)),
                   json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False),
                   expected_revision,
                   tuple(sorted(projected_reads, key=lambda item: (item.resource, item.kind, item.key))),
                   tuple(sorted(projected_writes, key=lambda item: (item.resource, item.kind, item.key))),
                   tuple(sorted(native_adoptions, key=lambda item: item.resource)),
                   tuple(sorted(read_memberships, key=lambda item: item.prefix)),
                   tuple(sorted(source_adoptions, key=lambda item: item.resource)),
                   tuple(sorted(namespace_transfers, key=lambda item: item.prefix)))

    @classmethod
    def from_payload(cls, value: Any) -> ProjectCommand:
        keys = {"version", "kind", "key", "project_id", "expected_generation", "expected_revision",
                "read_set", "write_set", "projected_reads", "projected_writes", "native_adoptions", "read_memberships", "source_adoptions", "namespace_transfers", "request"}
        if (not isinstance(value, dict) or set(value) != keys or type(value.get("version")) is not int
                or value["version"] != 1 or not isinstance(value["read_set"], dict)
                or not isinstance(value["write_set"], list) or not isinstance(value["request"], dict)):
            raise ValueError("A saved command must satisfy its exact versioned contract.")

        def selectors(name: str) -> list[ProjectionRead]:
            items = value[name]
            if not isinstance(items, list):
                raise ValueError("Saved projected guards must be an explicit list.")
            result = []
            for item in items:
                if not isinstance(item, dict) or set(item) != {"resource", "kind", "key", "sha256"}:
                    raise ValueError("A saved projected guard has an unknown or missing field.")
                result.append(ProjectionRead(item["resource"], item["kind"], item["key"], item["sha256"]))
            return result

        adoption_items = value["native_adoptions"]
        if not isinstance(adoption_items, list) or any(not isinstance(item, dict) or set(item) != {
                "resource", "before_sha256", "observed_sha256", "audit_sha256"} for item in adoption_items):
            raise ValueError("Saved native adoptions require exact closed fields.")
        adoptions = [NativeAdoption(item["resource"], item["before_sha256"], item["observed_sha256"],
                                    item["audit_sha256"]) for item in adoption_items]
        membership_items = value["read_memberships"]
        if not isinstance(membership_items, list) or any(not isinstance(item, dict) or set(item) != {
                "prefix", "members_sha256"} for item in membership_items):
            raise ValueError("Saved membership witnesses require exact closed fields.")
        memberships = [MembershipRead(item["prefix"], item["members_sha256"]) for item in membership_items]
        source_items = value["source_adoptions"]
        if not isinstance(source_items, list) or any(not isinstance(item, dict) or set(item) != {
                "resource", "source_id", "before_sha256", "observed_sha256"} for item in source_items):
            raise ValueError("Saved source observations require exact closed fields.")
        observations = [SourceAdoption(item["resource"], item["source_id"], item["before_sha256"],
                                       item["observed_sha256"]) for item in source_items]
        transfer_items = value["namespace_transfers"]
        if not isinstance(transfer_items, list) or any(not isinstance(item, dict) or set(item) != {
                "prefix", "history_prefix", "attachment_id", "original_head_sha256", "refusal_sha256",
                "owner_sha256", "history_owner_sha256", "members", "physical_backup_prefix"} for item in transfer_items):
            raise ValueError("Saved namespace transfers require exact closed fields.")
        transfers = []
        for item in transfer_items:
            members = item["members"]
            if not isinstance(members, list) or any(not isinstance(member, dict) or set(member) != {
                    "relative", "sha256", "size", "mode"} for member in members):
                raise ValueError("Saved observed namespace members require exact closed fields.")
            transfers.append(NamespaceTransfer(**{**item, "members": tuple(NamespaceMember(**member) for member in members)}))
        return cls.create(value["kind"], value["key"], project_id=value["project_id"],
                          expected_generation=value["expected_generation"], read_set=value["read_set"],
                          write_set=value["write_set"], request=value["request"],
                          expected_revision=value["expected_revision"], projected_reads=selectors("projected_reads"),
                          projected_writes=selectors("projected_writes"), native_adoptions=adoptions,
                          read_memberships=memberships, source_adoptions=observations, namespace_transfers=transfers)

    def to_payload(self) -> dict[str, Any]:
        self.__post_init__()
        return {"version": 1, "kind": self.kind.value, "key": self.key, "project_id": self.project_id,
                "expected_generation": self.expected_generation, "expected_revision": self.expected_revision,
                "read_set": dict(self.read_set), "write_set": list(self.write_set),
                "projected_reads": [item.to_payload() for item in self.projected_reads],
                "projected_writes": [item.to_payload() for item in self.projected_writes],
                "native_adoptions": [item.to_payload() for item in self.native_adoptions],
                "read_memberships": [item.to_payload() for item in self.read_memberships],
                "source_adoptions": [item.to_payload() for item in self.source_adoptions],
                "namespace_transfers": [item.to_payload() for item in self.namespace_transfers],
                "request": json.loads(self.request_json)}

    @property
    def command_digest(self) -> str:
        return canonical_json_sha256(self.to_payload(), allow_nan=False)


@dataclass(frozen=True)
class ProjectMutation:
    writes: Mapping[str, bytes | Path | PreparedFile | None]
    result: dict[str, Any]
    sources: Sequence[dict[str, Any]] | None = None
    review: dict[str, Any] | None = None
    artifacts: Mapping[str, bytes | Path | PreparedFile] = field(default_factory=dict)
    prepared_sources: tuple[PreparedSource, ...] = ()

    @property
    def prepared_digest(self) -> str:
        """Bind already prepared bytes; never read a path or invoke an executor."""
        if self.sources is not None or any(isinstance(item, Path) for item in (*self.writes.values(), *self.artifacts.values())):
            raise ValueError("Prepared storage publication requires byte values and no deferred source capture.")

        def entries(values: Mapping[str, bytes | Path | PreparedFile | None]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for name, value in values.items():
                if value is None:
                    result[name] = None
                elif isinstance(value, bytes):
                    result[name] = {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value), "mode": 0o600}
                elif isinstance(value, PreparedFile):
                    result[name] = value.descriptor()
                else:
                    raise ValueError("Prepared storage publication cannot resolve external IO.")
            return result

        return canonical_json_sha256({"writes": entries(self.writes), "artifacts": entries(self.artifacts),
                                      "result": self.result, "review": self.review,
                                      "sources": [source.descriptor() for source in self.prepared_sources]}, allow_nan=False)

    def validate_for(self, command: ProjectCommand) -> None:
        if set(self.writes) != set(command.write_set):
            raise ValueError("A candidate must contain exactly its admitted writes and deletions.")
        for name, value in self.writes.items():
            resource_key(name)
            if value is not None and not isinstance(value, (bytes, Path, PreparedFile)):
                raise ValueError("Candidate content must be bytes, a staged file, or an explicit deletion.")
            if isinstance(value, PreparedFile):
                value.__post_init__()
        for name, value in self.artifacts.items():
            resource_key(name)
            if not isinstance(value, (bytes, Path, PreparedFile)):
                raise ValueError("Review artifacts must be bytes or staged files.")
            if isinstance(value, PreparedFile):
                value.__post_init__()
        if not isinstance(self.result, dict) or self.review is not None and not isinstance(self.review, dict):
            raise ValueError("Candidate result and review must be JSON objects.")
        canonical_json_sha256(self.result, allow_nan=False)
        if self.review is not None:
            canonical_json_sha256(self.review, allow_nan=False)
        if self.sources is not None:
            canonical_json_sha256(list(self.sources), allow_nan=False)
        for source in self.prepared_sources:
            if not isinstance(source, PreparedSource):
                raise ValueError("Prepared sources must be explicit captured values.")
            source.__post_init__()
        declarations = [*self.sources] if self.sources is not None else []
        declarations.extend(source.to_storage_payload() for source in self.prepared_sources)
        for observed in command.source_adoptions:
            if not any(item.get("source_id") == observed.source_id and item.get("version") == observed.observed_sha256
                       for item in declarations):
                raise ValueError("A new raw observation must have its exact declared source version.")
