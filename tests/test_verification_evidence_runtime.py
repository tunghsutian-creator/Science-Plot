"""Native discovery and logical loader closure regressions without native execution."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from sciplot_core.verification import evidence_runtime as runtime
from sciplot_core.verification.evidence_identity import digest, discover_files


def binary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xcf\xfa\xed\xfe" + b"test native bytes")
    return path


def test_native_logical_alias_and_absent_loader_candidates_are_bound(tmp_path, monkeypatch):
    main = binary(tmp_path / "main.so")
    old = binary(tmp_path / "old/lib.dylib")
    new = binary(tmp_path / "new/lib.dylib")
    alias = tmp_path / "current"
    alias.symlink_to(old.parent, target_is_directory=True)
    absent = tmp_path / "preferred"
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    def otool(command, **kwargs):
        if Path(command[-1]) == main:
            output = (f"{main} (architecture arm64):\n\t@rpath/lib.dylib (compatibility version 1)\n"
                      f"{main} (architecture x86_64):\n\t@rpath/lib.dylib (compatibility version 1)\n")
            loads = f"cmd LC_RPATH\ncmdsize 40\npath {absent} (offset 12)\ncmd LC_RPATH\ncmdsize 40\npath {alias} (offset 12)\n"
        else:
            output, loads = f"{command[-1]}:\n", ""
        return SimpleNamespace(stdout=output if command[1] == "-L" else loads)
    monkeypatch.setattr(runtime.subprocess, "run", otool)
    bindings, aliases = {}, {}
    roots = runtime.native_dependencies([str(main)], executable=main, environment={}, bindings=bindings, aliases=aliases)
    assert alias / "lib.dylib" in roots and absent / "lib.dylib" in roots
    assert aliases[digest(str(alias / "lib.dylib"))] == digest(str(old))
    before = discover_files(roots, allow_missing=True)
    alias.unlink()
    alias.symlink_to(new.parent, target_is_directory=True)
    assert before != discover_files(roots, allow_missing=True)
    binary(absent / "lib.dylib")
    assert before != discover_files(roots, allow_missing=True)


def test_unknown_native_dependency_blocks(tmp_path, monkeypatch):
    main = binary(tmp_path / "main.so")
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(runtime.subprocess, "run", lambda command, **kwargs: SimpleNamespace(
        stdout=f"{main}:\n\t@rpath/unknown.dylib (compatibility version 1)\n" if command[1] == "-L" else ""))
    with pytest.raises(ValueError, match="unresolved"):
        runtime.native_dependencies([str(main)], executable=main, environment={})


def test_unused_qml_is_byte_input_but_not_supported_native_entrypoint():
    assert not runtime._native_entrypoint("/site/PyQt6/Qt6/plugins/qmltooling/libunused.dylib")
    assert runtime._native_entrypoint("/site/PyQt6/Qt6/plugins/platforms/libqcocoa.dylib")
    assert runtime._native_entrypoint("/site/PyQt6/QtSvg.abi3.so")


@pytest.mark.parametrize("source", ["from PyQt6 import QtQuick", "import importlib\nimportlib.import_module('PyQt6.QtQuick')"])
def test_new_unsupported_static_or_dynamic_qt_import_blocks(tmp_path, source):
    (tmp_path / "new.py").write_text(source)
    with pytest.raises(ValueError, match="Qt imports"):
        runtime.qt_import_bindings([tmp_path])


@pytest.mark.skipif(sys.platform != "darwin", reason="default runtime policy binds the actual macOS build")
def test_runtime_keeps_logical_roots_and_missing_enabled_usersite(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    for directory in [old, new]:
        directory.mkdir()
        (directory / "bytes").write_text(directory.name)
    alias = tmp_path / "current"
    alias.symlink_to(old, target_is_directory=True)
    executable = tmp_path / "python"
    executable.symlink_to(old / "bytes")
    site = tmp_path / "site"
    (site / "PyQt6").mkdir(parents=True)
    usersite = tmp_path / "absent-user-site"
    monkeypatch.setattr(runtime.site, "getsitepackages", lambda: [str(site)])
    monkeypatch.setattr(runtime.site, "ENABLE_USER_SITE", True)
    monkeypatch.setattr(runtime.site, "getusersitepackages", lambda: str(usersite))
    monkeypatch.setattr(runtime.sysconfig, "get_path", lambda name: str(tmp_path / "stdlib"))
    monkeypatch.setattr(runtime.sys, "path", [str(alias)])
    monkeypatch.setattr(runtime.sys, "executable", str(executable))
    domains, _ = runtime.runtime_inputs(repo_root=tmp_path, environment={
        "SCIPLOT_VEUSZ_ROOT": str(alias), "PYTHONPATH": str(alias), "DYLD_FRAMEWORK_PATH": str(alias)})
    assert domains["python"][0] == executable
    assert domains["native"][0] == alias and domains["native"][-1] == alias
    assert alias in domains["dependencies"] and usersite in domains["dependencies"]
    before = discover_files([alias, executable, usersite], allow_missing=True)
    alias.unlink()
    alias.symlink_to(new, target_is_directory=True)
    executable.unlink()
    executable.symlink_to(new / "bytes")
    assert before != discover_files([alias, executable, usersite], allow_missing=True)


def test_real_session_finish_blocks_unreviewed_dynamically_loaded_qt(tmp_path, monkeypatch):
    import json
    from sciplot_core.verification import pytest_finish
    finish = tmp_path / "finish.json"
    monkeypatch.setenv("SCIPLOT_VERIFY_FINISH", str(finish))
    monkeypatch.setenv("SCIPLOT_VERIFY_QT_MODULES", json.dumps(sorted(runtime.QT_MODULES)))
    monkeypatch.setitem(sys.modules, "PyQt6.QtQuick", SimpleNamespace())
    pytest_finish.pytest_sessionfinish(SimpleNamespace(items=[]), 0)
    assert json.loads(finish.read_text())["complete"] is False


@pytest.mark.skipif(sys.platform != "darwin", reason="default runtime policy binds the actual macOS build")
def test_relative_runtime_environment_binds_real_child_inputs(tmp_path, monkeypatch):
    import os
    import subprocess
    caller, repo = tmp_path / "caller", tmp_path / "project/repo"
    caller.mkdir()
    repo.mkdir(parents=True)
    child_source = repo.parent / "external"
    child_source.mkdir()
    module = child_source / "scientific_input.py"
    module.write_text("VALUE = 1\n")
    wrong_parent_source = tmp_path / "external"
    wrong_parent_source.mkdir()
    (wrong_parent_source / module.name).write_text("VALUE = 99\n")
    site = tmp_path / "site"
    (site / "PyQt6").mkdir(parents=True)
    for name in ("runtime/third_party/veusz", "plugins", "frameworks", "fonts", "parent-extra"):
        (repo / name).mkdir(parents=True)
    alias = repo / "import-current"
    alias.symlink_to(child_source, target_is_directory=True)
    monkeypatch.chdir(caller)
    monkeypatch.setattr(runtime.site, "getsitepackages", lambda: [str(site)])
    monkeypatch.setattr(runtime.site, "ENABLE_USER_SITE", False)
    monkeypatch.setattr(runtime.sysconfig, "get_path", lambda name: str(tmp_path / "stdlib"))
    monkeypatch.setattr(runtime.sys, "path", [*sys.path, "parent-extra"])
    env = {"PYTHONPATH": "../external:import-current:~/extras", "SCIPLOT_RUNTIME_REPO": "runtime",
           "QT_PLUGIN_PATH": "plugins", "DYLD_FRAMEWORK_PATH": "frameworks", "QT_QPA_FONTDIR": "fonts"}
    domains, _ = runtime.runtime_inputs(repo_root=repo, environment=env)
    assert repo / "../external" in domains["dependencies"]
    assert alias in domains["dependencies"]
    assert repo / "~/extras" in domains["dependencies"]
    assert caller / "parent-extra" in domains["dependencies"]
    assert domains["native"][0] == repo / "runtime/third_party/veusz"
    assert repo / "plugins" in domains["qt"] and repo / "frameworks" in domains["native"]
    assert repo / "fonts" in domains["fonts"]
    command = [sys.executable, "-B", "-c", "import scientific_input; assert scientific_input.VALUE == 1"]
    assert subprocess.run(command, cwd=repo, env={**os.environ, **env}).returncode == 0
    inputs = [path for path in domains["dependencies"] if path in {repo / "../external", alias}]
    from sciplot_core.verification.evidence_identity import DOMAINS, capture_inputs
    bindings = {domain: {"paths": [str(path) for path in inputs], "symlinks": "resolve", "allow_missing": True} for domain in DOMAINS}
    before = capture_inputs(bindings, repo_root=repo)
    module.write_text("VALUE = 2\n")
    assert before != capture_inputs(bindings, repo_root=repo)
    assert subprocess.run(command, cwd=repo, env={**os.environ, **env}, capture_output=True).returncode != 0
