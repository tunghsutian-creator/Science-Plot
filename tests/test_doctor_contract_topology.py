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
