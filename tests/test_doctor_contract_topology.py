from __future__ import annotations

from sciplot_core.doctor import (
    _publication_foundation_available,
    _vsz_lifecycle_available,
)


def test_doctor_finds_lifecycle_symbols_through_package_facades() -> None:
    assert _vsz_lifecycle_available()


def test_doctor_finds_publication_symbols_through_package_facades() -> None:
    assert _publication_foundation_available()
