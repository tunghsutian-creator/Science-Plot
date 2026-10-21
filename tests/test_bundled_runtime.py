import pytest

from sciplot_core import veusz_runtime
from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.studio_core import runtime as studio_runtime
from sciplot_core.studio_core.runtime import _qt_framework_paths


def test_bundle_qt_overrides_developer_framework_paths(tmp_path, monkeypatch):
    qt = tmp_path / "Qt lib"
    qt.mkdir()
    monkeypatch.setenv("SCIPLOT_BUNDLED_QT_LIB", str(qt))
    monkeypatch.setenv("DYLD_FRAMEWORK_PATH", "/old/developer/Qt")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/old/developer/lib")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/external/injected.dylib")
    monkeypatch.setattr(veusz_runtime.sys, "executable", str(tmp_path / "plain-python"))
    env = veusz_worker_environment()
    assert env["DYLD_FRAMEWORK_PATH"] == str(qt)
    assert env["DYLD_LIBRARY_PATH"] == "/old/developer/lib"
    assert env["DYLD_INSERT_LIBRARIES"] == "/external/injected.dylib"
    assert _qt_framework_paths() == [qt]
    fallback = {}
    veusz_runtime.configure_qt_loader_environment(fallback, [qt], bundled=False)
    assert fallback["DYLD_FRAMEWORK_PATH"] == str(qt)
    assert "DYLD_LIBRARY_PATH" not in fallback


def test_missing_bundled_qt_does_not_fall_back_to_developer_machine(tmp_path, monkeypatch):
    (tmp_path / ".local/runtime/qt/lib").mkdir(parents=True)
    monkeypatch.setenv("SCIPLOT_RUNTIME_REPO", str(tmp_path))
    monkeypatch.setattr(veusz_runtime.sys, "platform", "darwin")
    monkeypatch.setenv("SCIPLOT_BUNDLED_QT_LIB", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="repair"):
        veusz_worker_environment()
    with pytest.raises(ValueError, match="repair"):
        _qt_framework_paths()


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("platform", [None, "cocoa"])
def test_selected_qt_keeps_real_python_framework_across_worker_gui_and_intake(
    tmp_path, monkeypatch, explicit, platform,
):
    from sciplot_core.intake.packaging import _studio_prepare_env

    local_qt = tmp_path / "runtime/.local/runtime/qt/lib"
    explicit_qt = tmp_path / "explicit Qt/lib"
    local_qt.mkdir(parents=True)
    explicit_qt.mkdir(parents=True)
    python_root = tmp_path / "selected Python frameworks"
    version = python_root / "Python.framework/Versions/3.14"
    executable = version / "bin/python3.14"
    executable.parent.mkdir(parents=True)
    executable.write_text("selected executable")
    (version / "Python").write_text("selected Python library")
    alias = tmp_path / "venv-python"
    alias.symlink_to(executable)
    monkeypatch.setattr(veusz_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(veusz_runtime.sys, "executable", str(alias))
    monkeypatch.setenv("SCIPLOT_RUNTIME_REPO", str(tmp_path / "runtime"))
    monkeypatch.setenv("DYLD_FRAMEWORK_PATH", "/stale/Python.framework:/old/developer/Qt")
    monkeypatch.delenv("DYLD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("SCIPLOT_STUDIO_QT_RUNTIME", raising=False)
    monkeypatch.delenv("SCIPLOT_BUNDLED_QT_LIB", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    if platform is not None:
        monkeypatch.setenv("QT_QPA_PLATFORM", platform)
    selected = explicit_qt if explicit else local_qt
    if explicit:
        monkeypatch.setenv("SCIPLOT_BUNDLED_QT_LIB", str(selected))

    worker = veusz_worker_environment()
    intake = _studio_prepare_env()
    captured = {}
    monkeypatch.setattr(studio_runtime.os, "execvpe", lambda exe, argv, env: captured.update(exe=exe, argv=argv, env=env))
    studio_runtime.maybe_reexec_with_qt_runtime(["studio", "figure.vsz"])
    gui = captured["env"]
    assert captured["exe"] == str(alias)
    assert captured["argv"] == [str(alias), "-m", "sciplot_core.cli", "studio", "figure.vsz"]
    for environment in (worker, intake, gui):
        assert environment["SCIPLOT_BUNDLED_QT_LIB"] == str(selected)
        assert environment["DYLD_FRAMEWORK_PATH"] == str(python_root) + ":" + str(selected)
        assert "DYLD_LIBRARY_PATH" not in environment
        assert environment["SCIPLOT_STUDIO_QT_RUNTIME"] == "1"
    assert worker["QT_QPA_PLATFORM"] == intake["QT_QPA_PLATFORM"] == (platform or "offscreen")
    assert gui.get("QT_QPA_PLATFORM") == platform
