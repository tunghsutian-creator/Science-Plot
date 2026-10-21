"""The public launcher restores selected framework runtimes after shell entry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "skill/scripts/sciplot"


def _script(path: Path, contents: str) -> Path:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)
    return path


def _framework(path: Path) -> Path | None:
    marker = "/Python.framework/Versions/"
    return Path(str(path).split(marker, 1)[0] + "/Python.framework") if marker in str(path) else None


def _controls(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    source = tmp_path / "control source"
    package = source / "sciplot_core"
    package.mkdir(parents=True)
    # Keep the generated CLI first while allowing an inherited real observer to
    # import its actual verification owner through the controlled package.
    (package / "__init__.py").write_text(f"__path__.append({str(REPO_ROOT / 'src/sciplot_core')!r})\n")
    (package / "cli.py").write_text(
        "import json,os,sys\n"
        "print(json.dumps({'frameworks':os.environ.get('DYLD_FRAMEWORK_PATH'),"
        "'libraries':os.environ.get('DYLD_LIBRARY_PATH'),"
        "'bundled':os.environ.get('SCIPLOT_BUNDLED_QT_LIB'),"
        "'callback':os.environ.get('SCIPLOT_BOOTSTRAP_CALLBACK'),'args':sys.argv[1:],"
        "'cwd':os.getcwd()}))\n"
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    environment = {**os.environ, "SCIPLOT_REPO": str(REPO_ROOT),
                   "SCIPLOT_SOURCE_ROOT": str(source), "SCIPLOT_RUNTIME_REPO": str(tmp_path / "runtime"),
                   "SCIPLOT_VEUSZ_ROOT": str(tmp_path / "runtime/third_party/veusz"),
                   "PYTHONDONTWRITEBYTECODE": "1", "PATH": str(tools) + os.pathsep + os.environ["PATH"]}
    environment.pop("DYLD_FRAMEWORK_PATH", None)
    environment.pop("DYLD_LIBRARY_PATH", None)
    environment.pop("SCIPLOT_BUNDLED_QT_LIB", None)
    return tools, environment


def _qt_controls(tmp_path: Path, tools: Path, environment: dict[str, str]) -> tuple[Path, Path]:
    _script(tools / "uname", "#!/bin/sh\nprintf 'Darwin\\n'\n")
    extension = Path(environment["SCIPLOT_VEUSZ_ROOT"]) / "veusz/helpers/qtloops.control.so"
    extension.parent.mkdir(parents=True)
    extension.write_text("generated helper dependency control")
    base = tmp_path / "selected Qt/qtbase/lib"
    core = base / "QtCore.framework/Versions/A/QtCore"
    core.parent.mkdir(parents=True)
    core.write_text("selected QtCore")
    # otool separates the load path from version metadata with whitespace.
    # Use a real no-space alias, as native Mach-O dependency paths do here.
    linked = tmp_path / "qtbase"
    linked.symlink_to(base.parent, target_is_directory=True)
    core = linked / "lib/QtCore.framework/Versions/A/QtCore"
    _script(tools / "otool", "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(str(core)) + "\n")
    environment["SCIPLOT_PYTHON"] = str(Path(sys.executable).resolve())
    return linked / "lib", tmp_path / "qt/lib"


@pytest.mark.parametrize("matching_core,has_svg", [(True, True), (False, True), (True, False)])
def test_cold_qt_bootstrap_adds_only_matching_complete_components(
    tmp_path: Path, matching_core: bool, has_svg: bool,
) -> None:
    tools, environment = _controls(tmp_path)
    base, complete = _qt_controls(tmp_path, tools, environment)
    core = complete / "QtCore.framework/Versions/A/QtCore"
    core.parent.mkdir(parents=True)
    if matching_core:
        core.symlink_to(base / "QtCore.framework/Versions/A/QtCore")
    else:
        core.write_text("different QtCore")
    if has_svg:
        svg = complete / "QtSvg.framework/Versions/A/QtSvg"
        svg.parent.mkdir(parents=True)
        svg.write_text("generated SVG framework")
    result = subprocess.run([str(WRAPPER), "studio", "original.csv"], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    paths = payload["frameworks"].split(os.pathsep)
    assert str(base) in paths
    assert (str(complete) in paths) == (matching_core and has_svg)
    if matching_core and has_svg:
        assert paths.index(str(base)) < paths.index(str(complete))
    assert payload["libraries"] is None
    assert payload["args"] == ["studio", "original.csv"] and payload["cwd"] == str(tmp_path)


@pytest.mark.parametrize("exists", [True, False])
def test_cold_qt_bootstrap_bundled_runtime_never_falls_back_to_helpers(
    tmp_path: Path, exists: bool,
) -> None:
    tools, environment = _controls(tmp_path)
    base, _ = _qt_controls(tmp_path, tools, environment)
    local = Path(environment["SCIPLOT_RUNTIME_REPO"]) / ".local/runtime/qt/lib"
    local.mkdir(parents=True)
    bundled = tmp_path / "bundled Qt lib"
    if exists:
        bundled.mkdir()
    environment["SCIPLOT_BUNDLED_QT_LIB"] = str(bundled)
    result = subprocess.run([str(WRAPPER), "--help"], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, check=False)
    if not exists:
        assert result.returncode != 0 and "repair this installation" in result.stderr
        assert not result.stdout
        return
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert str(bundled) in payload["frameworks"].split(os.pathsep)
    assert str(base) not in payload["frameworks"].split(os.pathsep)
    assert payload["libraries"] is None


def test_cold_qt_bootstrap_automatically_selects_ignored_runtime_qt(tmp_path: Path) -> None:
    tools, environment = _controls(tmp_path)
    base, _ = _qt_controls(tmp_path, tools, environment)
    local = Path(environment["SCIPLOT_RUNTIME_REPO"]) / ".local/runtime/qt/lib"
    local.mkdir(parents=True)
    result = subprocess.run([str(WRAPPER), "--help"], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["bundled"] == str(local)
    assert payload["libraries"] is None
    assert str(local) in payload["frameworks"].split(os.pathsep)
    assert str(base) not in payload["frameworks"].split(os.pathsep)


def test_darwin_framework_bootstrap_preserves_the_selected_runtime_and_cwd(tmp_path: Path) -> None:
    tools, environment = _controls(tmp_path)
    _script(tools / "uname", "#!/bin/sh\nprintf 'Darwin\\n'\n")
    framework_root = tmp_path / "relocated frameworks"
    framework_root.mkdir()
    current_python = Path(sys.executable).resolve()
    actual = _framework(current_python)
    if actual is not None:
        (framework_root / "Python.framework").symlink_to(actual, target_is_directory=True)
        version = current_python.parent.parent.name
    else:
        version = "3.14"
        library = framework_root / f"Python.framework/Versions/{version}/Python"
        library.parent.mkdir(parents=True)
        library.write_text("non-native control for the shell path predicate")
    selected = framework_root / f"Python.framework/Versions/{version}/bin/python3.14"
    _script(tools / "realpath", "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(str(selected)) + "\n")
    environment["SCIPLOT_PYTHON"] = str(current_python)
    result = subprocess.run([str(WRAPPER), "--help"], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["frameworks"] == str(framework_root)
    assert payload["args"] == ["--help"] and payload["cwd"] == str(tmp_path)


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_nonframework_custom_wrapper_keeps_its_runtime_contract(tmp_path: Path, system: str) -> None:
    tools, environment = _controls(tmp_path)
    _script(tools / "uname", "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(system) + "\n")
    current_python = Path(sys.executable).resolve()
    actual = _framework(current_python)
    framework_path = str(actual.parent) if actual is not None else "custom-wrapper-runtime"
    custom = _script(tmp_path / "custom-python", "#!/bin/bash\n"
                     "export SCIPLOT_BOOTSTRAP_CALLBACK=custom-wrapper\n"
                     "export DYLD_FRAMEWORK_PATH=" + shlex.quote(framework_path) + "\n"
                     "exec " + shlex.quote(str(current_python)) + ' "$@"\n')
    environment["SCIPLOT_PYTHON"] = str(custom)
    result = subprocess.run([str(WRAPPER), "--help"], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["callback"] == "custom-wrapper" and payload["frameworks"] == framework_path
    assert payload["args"] == ["--help"] and payload["cwd"] == str(tmp_path)


@pytest.mark.comprehensive
@pytest.mark.parametrize("symlink_alias", [False, True])
def test_public_cli_help_bootstraps_actual_selected_python_without_inherited_dyld(
    tmp_path: Path, symlink_alias: bool,
) -> None:
    selected = Path(sys.executable).resolve()
    if symlink_alias:
        alias = tmp_path / "selected-python"
        alias.symlink_to(selected)
        selected = alias
    environment = {**os.environ, "SCIPLOT_REPO": str(REPO_ROOT),
                   "SCIPLOT_SOURCE_ROOT": str(REPO_ROOT / "src"), "SCIPLOT_PYTHON": str(selected),
                   "PYTHONDONTWRITEBYTECODE": "1"}
    environment.pop("DYLD_FRAMEWORK_PATH", None)
    result = subprocess.run([str(WRAPPER), "--help"], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout and "SciPlot" in result.stdout
