from __future__ import annotations

import json

import pytest

from sciplot_core.cli.value_io import _cli_runtime_error_payload


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("Input not found: missing.csv"),
        OSError("source read failed"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte"),
        json.JSONDecodeError("invalid JSON", "{", 1),
        ValueError("unsupported rule"),
    ],
)
def test_cli_runtime_error_payload_classifies_expected_failures(
    exc: Exception,
) -> None:
    payload = _cli_runtime_error_payload(exc)

    assert payload == {
        "kind": "sciplot_cli_runtime_error",
        "version": 1,
        "status": "failed",
        "category": "expected_runtime_failure",
        "reason_code": "cli_expected_runtime_failure",
        "exception_type": type(exc).__name__,
        "message": str(exc),
    }


@pytest.mark.parametrize(
    "exc",
    [AssertionError("invariant failed"), KeyError("missing"), TypeError("bad type")],
)
def test_cli_runtime_error_payload_classifies_internal_errors(
    exc: Exception,
) -> None:
    payload = _cli_runtime_error_payload(exc)

    assert payload["category"] == "internal_error"
    assert payload["reason_code"] == "cli_internal_error"
    assert payload["exception_type"] == type(exc).__name__
    assert payload["message"] == str(exc)
    assert "recovery_hint" not in payload


def test_cli_runtime_error_payload_includes_only_nonempty_recovery_hint() -> None:
    without_hint = _cli_runtime_error_payload(ValueError())
    with_hint = _cli_runtime_error_payload(
        ValueError("unrecognized table"),
        recovery_hint="Inspect the input table.",
    )

    assert without_hint["message"] == "ValueError"
    assert "recovery_hint" not in without_hint
    assert with_hint["recovery_hint"] == "Inspect the input table."
