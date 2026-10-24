"""Write one bounded completion marker from pytest's real sessionfinish hook."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sciplot_core.verification.evidence import atomic_json
from sciplot_core.verification.run_progress import PytestProgress

_passed: list[str] = []
_progress: PytestProgress | None = None


def pytest_sessionstart(session) -> None:
    global _progress
    _passed.clear()
    _progress = None


def pytest_collection_finish(session) -> None:
    global _progress
    destination = os.environ.get("SCIPLOT_VERIFY_FINISH")
    if destination:
        try:
            _progress = PytestProgress(Path(destination).parent, [item.nodeid for item in session.items])
        except Exception:
            _progress = None


def pytest_runtest_setup(item) -> None:
    if _progress is not None:
        _progress.event(item.nodeid, "setup")


def pytest_runtest_call(item) -> None:
    if _progress is not None:
        _progress.event(item.nodeid, "call")


def pytest_runtest_teardown(item) -> None:
    if _progress is not None:
        _progress.event(item.nodeid, "teardown")


def pytest_runtest_logreport(report) -> None:
    if report.when == "call" and report.passed:
        _passed.append(report.nodeid)
    if _progress is not None:
        _progress.event(report.nodeid, report.when, report.outcome)


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
    if _progress is not None:
        _progress.finish()
