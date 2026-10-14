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
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text(
        "import json,os,sys\n"
        "print(json.dumps({'frameworks':os.environ.get('DYLD_FRAMEWORK_PATH'),"
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
    return tools, environment


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
