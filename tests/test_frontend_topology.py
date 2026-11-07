from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
    return modules


def test_retired_qt_frontend_and_window_factories_stay_absent() -> None:
    retired = ["src/sciplot_gui", *("src/sciplot_core/studio_core/" + name + ".py"
               for name in ("qt_launch", "qt_window", "qt_safety"))]
    assert not [path for path in retired if (ROOT / path).exists()]
    # An unrelated editable install in the shared test interpreter is not this
    # checkout's distribution. Prove actual import absence without its finder.
    code = "\n".join([
        "import importlib.util, sys",
        "sys.path.insert(0, " + json.dumps(str(ROOT / "src")) + ")",
        "assert importlib.util.find_spec('sciplot_gui') is None",
        *["assert importlib.util.find_spec('sciplot_core.studio_core." + name + "') is None"
          for name in ("qt_launch", "qt_window", "qt_safety")],
    ])
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    # Qt itself remains part of headless native loading, rendering and fonts.
    for name in ("qt_compat.py", "native_export_adapter.py", "veusz_save.py"):
        assert (ROOT / "src/sciplot_core/studio_core" / name).is_file()
    assert (ROOT / "src/sciplot_core/veusz_worker/font_evidence.py").is_file()


def test_headless_intake_domain_has_no_http_or_browser_adapter() -> None:
    imports = _imported_modules(ROOT / "src/sciplot_core/intake/__init__.py")
    assert not {"http.server", "socketserver", "webbrowser"} & imports
    assert not any("browser_app" in name or "intake_server" in name for name in imports)
    for name in ("intake/browser_app.py", "intake/intake_static", "intake_server"):
        assert not (ROOT / "src/sciplot_core" / name).exists()
    assert (ROOT / "src/sciplot_core/intake/project/project_builder.py").is_file()
    assert (ROOT / "src/sciplot_core/intake/session.py").is_file()


def test_package_has_one_cli_and_no_standalone_frontend_entrypoint() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"] == {"sciplot": "sciplot_core.cli:main"}


def test_retired_parallel_lifecycle_modules_stay_absent() -> None:
    retired = {"codex_jobs.py", "figure_layouts.py", "figure_profiles.py", "figure_workflow.py",
               "scalar_strip_renderer.py", "workbench_contract.py"}
    assert not {path.name for path in (ROOT / "src/sciplot_core").iterdir()} & retired


def test_retired_live_editor_source_assets_and_build_chain_are_absent() -> None:
    root = Path(__file__).resolve().parents[1]
    retired = (
        "src/sciplot_core/live_editor",
        "src/sciplot_core/live_editor_assets",
        "src/sciplot_core/veusz_worker/live_session.py",
        "src/sciplot_core/verification/live_editor_owner.py",
        "web/editor",
    )
    assert not [path for path in retired if (root / path).exists()]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert not any("live_editor" in path or "live_session" in path
                   for path in project["tool"]["mypy"]["files"])
    assert not any("live_editor" in path for path in
                   project["tool"]["setuptools"]["package-data"]["sciplot_core"])
    assert "web/editor" not in (root / "MANIFEST.in").read_text()
