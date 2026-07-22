from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import sciplot_gui
from sciplot_core import intake, intake_server


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    modules.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    return modules


def test_qt_package_contains_only_native_veusz_integration_modules() -> None:
    package_dir = Path(sciplot_gui.__file__).resolve().parent
    modules = {path.name for path in package_dir.glob("*.py")}

    assert modules == {
        "__init__.py",
        "assistant_runtime.py",
        "studio_assistant.py",
        "studio_assistant_history.py",
        "studio_project.py",
        "studio_project_status.py",
    }


def test_headless_intake_domain_does_not_own_the_http_server() -> None:
    domain_imports = _imported_modules(Path(intake.__file__).resolve())
    server_imports = _imported_modules(Path(intake_server.__file__).resolve())

    assert "http.server" not in domain_imports
    assert "socketserver" not in domain_imports
    assert "http.server" in server_imports
    assert "socketserver" in server_imports


def test_package_has_one_cli_and_no_standalone_frontend_entrypoint() -> None:
    repo_root = Path(sciplot_gui.__file__).resolve().parents[2]
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"] == {"sciplot": "sciplot_core.cli:main"}


def test_retired_parallel_lifecycle_modules_stay_absent() -> None:
    core_dir = Path(sciplot_gui.__file__).resolve().parent.parent / "sciplot_core"
    retired = {
        "codex_jobs.py",
        "figure_layouts.py",
        "figure_profiles.py",
        "figure_workflow.py",
        "scalar_strip_renderer.py",
        "workbench_contract.py",
    }

    assert not {path.name for path in core_dir.iterdir()} & retired
