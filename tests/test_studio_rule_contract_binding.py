from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from sciplot_core.materials_rules import get_rule
from sciplot_core.readiness import (
    load_validated_envelope_registry,
    rule_contract_sha256,
    rule_semantic_contract_sha256,
)
from sciplot_core.studio_core import rule_readiness as readiness_module


def _ready_binding(rule_id: str = "swelling_curve") -> dict[str, Any]:
    rule = get_rule(rule_id)
    entry = load_validated_envelope_registry().entry(rule_id)
    assert entry is not None
    return {
        "kind": "sciplot_studio_rule_contract_binding",
        "version": 1,
        "rule_id": rule_id,
        "prepared_rule_contract_sha256": rule_contract_sha256(rule),
        "prepared_rule_semantic_contract_sha256": (rule_semantic_contract_sha256(rule)),
        "certification_status": "current",
        "certified_rule_contract_sha256": entry.contract_sha256,
        "certified_rule_semantic_contract_sha256": (entry.semantic_contract_sha256),
        "certification_reasons": [],
    }


def test_current_prepared_and_certified_contracts_are_publishable_and_pure() -> None:
    request = {
        "rule_id": "swelling_curve",
        "template": "point_line",
        "studio_rule_contract_binding": _ready_binding(),
    }
    original = deepcopy(request)

    readiness = readiness_module.resolve_studio_rule_publication_readiness(request)

    assert request == original
    assert readiness.publication_blocked is False
    assert readiness.pending_rule_review is False
    payload = readiness.to_payload()
    assert payload["version"] == 2
    assert payload["publication_blocked"] is False
    assert payload["blockers"] == []
    assert payload["rule_contract_evidence"]["status"] == "current"
    assert (
        payload["rule_contract_evidence"]["prepared"]
        == (request["studio_rule_contract_binding"])
    )
    assert (
        payload["rule_contract_evidence"]["current"]["certification_status"]
        == "current"
    )


def test_legacy_rule_bearing_request_requires_explicit_reprepare() -> None:
    readiness = readiness_module.resolve_studio_rule_publication_readiness(
        {
            "rule_id": "swelling_curve",
            "template": "point_line",
        }
    )

    assert readiness.pending_rule_review is False
    assert readiness.publication_blocked is True
    assert readiness.to_payload()["blockers"] == [
        "prepared_rule_contract_binding_missing"
    ]
    assert readiness.failure_reason == (
        "This rule-bearing Studio project has no prepare-time rule-contract "
        "binding. Reprepare it with the current certified rule before handoff."
    )


def test_ready_fixture_contract_drift_blocks_with_one_catalog_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_rule = get_rule("swelling_curve")
    drifted_rule = replace(
        base_rule,
        keywords=(*base_rule.keywords, "contract-drift-token"),
    )
    calls: list[str] = []

    def lookup(rule_id: str) -> Any:
        calls.append(rule_id)
        return drifted_rule

    monkeypatch.setattr(readiness_module, "get_rule", lookup)
    readiness = readiness_module.resolve_studio_rule_publication_readiness(
        {
            "rule_id": "swelling_curve",
            "studio_rule_contract_binding": _ready_binding(),
        }
    )

    assert calls == ["swelling_curve"]
    assert drifted_rule.fixture_status == "ready"
    assert readiness.pending_rule_review is False
    assert readiness.publication_blocked is True
    payload = readiness.to_payload()
    assert payload["blockers"] == [
        "current_rule_certification_stale",
        "prepared_rule_contract_binding_stale",
    ]
    assert payload["rule_contract_evidence"]["current"]["certification_reasons"] == [
        "certified_rule_contract_sha256_mismatch"
    ]


def test_missing_current_certification_is_a_structured_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_module,
        "load_validated_envelope_registry",
        lambda: SimpleNamespace(entry=lambda _rule_id: None),
        raising=False,
    )

    readiness = readiness_module.resolve_studio_rule_publication_readiness(
        {
            "rule_id": "swelling_curve",
            "studio_rule_contract_binding": _ready_binding(),
        }
    )

    assert readiness.publication_blocked is True
    assert readiness.to_payload()["blockers"] == [
        "current_rule_certification_missing",
        "prepared_rule_contract_binding_stale",
    ]
    assert readiness.failure_reason == (
        "Material rule `swelling_curve` has no validated-envelope certification "
        "for its current contract. Revalidate the central rule, then reprepare "
        "this Studio project before handoff."
    )


@pytest.mark.parametrize(
    "binding",
    [
        None,
        {},
        {
            **_ready_binding(),
            "prepared_rule_contract_sha256": "not-a-hash",
        },
        {
            **_ready_binding(),
            "prepared_rule_contract_sha256": _ready_binding()[
                "prepared_rule_contract_sha256"
            ].upper(),
        },
        {
            **_ready_binding(),
            "certification_status": "missing",
            "certified_rule_contract_sha256": None,
            "certified_rule_semantic_contract_sha256": None,
            "certification_reasons": [],
        },
        {
            **_ready_binding(),
            "unexpected": True,
        },
    ],
)
def test_malformed_rule_contract_binding_fails_closed(
    binding: object,
) -> None:
    with pytest.raises(ValueError, match="Studio rule-contract binding"):
        readiness_module.resolve_studio_rule_publication_readiness(
            {
                "rule_id": "swelling_curve",
                "studio_rule_contract_binding": binding,
            }
        )


def test_ruleless_request_rejects_stray_contract_binding_without_catalog_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        readiness_module,
        "get_rule",
        lambda rule_id: calls.append(rule_id),
    )

    with pytest.raises(
        ValueError,
        match="cannot carry a Studio rule-contract binding",
    ):
        readiness_module.resolve_studio_rule_publication_readiness(
            {"studio_rule_contract_binding": _ready_binding()}
        )

    assert calls == []
