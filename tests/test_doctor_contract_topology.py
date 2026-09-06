from __future__ import annotations

from sciplot_core.doctor import (
    _publication_foundation_available,
    _vsz_lifecycle_available,
    doctor_payload,
)


def test_doctor_finds_lifecycle_symbols_through_package_facades() -> None:
    assert _vsz_lifecycle_available()


def test_doctor_finds_publication_symbols_through_package_facades() -> None:
    assert _publication_foundation_available()


def test_doctor_lists_changed_owner_verification_before_broad_gates() -> None:
    routes = doctor_payload()["command_surface"]["developer_validation_routes"]

    assert routes == ["verify", "smoke", "acceptance", "batch"]


def test_doctor_exposes_readiness_evidence_scope() -> None:
    envelopes = doctor_payload()["validated_envelopes"]

    assert envelopes["evidence_scope"] == {
        "contract_freshness": "rule_declarations_and_render_request_policy",
        "implementation_freshness": "not_tracked_by_this_registry",
        "human_validation": "historical_owner_confirmation_without_build_binding",
    }
    assert envelopes["claims"]["current_implementation_certified"] is False
    assert envelopes["claims"]["human_validation_bound_to_current_build"] is False
