"""Pytest session evidence in the same supported observer stream."""
import os
from typing import Any

from sciplot_core.verification.private_observer import current_observer

_parent_nodeid = os.environ.get("PYTEST_CURRENT_TEST", "")


def _record(value: dict[str, Any]) -> None:
    observer = current_observer()
    if observer is not None:
        observer.record({**value, "nested_session": bool(_parent_nodeid), "parent_nodeid": _parent_nodeid})


def _context(item: Any) -> None:
    observer = current_observer()
    if observer is not None:
        observer.nodeid = _parent_nodeid or item.nodeid


pytest_runtest_setup = _context
pytest_runtest_call = _context
pytest_runtest_teardown = _context


def pytest_collection_finish(session: Any) -> None:
    _record({"event": "pytest_collection", "nodeids": [item.nodeid for item in session.items]})


def pytest_runtest_logreport(report: Any) -> None:
    _record({"event": "pytest_report", "test_nodeid": report.nodeid,
             "phase": report.when, "outcome": report.outcome})


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    _record({"event": "pytest_session_finish", "exitstatus": int(exitstatus),
             "testsfailed": session.testsfailed, "testscollected": session.testscollected})
