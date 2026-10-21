"""Write one bounded completion marker from pytest's real sessionfinish hook."""
from __future__ import annotations

import json
import os
import sys
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
    complete = True
    policy = os.environ.get("SCIPLOT_VERIFY_QT_MODULES")
    if policy:
        try:
            allowed = json.loads(policy)
            complete = isinstance(allowed, list) and all(isinstance(name, str) for name in allowed) and all(
                name.split(".")[1] in allowed for name in sys.modules if name.startswith("PyQt6.")
            )
        except (ValueError, TypeError):
            complete = False
    if destination:
        atomic_json(Path(destination), {
            "complete": complete, "exit_code": int(exitstatus),
            "selected_tests": [item.nodeid for item in session.items],
            "executed_tests": list(_passed),
        })
