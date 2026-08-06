"""Validate managed Studio rule-readiness evidence for native status display."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


_READINESS_KIND = "sciplot_studio_rule_publication_readiness"
_V1_FIELDS = frozenset(
    {
        "kind",
        "version",
        "rule_id",
        "persisted_pending_rule_review",
        "current_rule_readiness",
        "pending_rule_review",
        "blockers",
    }
)
_V2_FIELDS = _V1_FIELDS | {"publication_blocked", "rule_contract_evidence"}
_V1_BLOCKERS = frozenset({"persisted_pending_rule_review", "current_rule_not_ready"})
_V2_BLOCKERS = _V1_BLOCKERS | {
    "current_rule_certification_missing",
    "current_rule_certification_stale",
    "prepared_rule_contract_binding_missing",
    "prepared_rule_contract_binding_stale",
}
_CONTRACT_FIELDS = frozenset({"status", "prepared", "current"})
_BINDING_FIELDS = frozenset(
    {
        "kind",
        "version",
        "rule_id",
        "prepared_rule_contract_sha256",
        "prepared_rule_semantic_contract_sha256",
        "certification_status",
        "certified_rule_contract_sha256",
        "certified_rule_semantic_contract_sha256",
        "certification_reasons",
    }
)
_CURRENT_FIELDS = frozenset(
    {
        "rule_id",
        "semantic_family",
        "current_rule_contract_sha256",
        "current_rule_semantic_contract_sha256",
        "certified_rule_contract_sha256",
        "certified_rule_semantic_contract_sha256",
        "certified_semantic_family",
        "certification_status",
        "certification_reasons",
    }
)
_CERTIFICATION_REASONS = (
    "validated_envelope_missing",
    "certified_rule_contract_sha256_mismatch",
    "certified_rule_semantic_contract_sha256_mismatch",
    "certified_semantic_family_mismatch",
)
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


def _object(value: object, fields: frozenset[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != fields:
        return None
    return value


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value or value.strip() != value:
        return None
    return value


def _hash(value: object) -> str | None:
    return value if isinstance(value, str) and _HASH_PATTERN.fullmatch(value) else None


def _optional_hash(value: object) -> bool:
    return value is None or _hash(value) is not None


def _reasons(value: object) -> list[str] | None:
    if not isinstance(value, list) or len(value) != len(set(value)):
        return None
    expected = [reason for reason in _CERTIFICATION_REASONS if reason in value]
    return list(value) if value == expected else None


def _binding(value: object, *, rule_id: str) -> dict[str, Any] | None:
    payload = _object(value, _BINDING_FIELDS)
    if payload is None:
        return None
    prepared_hash = _hash(payload["prepared_rule_contract_sha256"])
    prepared_semantic_hash = _hash(payload["prepared_rule_semantic_contract_sha256"])
    certified_hash = payload["certified_rule_contract_sha256"]
    certified_semantic_hash = payload["certified_rule_semantic_contract_sha256"]
    status = payload["certification_status"]
    reasons = _reasons(payload["certification_reasons"])
    if (
        payload["kind"] != "sciplot_studio_rule_contract_binding"
        or type(payload["version"]) is not int
        or payload["version"] != 1
        or payload["rule_id"] != rule_id
        or prepared_hash is None
        or prepared_semantic_hash is None
        or status not in {"current", "missing", "stale"}
        or not _optional_hash(certified_hash)
        or not _optional_hash(certified_semantic_hash)
        or reasons is None
    ):
        return None
    if status == "current":
        valid = (
            certified_hash == prepared_hash
            and certified_semantic_hash == prepared_semantic_hash
            and not reasons
        )
    elif status == "missing":
        valid = (
            certified_hash is None
            and certified_semantic_hash is None
            and reasons == ["validated_envelope_missing"]
        )
    else:
        if certified_hash is None or certified_semantic_hash is None:
            return None
        expected = []
        if certified_hash != prepared_hash:
            expected.append("certified_rule_contract_sha256_mismatch")
        if certified_semantic_hash != prepared_semantic_hash:
            expected.append("certified_rule_semantic_contract_sha256_mismatch")
        if "certified_semantic_family_mismatch" in reasons:
            expected.append("certified_semantic_family_mismatch")
        valid = bool(reasons) and reasons == expected
    return deepcopy(payload) if valid else None


def _current_contract(value: object, *, rule_id: str) -> dict[str, Any] | None:
    payload = _object(value, _CURRENT_FIELDS)
    if payload is None:
        return None
    current_hash = _hash(payload["current_rule_contract_sha256"])
    current_semantic_hash = _hash(payload["current_rule_semantic_contract_sha256"])
    certified_hash = payload["certified_rule_contract_sha256"]
    certified_semantic_hash = payload["certified_rule_semantic_contract_sha256"]
    family = _text(payload["semantic_family"])
    certified_family = payload["certified_semantic_family"]
    status = payload["certification_status"]
    reasons = _reasons(payload["certification_reasons"])
    if (
        payload["rule_id"] != rule_id
        or current_hash is None
        or current_semantic_hash is None
        or family is None
        or not _optional_hash(certified_hash)
        or not _optional_hash(certified_semantic_hash)
        or (certified_family is not None and _text(certified_family) is None)
        or status not in {"current", "missing", "stale"}
        or reasons is None
    ):
        return None
    if status == "current":
        valid = (
            certified_hash == current_hash
            and certified_semantic_hash == current_semantic_hash
            and certified_family == family
            and not reasons
        )
    elif status == "missing":
        valid = (
            certified_hash is None
            and certified_semantic_hash is None
            and certified_family is None
            and reasons == ["validated_envelope_missing"]
        )
    else:
        if (
            certified_hash is None
            or certified_semantic_hash is None
            or certified_family is None
        ):
            return None
        expected = []
        if certified_hash != current_hash:
            expected.append("certified_rule_contract_sha256_mismatch")
        if certified_semantic_hash != current_semantic_hash:
            expected.append("certified_rule_semantic_contract_sha256_mismatch")
        if certified_family != family:
            expected.append("certified_semantic_family_mismatch")
        valid = bool(reasons) and reasons == expected
    return deepcopy(payload) if valid else None


def _binding_matches_current(
    binding: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    return bool(
        binding["prepared_rule_contract_sha256"]
        == current["current_rule_contract_sha256"]
        and binding["prepared_rule_semantic_contract_sha256"]
        == current["current_rule_semantic_contract_sha256"]
        and binding["certification_status"] == current["certification_status"]
        and binding["certified_rule_contract_sha256"]
        == current["certified_rule_contract_sha256"]
        and binding["certified_rule_semantic_contract_sha256"]
        == current["certified_rule_semantic_contract_sha256"]
        and binding["certification_reasons"] == current["certification_reasons"]
    )


def _managed_rule_readiness(value: object) -> dict[str, Any] | None:
    """Return an isolated managed v1/v2 payload, or None when malformed."""

    if not isinstance(value, dict):
        return None
    version = value.get("version")
    if type(version) is not int or version not in {1, 2}:
        return None
    payload = _object(value, _V1_FIELDS if version == 1 else _V2_FIELDS)
    if payload is None or payload["kind"] != _READINESS_KIND:
        return None
    rule_id_value = payload["rule_id"]
    readiness_value = payload["current_rule_readiness"]
    rule_id = None if rule_id_value is None else _text(rule_id_value)
    readiness = None if readiness_value is None else _text(readiness_value)
    if (
        (rule_id_value is not None and rule_id is None)
        or (readiness_value is not None and readiness is None)
        or (rule_id is None) != (readiness is None)
        or type(payload["persisted_pending_rule_review"]) is not bool
        or type(payload["pending_rule_review"]) is not bool
    ):
        return None
    persisted = payload["persisted_pending_rule_review"]
    pending = bool(persisted or (rule_id is not None and readiness != "ready"))
    blockers_value = payload["blockers"]
    allowed = _V1_BLOCKERS if version == 1 else _V2_BLOCKERS
    if (
        payload["pending_rule_review"] is not pending
        or not isinstance(blockers_value, list)
        or len(blockers_value) != len(set(blockers_value))
        or any(blocker not in allowed for blocker in blockers_value)
    ):
        return None
    expected = []
    if persisted:
        expected.append("persisted_pending_rule_review")
    if rule_id is not None and readiness != "ready":
        expected.append("current_rule_not_ready")
    if version == 1:
        # A pre-binding rule-bearing "ready" receipt cannot establish current
        # contract freshness. Keep v1 pending and ruleless compatibility only.
        if rule_id is not None and not pending:
            return None
        return deepcopy(payload) if blockers_value == expected else None
    if type(payload["publication_blocked"]) is not bool:
        return None
    contract = _object(payload["rule_contract_evidence"], _CONTRACT_FIELDS)
    if contract is None:
        return None
    status = contract["status"]
    prepared_value = contract["prepared"]
    current_value = contract["current"]
    if rule_id is None:
        if (
            status != "not_applicable"
            or prepared_value is not None
            or current_value is not None
        ):
            return None
    else:
        current = _current_contract(current_value, rule_id=rule_id)
        prepared = (
            None
            if prepared_value is None
            else _binding(prepared_value, rule_id=rule_id)
        )
        if current is None or (prepared_value is not None and prepared is None):
            return None
        certification_status = current["certification_status"]
        if certification_status == "missing":
            expected.append("current_rule_certification_missing")
        elif certification_status == "stale":
            expected.append("current_rule_certification_stale")
        if prepared is None:
            expected.append("prepared_rule_contract_binding_missing")
        elif not _binding_matches_current(prepared, current):
            expected.append("prepared_rule_contract_binding_stale")
        contract_blocked = len(expected) > (int(persisted) + int(readiness != "ready"))
        if status != ("blocked" if contract_blocked else "current"):
            return None
    if blockers_value != expected or payload["publication_blocked"] is not bool(
        expected
    ):
        return None
    return deepcopy(payload)


__all__ = ["_managed_rule_readiness"]
