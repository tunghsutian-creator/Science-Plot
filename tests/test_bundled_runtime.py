import pytest

from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.studio_core.runtime import _qt_framework_paths


def test_bundle_qt_overrides_developer_framework_paths(tmp_path, monkeypatch):
    qt = tmp_path / "Qt lib"
    qt.mkdir()
    monkeypatch.setenv("SCIPLOT_BUNDLED_QT_LIB", str(qt))
    monkeypatch.setenv("DYLD_FRAMEWORK_PATH", "/old/developer/Qt")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/old/developer/lib")
    env = veusz_worker_environment()
    assert env["DYLD_FRAMEWORK_PATH"] == str(qt)
    assert env["DYLD_LIBRARY_PATH"] == str(qt)
    assert _qt_framework_paths() == [qt]


def test_missing_bundled_qt_does_not_fall_back_to_developer_machine(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIPLOT_BUNDLED_QT_LIB", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="repair"):
        veusz_worker_environment()
    with pytest.raises(ValueError, match="repair"):
        _qt_framework_paths()
