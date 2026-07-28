from __future__ import annotations

from datetime import datetime

import pytest

from sciplot_core.assistant_provider import text_validation
from sciplot_core.foundation.iso_timestamps import (
    require_zoned_iso_timestamp,
    utc_now_iso,
)
from sciplot_core.mapping_contract import values


def test_contract_packages_share_one_timestamp_validator() -> None:
    assert text_validation._timestamp is require_zoned_iso_timestamp
    assert values._timestamp is require_zoned_iso_timestamp
    assert text_validation._now is utc_now_iso
    assert values._now is utc_now_iso


def test_iso_timestamp_requires_an_explicit_timezone() -> None:
    assert require_zoned_iso_timestamp("2026-07-28T12:30:00Z", "created_at") == (
        "2026-07-28T12:30:00Z"
    )
    with pytest.raises(ValueError, match="timezone offset"):
        require_zoned_iso_timestamp("2026-07-28T12:30:00", "created_at")


def test_utc_now_iso_is_timezone_aware() -> None:
    parsed = datetime.fromisoformat(utc_now_iso())

    assert parsed.utcoffset() is not None
