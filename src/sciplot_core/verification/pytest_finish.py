"""Write one bounded completion marker from pytest's real sessionfinish hook."""
from __future__ import annotations

import os
from pathlib import Path

from sciplot_core.verification.evidence import atomic_json

_passed: list[str] = []


def pytest_sessionstart(session) -> None:
    _passed.clear()


def pytest_runtest_logreport(report) -> None:
    if report.when == "call" and report.passed:
        _passed.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus) -> None:
    destination = os.environ.get("SCIPLOT_VERIFY_FINISH")
    if destination:
        atomic_json(Path(destination), {
            "complete": True, "exit_code": int(exitstatus),
            "selected_tests": [item.nodeid for item in session.items],
            "executed_tests": list(_passed),
        })
