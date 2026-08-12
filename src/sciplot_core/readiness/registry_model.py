"""Represent and query a validated-envelope registry."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sciplot_core.readiness.constants import (
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
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
        if version not in {1, VALIDATED_ENVELOPE_REGISTRY_VERSION}:
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
        entries = tuple(self.entries)
        ids = [entry.rule_id for entry in entries]
        if len(set(ids)) != len(ids):
            raise ValueError("Validated-envelope rule IDs must be unique.")
        source = (
            _validate_legacy_source_acceptance(
                self.source_acceptance,
                entry_count=len(entries),
            )
            if version == 1
            else _validate_acceptance_lineage(
                self.source_acceptance,
                entry_ids=frozenset(ids),
            )
        )
        object.__setattr__(self, "source_acceptance", source)
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

    def acceptance_lineage_records(self) -> tuple[dict[str, Any], ...]:
        """Return truthful per-summary sources for either registry generation."""

        if self.version == VALIDATED_ENVELOPE_REGISTRY_VERSION:
            return tuple(deepcopy(self.source_acceptance["records"]))
        source = self.source_acceptance
        return (
            {
                "kind": source["kind"],
                "version": source["version"],
                "generated_at": source["generated_at"],
                "summary_sha256": source["summary_sha256"],
                "rule_ids": [entry.rule_id for entry in self.entries],
                "limitations": deepcopy(source["limitations"]),
            },
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


def _validate_acceptance_record(value: object, *, index: int) -> dict[str, Any]:
    label = f"source_acceptance records[{index}]"
    record = _closed_object(
        value,
        label=label,
        expected=frozenset(
            {
                "kind",
                "version",
                "generated_at",
                "summary_sha256",
                "rule_ids",
                "limitations",
            }
        ),
    )
    kind = _required_text(record["kind"], f"{label} kind")
    if kind != "sciplot_ready_rule_acceptance":
        raise ValueError(f"{label} kind is not supported.")
    version = _required_int(record["version"], f"{label} version", minimum=1)
    if version != READY_RULE_ACCEPTANCE_VERSION:
        raise ValueError(f"Unsupported {label} version {version}.")
    rule_ids = _text_list(
        record["rule_ids"],
        f"{label} rule_ids",
        maximum_items=512,
    )
    if not rule_ids or len(set(rule_ids)) != len(rule_ids):
        raise ValueError(f"{label} rule_ids must be non-empty and unique.")
    return {
        "kind": kind,
        "version": version,
        "generated_at": _timestamp(record["generated_at"], f"{label} generated_at"),
        "summary_sha256": _required_hash(
            record["summary_sha256"], f"{label} summary_sha256"
        ),
        "rule_ids": list(rule_ids),
        "limitations": list(
            _text_list(
                record["limitations"],
                f"{label} limitations",
                maximum_items=64,
                maximum_text=4096,
            )
        ),
    }


def _validate_acceptance_lineage(
    value: object,
    *,
    entry_ids: frozenset[str],
) -> dict[str, Any]:
    source = _closed_object(
        value,
        label="source_acceptance",
        expected=frozenset({"kind", "version", "records"}),
    )
    kind = _required_text(source["kind"], "source_acceptance kind")
    if kind != VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND:
        raise ValueError("source_acceptance kind is not supported.")
    version = _required_int(source["version"], "source_acceptance version", minimum=1)
    if version != VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION:
        raise ValueError(f"Unsupported source_acceptance version {version}.")
    raw_records = source["records"]
    if not isinstance(raw_records, list) or not raw_records or len(raw_records) > 512:
        raise ValueError("source_acceptance records must be a non-empty bounded list.")
    records = [
        _validate_acceptance_record(record, index=index)
        for index, record in enumerate(raw_records)
    ]
    recorded_ids: set[str] = set()
    for record in records:
        overlap = recorded_ids.intersection(record["rule_ids"])
        if overlap:
            raise ValueError(
                "source_acceptance records overlap: " + ", ".join(sorted(overlap))
            )
        recorded_ids.update(record["rule_ids"])
    if recorded_ids != entry_ids:
        missing = sorted(entry_ids - recorded_ids)
        extra = sorted(recorded_ids - entry_ids)
        raise ValueError(
            "source_acceptance records must partition registry entries "
            f"(missing={missing}, extra={extra})."
        )
    return {"kind": kind, "version": version, "records": records}


def _validate_legacy_source_acceptance(
    value: object,
    *,
    entry_count: int,
) -> dict[str, Any]:
    source = _closed_object(
        value,
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
    source["kind"] = _required_text(source["kind"], "source_acceptance kind")
    if source["kind"] != "sciplot_ready_rule_acceptance":
        raise ValueError("source_acceptance kind is not supported.")
    source["version"] = _required_int(
        source["version"], "source_acceptance version", minimum=1
    )
    if source["version"] != READY_RULE_ACCEPTANCE_VERSION:
        raise ValueError(f"Unsupported source_acceptance version {source['version']}.")
    source["generated_at"] = _timestamp(
        source["generated_at"], "source_acceptance generated_at"
    )
    source["summary_sha256"] = _required_hash(
        source["summary_sha256"], "source_acceptance summary_sha256"
    )
    for key in (
        "ready_rule_count",
        "lifecycle_passed_count",
        "physical_size_passed_count",
        "real_data_lifecycle_passed_count",
    ):
        source[key] = _required_int(source[key], f"source_acceptance {key}")
        if source[key] != entry_count:
            raise ValueError(f"source_acceptance {key} must equal the envelope count.")
    source["limitations"] = list(
        _text_list(
            source["limitations"],
            "source_acceptance limitations",
            maximum_items=64,
            maximum_text=4096,
        )
    )
    return source
