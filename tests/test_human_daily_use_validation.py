from __future__ import annotations

import json

import pytest

from sciplot_core.readiness.human_validation import (
    load_human_daily_use_validation,
)
from sciplot_core.readiness.status import validated_envelope_status


def test_owner_validation_drives_daily_use_readiness_claims() -> None:
    validation = load_human_daily_use_validation()
    status = validated_envelope_status()

    assert validation["status"] == "passed"
    assert validation["confirmed_by"] == "project_owner"
    assert status["human_daily_use_validation"] == validation
    assert status["claims"]["human_daily_use_cutover_established"] is True
    assert status["claims"]["human_daily_use_validation_established"] is True
    assert status["claims"]["journal_compliance_established"] is False


def test_daily_use_validation_requires_complete_owner_scope(tmp_path) -> None:
    payload = load_human_daily_use_validation()
    payload["scope"] = ["veusz_first_daily_use"]
    path = tmp_path / "incomplete_daily_use_validation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="scope is incomplete"):
        load_human_daily_use_validation(path)
