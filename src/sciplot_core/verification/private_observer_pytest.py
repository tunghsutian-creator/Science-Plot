"""Pytest session evidence in the same supported observer stream."""
import os
from typing import Any, Callable, Iterator
import pytest

from sciplot_core.verification.private_observer import current_observer
from sciplot_core.verification.private_exclusion_boundary import bind_collection, begin_phase, end_phase
from sciplot_core.verification.private_audit_runtime import start_node, finish_node
from sciplot_core.verification.private_native_exit_port import start_port, close_port

_parent_nodeid = os.environ.get("PYTEST_CURRENT_TEST", "")


def _record(value: dict[str, Any]) -> None:
    observer = current_observer()
    if observer is not None:
        observer.record({**value, "nested_session": bool(_parent_nodeid), "parent_nodeid": _parent_nodeid})


def _phase(item: Any, phase: str) -> Iterator[None]:
    observer = current_observer()
    if observer is not None:
        if phase == "setup":
            start_node(observer, item)
        begin_phase(observer, item, phase)
    try:
        yield
    finally:
        if observer is not None:
            try:
                if phase == "teardown":
                    finish_node(observer, item)
            finally:
                end_phase(observer, item, phase)


def _wrapper(function: Callable[[Any], Iterator[None]]) -> Callable[[Any], Iterator[None]]:
    return pytest.hookimpl(hookwrapper=True, tryfirst=True)(function)


@_wrapper
def pytest_runtest_setup(item: Any) -> Iterator[None]:
    yield from _phase(item, "setup")


@_wrapper
def pytest_runtest_call(item: Any) -> Iterator[None]:
    yield from _phase(item, "call")


@_wrapper
def pytest_runtest_teardown(item: Any) -> Iterator[None]:
    yield from _phase(item, "teardown")


def pytest_collection_finish(session: Any) -> None:
    observer = current_observer()
    if observer is not None:
        bind_collection(observer, [item.nodeid for item in session.items])
        start_port(observer)
    _record({"event": "pytest_collection", "nodeids": [item.nodeid for item in session.items]})


def pytest_runtest_logreport(report: Any) -> None:
    _record({"event": "pytest_report", "test_nodeid": report.nodeid,
             "phase": report.when, "outcome": report.outcome})


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    _record({"event": "pytest_session_finish", "exitstatus": int(exitstatus),
             "testsfailed": session.testsfailed, "testscollected": session.testscollected})
    observer = current_observer()
    if observer is not None:
        close_port(observer)
