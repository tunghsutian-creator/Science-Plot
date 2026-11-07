"""Renderer-independent authority, command, version and outcome values."""
from dataclasses import asdict, dataclass
from enum import StrEnum
import re
from typing import Any, cast

from sciplot_core.plot_document.requests import PatchRequest, RequestBody


class AuthorityMode(StrEnum):
    MANAGED = "managed"
    LEGACY_NATIVE = "legacy_native"

    @classmethod
    def of(cls, document: dict[str, Any]) -> "AuthorityMode":
        tag = document.get("plot_type")
        if tag == "ManagedPlot":
            return cls.MANAGED
        if tag == "LegacyPlot":
            return cls.LEGACY_NATIVE
        if "plot_type" not in document:
            # The historical model deliberately omitted this tag. Validate that
            # exact old model and shadow coverage without modifying its payload.
            from sciplot_core.plot_document import validate_document

            legacy = validate_document(document)
            if legacy["coverage"]["mode"] == "legacy_shadow":
                return cls.LEGACY_NATIVE
        raise ValueError("Unknown or unrepresented document authority.")


@dataclass(frozen=True)
class RevisionToken:
    plot_id: str
    authority: AuthorityMode
    revision: int
    scientific_hash: str
    presentation_hash: str

    def __post_init__(self) -> None:
        if (not isinstance(self.plot_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.plot_id) is None
                or not isinstance(self.authority, AuthorityMode)
                or type(self.revision) is not int or self.revision < 0
                or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
                       for value in (self.scientific_hash, self.presentation_hash))):
            raise ValueError("A revision token requires a valid identity, authority, revision and content hashes.")

    @classmethod
    def of(cls, document: dict[str, Any]) -> "RevisionToken":
        return cls(document["plot_id"], AuthorityMode.of(document), document["revision"],
                   document["scientific_hash"], document["presentation_hash"])

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedCommand:
    kind: str
    idempotency_key: str
    original_request: RequestBody | PatchRequest | dict[str, Any]
    request_digest: str
    business_request: RequestBody | PatchRequest | dict[str, Any]
    original_request_digest: str
    expected_revision: RevisionToken | None
    authority: AuthorityMode

    def __post_init__(self) -> None:
        original = self._body(self.original_request)
        business = original if self.business_request is self.original_request else self._body(self.business_request)
        if (not isinstance(self.kind, str) or self.kind not in {"create", "patch", "intent", "rollback", "reimport", "export"}
                or not isinstance(self.authority, AuthorityMode)
                or not isinstance(self.idempotency_key, str) or not 1 <= len(self.idempotency_key) <= 128
                or original.to_payload().get("idempotency_key") != self.idempotency_key
                or business.to_payload().get("idempotency_key") != self.idempotency_key
                or original.digest != self.original_request_digest or business.digest != self.request_digest
                or self.expected_revision is not None and not isinstance(self.expected_revision, RevisionToken)):
            raise ValueError("The normalized command kind, identity, digest or authority is invalid.")
        if self.expected_revision is not None and self.expected_revision.authority != self.authority:
            raise ValueError("Command and expected revision authorities disagree.")
        if self.kind == "create":
            if self.expected_revision is not None:
                raise ValueError("A creation command has no previous revision.")
        elif self.expected_revision is None:
            raise ValueError("A mutation command requires its tagged expected revision.")
        object.__setattr__(self, "original_request", original)
        object.__setattr__(self, "business_request", business)

    @staticmethod
    def _body(value: RequestBody | PatchRequest | dict[str, Any]) -> RequestBody | PatchRequest:
        return (cast(RequestBody | PatchRequest, value) if type(value) in {RequestBody, PatchRequest}
                else RequestBody(cast(dict[str, Any], value)))

    @classmethod
    def create(cls, kind: str, request: RequestBody | PatchRequest | dict[str, Any], *, expected_revision: RevisionToken | None = None,
               authority: AuthorityMode = AuthorityMode.LEGACY_NATIVE,
               business_request: RequestBody | PatchRequest | dict[str, Any] | None = None) -> "NormalizedCommand":
        original = cls._body(request)
        key = original.to_payload().get("idempotency_key")
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise ValueError("Use a stable non-empty idempotency key of at most 128 characters.")
        business = original if business_request is None or business_request is request else cls._body(business_request)
        return cls(kind, key, original, business.digest, business,
                   original.digest, expected_revision,
                   expected_revision.authority if expected_revision else authority)

    @property
    def original_payload(self) -> dict[str, Any]:
        return cast(RequestBody | PatchRequest, self.original_request).to_payload()

    @property
    def business_payload(self) -> dict[str, Any]:
        return cast(RequestBody | PatchRequest, self.business_request).to_payload()

    def to_payload(self) -> dict[str, Any]:
        return {"version": 1, "kind": self.kind, "idempotency_key": self.idempotency_key,
                "original_request": self.original_payload, "original_request_digest": self.original_request_digest,
                "business_request": self.business_payload, "request_digest": self.request_digest,
                "expected_revision": self.expected_revision.to_payload() if self.expected_revision else None,
                "authority": self.authority.value}


@dataclass(frozen=True)
class RecoveryState:
    phase: str
    committed: bool
    export_complete: bool
    outcome: str
    blocked: bool = False

    @classmethod
    def of(cls, transaction: dict[str, Any]) -> "RecoveryState":
        phase = transaction["phase"]
        committed = phase in {"committed", "exporting", "export_pending", "complete"}
        outcome = ("complete" if phase == "complete" else "rejected" if phase == "rejected"
                   else "native_outcome_requires_owner_validation" if phase == "applying"
                   else "export_only" if committed else "pending")
        return cls(phase, committed, phase == "complete", outcome,
                   bool(transaction.get("error")) and phase not in {"complete", "needs_review", "rejected"})

    def to_payload(self) -> dict[str, Any]:
        status = {"complete": "complete", "needs_review": "needs_review", "rejected": "rejected"}.get(self.phase, "pending")
        return {"status": "blocked" if self.blocked else status, "commit_status": "committed" if self.committed else "pending",
                "export_status": "complete" if self.export_complete else "pending"}


@dataclass(frozen=True)
class Receipt:
    revision: RevisionToken
    recovery: RecoveryState
    command_digest: str | None

    @classmethod
    def of(cls, transaction: dict[str, Any]) -> "Receipt":
        command = transaction.get("normalized_command", {})
        # Historical request_hash may identify a generated inverse/native request,
        # so it cannot certify the canonical business command digest.
        return cls(RevisionToken.of(transaction["document"]), RecoveryState.of(transaction),
                   command.get("request_digest"))

    def to_payload(self) -> dict[str, Any]:
        return {"plot_id": self.revision.plot_id, "revision": self.revision.revision,
                "plot_type": "ManagedPlot" if self.revision.authority == AuthorityMode.MANAGED else "LegacyPlot",
                "scientific_hash": self.revision.scientific_hash, "presentation_hash": self.revision.presentation_hash,
                **self.recovery.to_payload(), "command_digest": self.command_digest}
