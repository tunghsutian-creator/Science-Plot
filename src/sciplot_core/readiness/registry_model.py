"""Represent and query a validated-envelope registry."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sciplot_core.readiness.constants import (
    VALIDATED_ENVELOPE_REGISTRY_KIND,
    VALIDATED_ENVELOPE_REGISTRY_VERSION,
    READY_RULE_ACCEPTANCE_VERSION,
)

from sciplot_core.readiness.validation import (
    _required_text,
    _required_int,
    _required_hash,
    _timestamp,
    _closed_object,
    _text_list,
)

from sciplot_core.readiness.envelope_model import (
    ValidatedRuleEnvelope,
)


@dataclass(frozen=True)
class ValidatedEnvelopeRegistry:
    generated_at: str
    source_acceptance: dict[str, Any]
    entries: tuple[ValidatedRuleEnvelope, ...]
    limitations: tuple[str, ...]
    kind: str = VALIDATED_ENVELOPE_REGISTRY_KIND
    version: int = VALIDATED_ENVELOPE_REGISTRY_VERSION

    def __post_init__(self) -> None:
        kind = _required_text(self.kind, "registry kind")
        if kind != VALIDATED_ENVELOPE_REGISTRY_KIND:
            raise ValueError("Not a SciPlot validated-envelope registry.")
        version = _required_int(self.version, "registry version", minimum=1)
        if version != VALIDATED_ENVELOPE_REGISTRY_VERSION:
            raise ValueError(
                f"Unsupported validated-envelope registry version {version}."
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "version", version)
        object.__setattr__(
            self,
            "generated_at",
            _timestamp(self.generated_at, "registry generated_at"),
        )
        source = _closed_object(
            self.source_acceptance,
            label="source_acceptance",
            expected=frozenset(
                {
                    "kind",
                    "version",
                    "generated_at",
                    "summary_sha256",
                    "ready_rule_count",
                    "lifecycle_passed_count",
                    "physical_size_passed_count",
                    "real_data_lifecycle_passed_count",
                    "limitations",
                }
            ),
        )
        source["kind"] = _required_text(
            source["kind"],
            "source_acceptance kind",
        )
        if source["kind"] != "sciplot_ready_rule_acceptance":
            raise ValueError("source_acceptance kind is not supported.")
        source["version"] = _required_int(
            source["version"],
            "source_acceptance version",
            minimum=1,
        )
        if source["version"] != READY_RULE_ACCEPTANCE_VERSION:
            raise ValueError(
                "Unsupported source_acceptance version "
                f"{source['version']}; expected {READY_RULE_ACCEPTANCE_VERSION}."
            )
        source["generated_at"] = _timestamp(
            source["generated_at"],
            "source_acceptance generated_at",
        )
        source["summary_sha256"] = _required_hash(
            source["summary_sha256"],
            "source_acceptance summary_sha256",
        )
        for key in (
            "ready_rule_count",
            "lifecycle_passed_count",
            "physical_size_passed_count",
            "real_data_lifecycle_passed_count",
        ):
            source[key] = _required_int(source[key], f"source_acceptance {key}")
        source["limitations"] = list(
            _text_list(
                source["limitations"],
                "source_acceptance limitations",
                maximum_items=64,
                maximum_text=4096,
            )
        )
        object.__setattr__(self, "source_acceptance", source)
        entries = tuple(self.entries)
        ids = [entry.rule_id for entry in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("Validated-envelope rule IDs must be unique.")
        for key in (
            "ready_rule_count",
            "lifecycle_passed_count",
            "physical_size_passed_count",
            "real_data_lifecycle_passed_count",
        ):
            if source[key] != len(entries):
                raise ValueError(
                    f"source_acceptance {key} must equal the envelope count."
                )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda item: item.rule_id)),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(
                _required_text(value, "registry limitation", maximum=4096)
                for value in self.limitations
            ),
        )

    def entry(self, rule_id: str) -> ValidatedRuleEnvelope | None:
        return next(
            (entry for entry in self.entries if entry.rule_id == rule_id),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "version": self.version,
            "generated_at": self.generated_at,
            "source_acceptance": deepcopy(self.source_acceptance),
            "entries": [entry.to_dict() for entry in self.entries],
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: object) -> ValidatedEnvelopeRegistry:
        parsed = _closed_object(
            payload,
            label="validated-envelope registry",
            expected=frozenset(
                {
                    "kind",
                    "version",
                    "generated_at",
                    "source_acceptance",
                    "entries",
                    "limitations",
                }
            ),
        )
        if not isinstance(parsed["entries"], list):
            raise ValueError("validated-envelope entries must be a list.")
        if len(parsed["entries"]) > 512:
            raise ValueError("validated-envelope registry is too large.")
        return cls(
            kind=parsed["kind"],
            version=parsed["version"],
            generated_at=parsed["generated_at"],
            source_acceptance=parsed["source_acceptance"],
            entries=tuple(
                ValidatedRuleEnvelope.from_dict(entry) for entry in parsed["entries"]
            ),
            limitations=_text_list(
                parsed["limitations"],
                "registry limitations",
                maximum_items=64,
                maximum_text=4096,
            ),
        )
