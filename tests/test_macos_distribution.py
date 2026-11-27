from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from distribution.macos.build import build_app, isolated_environment, source_snapshot
from distribution.macos.entrypoints import write_entrypoints
from distribution.macos import macho
from distribution.macos.macho import relocated_reference, system_library
from distribution.macos.welcome import connection_files, render_page
from distribution.macos.runtime_files import _copy_tree, remove_install_location_metadata


def test_connection_files_preserve_unusual_paths_without_host_configuration(tmp_path: Path) -> None:
    command = tmp_path / '空 格 "name" $literal' / "SciPlot.app/Contents/MacOS/sciplot"
    configs = connection_files(command)
    toml = tomllib.loads(configs["codex-mcp.toml"])
    wire = json.loads(configs["mcp-server.json"])
    assert toml["mcp_servers"]["sciplot"]["command"] == str(command)
    assert toml["mcp_servers"]["sciplot"]["args"] == ["mcp", "--profile", "daily"]
    assert wire["mcpServers"]["sciplot"] == {"command": str(command), "args": ["mcp", "--profile", "daily"]}
    assert not any(tmp_path.iterdir())


def test_packaged_metadata_does_not_disclose_editable_checkout(tmp_path: Path) -> None:
    metadata = tmp_path / "sciplot_core-0.1.0.dist-info"
    metadata.mkdir()
    direct = metadata / "direct_url.json"
    direct.write_text('{"url":"file:///private/developer/source"}')
    (metadata / "METADATA").write_text("Name: sciplot-core\nVersion: 0.1.0\n")
    remove_install_location_metadata(tmp_path)
    assert not direct.exists()
    assert (metadata / "METADATA").read_text().startswith("Name: sciplot-core")


def test_build_snapshot_and_source_copy_ignore_regenerated_egg_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    package = repo / "src/sciplot_core"
    package.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'sciplot-core'\n")
    (package / "__init__.py").write_text("value = 1\n")
    metadata = repo / "src/sciplot_core.egg-info"
    metadata.mkdir()
    record = metadata / "SOURCES.txt"
    record.write_text("first development build\n")
    before = source_snapshot(repo)
    record.write_text("regenerated during an editable build\n")
    assert source_snapshot(repo) == before
    target = tmp_path / "packaged-src"
    _copy_tree(repo / "src", target)
    assert not (target / "sciplot_core.egg-info").exists()
    assert (target / "sciplot_core/__init__.py").read_text() == "value = 1\n"


def test_bundle_entrypoint_uses_only_moved_bundle_runtime(tmp_path: Path) -> None:
    app = tmp_path / "有空格的应用" / "SciPlot.app"
    resources = app / "Contents/Resources"
    write_entrypoints(app, "3.14")
    runtime_python = resources / "runtime/bin/python3"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text('#!/bin/bash\nprintf "%s\\n" "$SCIPLOT_REPO" "$PYTHONPATH" "$SCIPLOT_BUNDLED_QT_LIB" "$*"\n')
    runtime_python.chmod(0o755)
    document = tmp_path / "研究 图.sciplot"
    finder = app / "Contents/MacOS/SciPlotLauncher"
    launched = subprocess.run([str(finder), str(document)], check=True, capture_output=True, text=True)
    assert launched.stdout.splitlines()[-1] == f"{resources / 'distribution-source/finder.py'} {document}"
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    [handler] = info["CFBundleDocumentTypes"]
    [project_type] = info["UTExportedTypeDeclarations"]
    assert handler["CFBundleTypeRole"] == "Editor"
    assert handler["LSItemContentTypes"] == [project_type["UTTypeIdentifier"]]
    assert project_type["UTTypeTagSpecification"] == {"public.filename-extension": ["sciplot"]}
    result = subprocess.run(
        [str(resources / "app/skill/scripts/sciplot"), "mcp"],
        check=True, capture_output=True, text=True,
        timeout=10,
        env=os.environ | {"SCIPLOT_REPO": "/old/repo", "PYTHONPATH": "/old/site", "DYLD_FRAMEWORK_PATH": "/old/qt"},
    )
    assert "/old/" not in result.stdout
    assert str(resources / "app") in result.stdout
    assert str(resources / "runtime/lib/python3.14/site-packages/PyQt6/Qt6/lib") in result.stdout
    assert result.stdout.splitlines()[-1] == "-m sciplot_core.cli mcp"


def test_finder_qt_intake_handles_cold_and_warm_file_events(tmp_path: Path) -> None:
    cold = tmp_path / "冷 启动.sciplot"
    warm = tmp_path / "已 打开.sciplot"
    # PyQt receives native QFileOpenEvent objects but cannot construct them.
    # Deliver a Qt event of the same type and surface in an isolated process.
    driver = """
import sys
from pathlib import Path
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer, QUrl
from distribution.macos.finder import FinderApplication

class OpenEvent(QEvent):
    def __init__(self, url):
        super().__init__(QEvent.Type.FileOpen)
        self._url = url
    def url(self):
        return self._url
    def file(self):
        assert self._url.isEmpty()
        return cold

mode, cold, warm = sys.argv[1:]
opened = []
app = FinderApplication(["sciplot"], lambda path: opened.append(str(path)), lambda: opened.append("rejected"))
def welcome():
    opened.append("welcome")
    if mode == "late":
        QTimer.singleShot(10, lambda: QCoreApplication.postEvent(app, OpenEvent(QUrl.fromLocalFile(cold))))
    QTimer.singleShot(50, app.quit)

app.start([], welcome)
if mode == "events":
    QCoreApplication.postEvent(app, OpenEvent(QUrl()))
    QTimer.singleShot(475, lambda: QCoreApplication.postEvent(app, OpenEvent(QUrl.fromLocalFile(warm))))
    QTimer.singleShot(515, lambda: QCoreApplication.postEvent(app, OpenEvent(QUrl("https://invalid.test/remote.sciplot"))))
    QTimer.singleShot(575, app.quit)
app.exec()
expected = {"events": [cold, warm, "rejected"], "welcome": ["welcome"], "late": ["welcome", cold]}
assert opened == expected[mode], opened
"""
    for mode in ("events", "welcome", "late"):
        result = subprocess.run(
            [sys.executable, "-c", driver, mode, str(cold), str(warm)],
            capture_output=True, text=True, timeout=10, env=os.environ | {"QT_QPA_PLATFORM": "offscreen"},
        )
        assert result.returncode == 0, result.stderr


def test_build_refuses_existing_output_before_copying(tmp_path: Path) -> None:
    if os.uname().sysname != "Darwin":
        pytest.skip("macOS builder")
    existing = tmp_path / "SciPlot.app"
    existing.mkdir()
    sentinel = existing / "user-file"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError, match="never overwritten"):
        build_app(tmp_path, existing)
    assert sentinel.read_text() == "preserve"


def test_relocation_and_isolation_do_not_allow_host_runtime_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    assert system_library("/usr/lib/libSystem.B.dylib")
    assert not system_library("/opt/homebrew/lib/libqt.dylib")
    assert not system_library("/System/LibraryEvil/lib.dylib")
    assert relocated_reference(Path("/a/bin/python"), Path("/a/lib/Python")) == "@loader_path/../lib/Python"
    monkeypatch.setenv("SCIPLOT_REPO", "/developer/repo")
    monkeypatch.setenv("PYTHONPATH", "/developer/python")
    monkeypatch.setenv("DYLD_FRAMEWORK_PATH", "/developer/qt")
    clean = isolated_environment()
    assert not {"SCIPLOT_REPO", "PYTHONPATH", "DYLD_FRAMEWORK_PATH"} & clean.keys()


def test_welcome_reports_actual_failure_and_does_not_claim_novice_acceptance(tmp_path: Path) -> None:
    page = render_page(tmp_path / "sciplot", {"status": "needs_fix", "error": "<missing Qt>"}, False, tmp_path / "check.json")
    assert "本地环境需要处理" in page
    assert "&lt;missing Qt&gt;" in page
    assert "尚未提供 MCP" in page
    assert "不能替代干净 Mac 安装" in page
    assert 'download="mcp-server.json"' not in page
    assert 'download="codex-mcp.toml"' not in page
    assert "task create" in page and "plot open" in page


def test_native_audit_rejects_external_missing_and_escaping_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "runtime/bin/python"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\xcf\xfa\xed\xfe")
    for dependency in ("/opt/homebrew/lib/Python", "@rpath/Python", "@loader_path/missing", "@loader_path/../../../outside"):
        monkeypatch.setattr(macho, "load_commands", lambda path, dependency=dependency: ([dependency], [], None))
        with pytest.raises(ValueError, match="dependency|Dependency"):
            macho.audit_runtime(tmp_path)
    library = tmp_path / "runtime/lib/Python"
    library.parent.mkdir()
    library.write_bytes(b"library fixture")
    monkeypatch.setattr(macho, "load_commands", lambda path: (["@loader_path/../lib/Python", "/usr/lib/libSystem.B.dylib"], [], None))
    assert macho.audit_runtime(tmp_path) == {"mach_o_count": 1, "external_non_system_dependencies": 0}


def test_reopening_project_focuses_editor_until_it_is_closed() -> None:
    driver = """
import sys, types
from pathlib import Path
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QWidget
from distribution.macos.finder import FinderApplication, main

created = []
class Editor(QWidget):
    def __init__(self, path, **kwargs):
        super().__init__()
        created.append(self)
        self.activations = 0
    def activateWindow(self):
        self.activations += 1

stub = types.ModuleType("sciplot_core.plot_editor")
stub.PlotEditor = Editor
sys.modules[stub.__name__] = stub
def exercise(self):
    self._open_document(Path("first.sciplot"))
    first, = created
    first.showMinimized()
    self._open_document(Path("first.sciplot").absolute())
    assert created == [first] and first.activations == 2 and not first.isMinimized()
    self._open_document(Path("second.sciplot"))
    assert len(created) == 2
    first.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    self._open_document(Path("first.sciplot"))
    assert len(created) == 3
    return 0
FinderApplication.exec = exercise
assert main() == 0
"""
    result = subprocess.run(
        [sys.executable, "-c", driver], capture_output=True, text=True, timeout=10,
        env=os.environ | {"QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr


def test_build_refuses_a_checkout_without_compiled_veusz_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from distribution.macos import build

    # Reach the actual build entry point without relying on host tool discovery.
    monkeypatch.setattr(build.sys, "platform", "darwin")
    monkeypatch.setattr(build.shutil, "which", lambda tool: tool)
    repo = tmp_path / "checkout"
    helpers = repo / "third_party/veusz/veusz/helpers"
    helpers.mkdir(parents=True)
    # Source and a different Python ABI are not usable native inputs.
    (helpers / "qtloops.sip").touch()
    (helpers / "qtloops.cpython-999-darwin.so").touch()
    output = tmp_path / "SciPlot.app"
    with pytest.raises(RuntimeError, match="Missing compiled Veusz helpers: qtloops"):
        build_app(repo, output)
    assert not output.exists()
