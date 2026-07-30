from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sciplot_core import assistant_operations, assisted_cleanup, readiness
from sciplot_core.assistant_provider import text_validation
from sciplot_core.data_mapping import contracts as data_mapping_contracts
from sciplot_core.foundation.iso_timestamps import (
    require_zoned_iso_timestamp,
    utc_now_iso,
)
from sciplot_core.mapping_contract import values
from sciplot_core.one_step import confidence as one_step_confidence
from sciplot_gui.studio_assistant_history import (
    validation as history_validation,
    values as history_values,
)


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
TIMESTAMP_OWNER = SOURCE_ROOT / "sciplot_core" / "foundation" / "iso_timestamps.py"


def test_contract_packages_share_one_timestamp_validator() -> None:
    assert text_validation._timestamp is require_zoned_iso_timestamp
    assert values._timestamp is require_zoned_iso_timestamp
    assert history_validation._timestamp is require_zoned_iso_timestamp
    assert readiness._timestamp("2026-07-28T12:30:00Z", "created_at") == (
        "2026-07-28T12:30:00Z"
    )
    assert text_validation._now is utc_now_iso
    assert values._now is utc_now_iso
    assert assistant_operations._now is utc_now_iso
    assert assisted_cleanup._timestamp is utc_now_iso
    assert data_mapping_contracts._now is utc_now_iso
    assert history_values._now is utc_now_iso
    assert one_step_confidence._now is utc_now_iso
    assert readiness._now is utc_now_iso


def test_first_party_contract_timestamp_implementation_has_one_owner() -> None:
    offenders: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if path == TIMESTAMP_OWNER:
            continue
        source = path.read_text(encoding="utf-8")
        if (
            "datetime.now(UTC).isoformat()" in source
            or "datetime.fromisoformat(" in source
        ):
            offenders.append(str(path.relative_to(SOURCE_ROOT)))

    assert offenders == []


def test_iso_timestamp_requires_an_explicit_timezone() -> None:
    assert require_zoned_iso_timestamp("2026-07-28T12:30:00Z", "created_at") == (
        "2026-07-28T12:30:00Z"
    )
    with pytest.raises(ValueError, match="timezone offset"):
        require_zoned_iso_timestamp("2026-07-28T12:30:00", "created_at")


def test_utc_now_iso_is_timezone_aware() -> None:
    parsed = datetime.fromisoformat(utc_now_iso())

    assert parsed.utcoffset() is not None
