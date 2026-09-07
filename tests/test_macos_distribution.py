from __future__ import annotations

import json
import os
import subprocess
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
    assert wire["mcpServers"]["sciplot"] == {"command": str(command), "args": ["mcp"]}
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
    assert "真实小白测试仍需独立验收" in page
    assert "不会改写任何 AI 工具的设置" in page


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
