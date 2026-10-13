from __future__ import annotations

import builtins
import errno
import importlib.machinery
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from sciplot_core.doctor import (
    _next_actions,
    _publication_foundation_available,
    _vsz_lifecycle_available,
    doctor_payload,
    readiness_checks,
    runtime_checks,
)
from sciplot_core.doctor import payload as doctor_module


@pytest.mark.parametrize(
    ("wrapper_kind", "expected_status"),
    [("missing", "failed"), ("directory", "failed"),
     ("non_executable", "failed"), ("executable", "passed")],
)
def test_doctor_requires_a_regular_executable_skill_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    wrapper_kind: str, expected_status: str,
) -> None:
    wrapper = tmp_path / "skill" / "scripts" / "sciplot"
    wrapper.parent.mkdir(parents=True)
    if wrapper_kind == "directory":
        wrapper.mkdir()
    elif wrapper_kind != "missing":
        wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        wrapper.chmod(0o755 if wrapper_kind == "executable" else 0o644)
    (tmp_path / "pyproject.toml").touch()
    monkeypatch.setattr(doctor_module, "REPO_ROOT", tmp_path)
    original_mode = wrapper.stat().st_mode if wrapper.exists() else None

    payload = doctor_payload()

    check = next(item for item in payload["checks"] if item["id"] == "skill_wrapper")
    assert check["status"] == expected_status
    assert check["required"] is True
    assert check["detail"] == str(wrapper)
    if expected_status == "failed":
        assert payload["status"] == "blocked"
    assert (wrapper.stat().st_mode if wrapper.exists() else None) == original_mode


def test_doctor_finds_lifecycle_symbols_through_package_facades() -> None:
    assert _vsz_lifecycle_available()


def test_doctor_finds_publication_symbols_through_package_facades() -> None:
    assert _publication_foundation_available()


def test_doctor_lists_changed_owner_verification_before_broad_gates() -> None:
    routes = doctor_payload()["command_surface"]["developer_validation_routes"]

    assert routes == ["verify", "smoke", "acceptance", "batch"]


def test_doctor_prefers_external_tasks_and_retains_native_compatibility() -> None:
    payload = doctor_payload()
    normal = payload["normal_mode"]
    routes = payload["command_surface"]

    assert normal["task_interface"] == "external_ai"
    assert normal["daily_entrypoint"] == "sciplot task start --request REQUEST_JSON --json"
    assert normal["daily_entrypoint"] == routes["task_family"]["start"]
    assert normal["capabilities_entrypoint"] == "sciplot task capabilities --json"
    assert normal["capabilities_entrypoint"] == routes["task_family"]["capabilities"]
    assert routes["task_family"]["command"] == "task"
    assert routes["task_family"]["preferred_for"] == "external_ai_create_edit_export_and_continuation"
    assert routes["task_family"]["internal_model_required"] is False
    assert routes["project_control"]["command"] == "project"
    assert routes["mcp_transport"]["command"] == "mcp"
    assert routes["mcp_transport"]["internal_model_required"] is False
    assert normal["interactive_entrypoint"] == routes["interactive_family"]["interactive"]
    assert normal["interactive_entrypoint"] == "sciplot edit PROJECT_OR_DELIVERY"
    assert normal["frontend_default"] == "live_editor"
    assert normal["frontend_default_scope"] == "saved_project_visual_adjustments"
    assert routes["interactive_family"]["command"] == "edit"
    assert routes["interactive_family"]["document_authority"] == "saved_vsz"
    assert normal["native_editor_entrypoint"] == routes["native_compatibility"]["interactive"]
    assert routes["native_compatibility"]["command"] == "studio"
    assert payload["vsz_lifecycle"]["editor"] == "live_editor"
    assert payload["vsz_lifecycle"]["native_editor"] == "veusz_mainwindow"
    assert any("Open_in_SciPlot.command" in item for item in _next_actions([]))
    assert routes["automation_family"]["command"] == "autoplot"
    assert routes["automation_family"]["separate_renderer"] is False
    assert "not directly resumable" in routes["automation_family"]["role"]


def test_doctor_exposes_readiness_evidence_scope() -> None:
    envelopes = doctor_payload()["validated_envelopes"]

    assert envelopes["evidence_scope"] == {
        "contract_freshness": "rule_declarations_and_render_request_policy",
        "implementation_freshness": "not_tracked_by_this_registry",
        "human_validation": "historical_owner_confirmation_without_build_binding",
    }
    assert envelopes["claims"]["current_implementation_certified"] is False
    assert envelopes["claims"]["human_validation_bound_to_current_build"] is False


def test_doctor_reports_runtime_and_optional_development_prerequisites_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        doctor_module,
        "_veusz_qt_runtime_status",
        lambda: (False, "Vendored Veusz qtloops compiled helper is absent"),
    )
    monkeypatch.setattr(
        doctor_module,
        "_qt_build_prerequisite_status",
        lambda *, needed: (False, "qmake cannot run; sip-build is absent") if needed else (True, "ok"),
    )
    monkeypatch.setattr(
        doctor_module,
        "_local_socket_status",
        lambda: (False, "AF_UNIX denied by sandbox; no service contacted"),
    )
    monkeypatch.setattr(
        doctor_module,
        "_ready_rule_fixtures_exist",
        lambda rules: (False, "missing 24 rule fixtures under SCIPLOT_REFERENCE_DATA"),
    )

    payload = doctor_payload()
    checks = {check["id"]: check for check in payload["checks"]}

    assert payload["status"] == "blocked"
    assert checks["veusz_qt_runtime"]["required"] is True
    assert checks["qt_build_prerequisites"]["required"] is False
    assert checks["local_socket_transport"]["required"] is False
    assert "sciplot plot" in checks["local_socket_transport"]["label"]
    assert payload["optional_capabilities"]["plot_socket_transport"] == {
        "required_for_task_native_readiness": False,
        "default_route": "sciplot plot",
        "available": False,
    }
    assert checks["ready_rule_fixtures"]["required"] is False
    assert "Real-data acceptance only; not needed for ordinary use" in checks["ready_rule_fixtures"]["detail"]
    assert "Build the vendored Veusz native helpers" in " ".join(payload["next_actions"])
    assert not any("fixture" in action.lower() for action in payload["next_actions"])


def test_socket_denial_does_not_block_socket_independent_task_native_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(doctor_module, "_veusz_qt_runtime_status", lambda: (True, "qtloops loaded"))
    monkeypatch.setattr(doctor_module, "_qt_build_prerequisite_status", lambda *, needed: (True, "not needed"))
    monkeypatch.setattr(doctor_module, "_local_socket_status", lambda: (False, "AF_UNIX denied"))
    monkeypatch.setattr(doctor_module, "_ready_rule_fixtures_exist", lambda rules: (False, "private corpus absent"))

    payload = doctor_payload()

    assert payload["status"] == "ready"
    assert payload["optional_capabilities"]["plot_socket_transport"]["available"] is False
    assert next(check for check in payload["checks"] if check["id"] == "ready_rule_fixtures")["required"] is False


def test_doctor_identifies_unix_socket_permission_denial_before_service_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_socket(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(runtime_checks.socket, "socket", deny_socket)

    ok, detail = runtime_checks._local_socket_status()

    assert ok is False
    assert "AF_UNIX" in detail
    assert "denied by OS or sandbox" in detail
    assert "errno 1" in detail
    assert "no SciPlot service was contacted" in detail


def test_doctor_socket_probe_removes_temporary_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound: list[Path] = []

    class FakeSocket:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def bind(self, path: str) -> None:
            bound.append(Path(path))
            Path(path).touch()

        def listen(self, _backlog: int) -> None:
            pass

    monkeypatch.setattr(runtime_checks.socket, "socket", lambda *_args: FakeSocket())

    ok, detail = runtime_checks._local_socket_status()

    assert ok is True
    assert "no service was contacted" in detail
    assert len(bound) == 1
    assert not bound[0].exists()


def test_doctor_distinguishes_missing_qtloops_binary_from_load_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def failing_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "PyQt6":
            return SimpleNamespace(QtCore=object(), QtGui=object(), QtWidgets=object())
        return original_import(name, *args, **kwargs)

    def failing_helper_import(_name: str) -> object:
        raise ImportError("qtloops load failed")

    monkeypatch.setattr(runtime_checks, "_module_available", lambda _name: True)
    monkeypatch.setattr(runtime_checks, "VEUSZ_ROOT", tmp_path)
    monkeypatch.setattr(runtime_checks.sys, "path", runtime_checks.sys.path.copy())
    monkeypatch.setattr(builtins, "__import__", failing_import)
    monkeypatch.setattr(runtime_checks.importlib, "import_module", failing_helper_import)

    missing, missing_detail = runtime_checks._veusz_qt_runtime_status()
    helper_dir = tmp_path / "veusz" / "helpers"
    helper_dir.mkdir(parents=True)
    (helper_dir / ("qtloops" + importlib.machinery.EXTENSION_SUFFIXES[0])).touch()
    unloadable, unloadable_detail = runtime_checks._veusz_qt_runtime_status()

    assert missing is unloadable is False
    assert "compiled helper is absent" in missing_detail
    assert "compiled helper is present but cannot load" in unloadable_detail


@pytest.mark.parametrize("failed_helper", ["qtmml", "recordpaint", "threed", "_nc_cntr"])
def test_doctor_rejects_each_broken_helper_even_when_qtloops_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_helper: str,
) -> None:
    original_import = builtins.__import__
    loaded: list[str] = []

    def import_qt(name: str, *args: object, **kwargs: object) -> object:
        if name == "PyQt6":
            return SimpleNamespace(QtCore=object(), QtGui=object(), QtWidgets=object())
        return original_import(name, *args, **kwargs)

    def import_helper(name: str) -> object:
        loaded.append(name)
        if name == "veusz.helpers." + failed_helper:
            raise ImportError(f"dynamic module does not define module export function (PyInit_{failed_helper})")
        return object()

    helper_dir = tmp_path / "veusz" / "helpers"
    helper_dir.mkdir(parents=True)
    (helper_dir / (failed_helper + importlib.machinery.EXTENSION_SUFFIXES[0])).touch()
    monkeypatch.setattr(runtime_checks, "_module_available", lambda _name: True)
    monkeypatch.setattr(runtime_checks, "VEUSZ_ROOT", tmp_path)
    monkeypatch.setattr(runtime_checks.sys, "path", runtime_checks.sys.path.copy())
    monkeypatch.setattr(builtins, "__import__", import_qt)
    monkeypatch.setattr(runtime_checks.importlib, "import_module", import_helper)

    ok, detail = runtime_checks._veusz_qt_runtime_status()

    assert ok is False
    assert loaded[0] == "veusz.helpers.qtloops"
    assert loaded[-1] == "veusz.helpers." + failed_helper
    assert failed_helper in detail and "compiled helper is present but cannot load" in detail
    assert "PyInit_" + failed_helper in detail


def test_doctor_requires_every_native_helper_to_load(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__
    loaded: list[str] = []

    def import_qt(name: str, *args: object, **kwargs: object) -> object:
        if name == "PyQt6":
            core = SimpleNamespace(PYQT_VERSION_STR="6.11.0", qVersion=lambda: "6.11.2")
            return SimpleNamespace(QtCore=core, QtGui=object(), QtWidgets=object())
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(runtime_checks, "_module_available", lambda _name: True)
    monkeypatch.setattr(builtins, "__import__", import_qt)
    monkeypatch.setattr(runtime_checks.importlib, "import_module", lambda name: loaded.append(name) or object())

    ok, detail = runtime_checks._veusz_qt_runtime_status()

    assert ok is True
    assert loaded == ["veusz.helpers." + name for name in
                      ("qtloops", "qtmml", "recordpaint", "threed", "_nc_cntr")]
    assert "Qt runtime 6.11.2" in detail


def test_doctor_does_not_mislabel_pyqt_load_failure_as_missing_qtloops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def failing_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "PyQt6":
            raise OSError("Qt shared library unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(runtime_checks, "_module_available", lambda _name: True)
    monkeypatch.setattr(runtime_checks, "VEUSZ_ROOT", tmp_path)
    monkeypatch.setattr(runtime_checks.sys, "path", runtime_checks.sys.path.copy())
    monkeypatch.setattr(builtins, "__import__", failing_import)

    ok, detail = runtime_checks._veusz_qt_runtime_status()

    assert ok is False
    assert "PyQt6/Qt runtime cannot load" in detail
    assert "qtloops" not in detail
    actions = _next_actions([{"id": "veusz_qt_runtime", "detail": detail}])
    assert any("Repair the PyQt6/Qt runtime" in action for action in actions)
    assert not any("Build the vendored Veusz" in action for action in actions)


def test_doctor_source_build_check_requires_working_qt6_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QMAKE_EXE", raising=False)
    paths = {
        "qmake-qt6": None,
        "qmake6": None,
        "qmake": "/usr/bin/qmake",
        "sip-build": None,
        "c++": "/usr/bin/c++",
    }
    monkeypatch.setattr(runtime_checks.shutil, "which", paths.get)
    monkeypatch.setattr(
        runtime_checks.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "qmake cannot execute"),
    )

    ok, detail = runtime_checks._qt_build_prerequisite_status(needed=True)

    assert ok is False
    assert "qmake cannot execute" in detail
    assert "sip-build is absent" in detail
    assert "Needed only to build" in detail
    assert runtime_checks._qt_build_prerequisite_status(needed=False)[0] is True


def test_doctor_names_configured_private_fixture_root_without_requiring_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = tmp_path / "private-reference-data"
    monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", str(reference))
    rule = SimpleNamespace(
        rule_id="synthetic_unit_rule",
        fixture_status="ready",
        fixture_path="tests/fixtures/real_world/synthetic_unit_rule/source.csv",
    )

    ok, detail = readiness_checks._ready_rule_fixtures_exist([rule])

    assert ok is False
    assert "synthetic_unit_rule" in detail
    assert str(reference) in detail
    assert "SCIPLOT_REFERENCE_DATA" in detail
