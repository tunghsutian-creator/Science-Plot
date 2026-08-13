from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
import tomllib
from collections.abc import Iterable
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
FIRST_PARTY_PACKAGES = {"sciplot_core", "sciplot_gui", "sciplot_recipes"}
MAX_SOURCE_LINES = 400

# These modules are linear black-box evidence harnesses.  Their ordered setup,
# mutation, and attack trace is itself the verification artifact, so splitting
# them would obscure the scenario rather than create a reusable responsibility.
OVERSIZED_VALIDATION_HARNESSES = {
    "src/sciplot_core/analysis_contract_probe.py",
    "src/sciplot_core/data_mapping_probe.py",
    "src/sciplot_core/openai_provider_probe.py",
    "src/sciplot_core/readiness_probe.py",
    "src/sciplot_core/semantic_contract_probe.py",
    "src/sciplot_core/smoke/runtime.py",
    "src/sciplot_core/smoke/scalar_field.py",
    "src/sciplot_core/smoke/semantic_parser.py",
    "src/sciplot_core/studio_assistant_probe.py",
    "src/sciplot_core/studio_figure_set_probe.py",
    "src/sciplot_core/studio_project_probe.py",
}


def _source_files() -> list[Path]:
    return sorted(
        path
        for package in FIRST_PARTY_PACKAGES
        for path in (SOURCE_ROOT / package).rglob("*.py")
    )


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _absolute_import(module: str, path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    parts = package.split(".")
    retained = parts[: len(parts) - node.level + 1]
    return ".".join([*retained, *(node.module or "").split(".")]).rstrip(".")


def _known_target(name: str, known_modules: set[str]) -> str | None:
    candidate = name
    while candidate:
        if candidate in known_modules:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _import_targets(
    module: str,
    path: Path,
    known_modules: set[str],
) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        names: Iterable[str]
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_import(module, path, node)
            names = (
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
                if alias.name != "*"
            )
            base_target = _known_target(base, known_modules)
            if base_target is not None:
                targets.add(base_target)
        else:
            continue
        for name in names:
            target = _known_target(name, known_modules)
            if target is not None:
                targets.add(target)
    targets.discard(module)
    return targets


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[tuple[str, ...]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = index
        lowlinks[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)
        for target in graph[module]:
            if target not in indices:
                visit(target)
                lowlinks[module] = min(lowlinks[module], lowlinks[target])
            elif target in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[target])
        if lowlinks[module] != indices[module]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == module:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for module in graph:
        if module not in indices:
            visit(module)
    return sorted(components)


def test_ordinary_source_files_stay_within_the_size_boundary() -> None:
    oversized = {
        str(path.relative_to(REPO_ROOT)): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in _source_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_SOURCE_LINES
    }

    assert set(oversized) == OVERSIZED_VALIDATION_HARNESSES


def test_first_party_import_graph_is_acyclic() -> None:
    paths = {_module_name(path): path for path in _source_files()}
    graph = {
        module: _import_targets(module, path, set(paths))
        for module, path in paths.items()
    }

    assert _strongly_connected_components(graph) == []


def test_studio_entry_modules_import_in_fresh_interpreters() -> None:
    for module in (
        "sciplot_core.studio",
        "sciplot_core.studio_core.prepare_generated",
        "sciplot_core.studio_core.studio_command",
    ):
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


def test_terminal_evidence_entry_modules_import_in_fresh_interpreters() -> None:
    for module in (
        "sciplot_core.render",
        "sciplot_core.veusz_worker",
        "sciplot_core.workflow.request_rendering",
    ):
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


def test_terminal_source_binding_wire_has_only_two_runtime_importers() -> None:
    importers: set[str] = set()
    wire_module = "sciplot_core.terminal_source_binding_wire"
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(
                name == wire_module or name.startswith(f"{wire_module}.")
                for name in imported
            ):
                importers.add(str(path.relative_to(REPO_ROOT)))

    assert importers == {
        "src/sciplot_core/render/target_paths.py",
        "src/sciplot_core/veusz_worker/operations.py",
    }


def test_preparation_attestation_keeps_foundation_and_parser_boundaries() -> None:
    known_modules = {_module_name(path) for path in _source_files()}
    for relative in (
        "semantic.py",
        "preparation_source_attestation.py",
    ):
        path = SOURCE_ROOT / "sciplot_core" / relative
        targets = _import_targets(_module_name(path), path, known_modules)
        assert not any(
            target == "sciplot_core.figure_plan"
            or target.startswith("sciplot_core.figure_plan.")
            for target in targets
        )

    task_source = SOURCE_ROOT / "sciplot_core/workflow/rheology_task_sources.py"
    targets = _import_targets(_module_name(task_source), task_source, known_modules)
    assert "sciplot_core.semantic_sources.rheology_sweep_sources" not in targets


def _assert_fresh_python(source: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_study_model_first_import_uses_figure_plan_leaf_owners() -> None:
    _assert_fresh_python(
        """
        import builtins

        original_import = builtins.__import__
        forbidden = {
            "sciplot_core.study_model.run_artifacts": {
                "resolved_figure_plan_from_payload"
            },
            "sciplot_core.study_model.package_contract": {
                "figure_plan_manifest_gate"
            },
        }

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            caller = "" if globals is None else str(globals.get("__name__") or "")
            if (
                name == "sciplot_core.figure_plan"
                and caller in forbidden
                and forbidden[caller] & set(fromlist)
            ):
                raise AssertionError(
                    f"{caller} imported {sorted(fromlist)} from the package facade"
                )
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        import sciplot_core.study_model as study_model
        builtins.__import__ = original_import
        import sciplot_core.figure_plan as figure_plan

        assert set(study_model.__all__) <= study_model.__dict__.keys()
        assert set(figure_plan.__all__) <= figure_plan.__dict__.keys()

        from sciplot_core.figure_plan.manifest_gate import (
            figure_plan_manifest_gate as manifest_gate_leaf,
        )
        from sciplot_core.figure_plan.plan import (
            resolved_figure_plan_from_payload as plan_parser_leaf,
        )

        assert figure_plan.figure_plan_manifest_gate is manifest_gate_leaf
        assert figure_plan.resolved_figure_plan_from_payload is plan_parser_leaf
        """
    )


def test_figure_plan_first_import_does_not_initialize_study_model() -> None:
    _assert_fresh_python(
        """
        import sys
        import sciplot_core.figure_plan as figure_plan

        premature = sorted(
            name
            for name in sys.modules
            if name == "sciplot_core.study_model"
            or name.startswith("sciplot_core.study_model.")
        )
        assert premature == [], premature
        assert set(figure_plan.__all__) <= figure_plan.__dict__.keys()

        import sciplot_core.study_model as study_model

        assert set(study_model.__all__) <= study_model.__dict__.keys()
        assert set(figure_plan.__all__) <= figure_plan.__dict__.keys()
        """
    )


def test_delivery_gate_consumers_import_figure_plan_leaf_owners() -> None:
    for filename in ("package_builder.py", "package_validation.py"):
        path = SOURCE_ROOT / "sciplot_core" / "delivery" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            (node.module, alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }

        assert (
            "sciplot_core.figure_plan.manifest_gate",
            "figure_plan_manifest_gate",
        ) in imports
        assert (
            "sciplot_core.figure_plan.plan",
            "resolved_figure_plan_from_payload",
        ) in imports
        assert not any(
            module == "sciplot_core.figure_plan"
            and name
            in {
                "figure_plan_manifest_gate",
                "resolved_figure_plan_from_payload",
            }
            for module, name in imports
        )


def test_publish_state_imports_the_figure_plan_execution_leaf_owner() -> None:
    path = SOURCE_ROOT / "sciplot_core" / "publish_state.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert (
        "sciplot_core.figure_plan.execution",
        "figure_plan_gate",
    ) in imports
    assert not any(module == "sciplot_core.figure_plan" for module, _name in imports)


def test_core_business_and_data_layers_do_not_depend_on_the_gui_layer() -> None:
    offenders: list[str] = []
    for path in (SOURCE_ROOT / "sciplot_core").rglob("*.py"):
        relative = path.relative_to(SOURCE_ROOT / "sciplot_core")
        if (
            path.name.endswith("_probe.py")
            or "smoke" in path.parts
            or relative.parts[0] == "cli"
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        imports.extend(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        if any(
            name == "sciplot_gui" or name.startswith("sciplot_gui.") for name in imports
        ):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_low_level_packages_do_not_depend_on_higher_core_layers() -> None:
    known_modules = {_module_name(path) for path in _source_files()}
    offenders: list[str] = []
    for package in ("foundation", "policy", "source_tables"):
        package_module = f"sciplot_core.{package}"
        for path in (SOURCE_ROOT / "sciplot_core" / package).rglob("*.py"):
            module = _module_name(path)
            targets = _import_targets(module, path, known_modules)
            if any(not target.startswith(package_module) for target in targets):
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_gui_uses_the_public_studio_api_not_studio_core_implementation() -> None:
    known_modules = {_module_name(path) for path in _source_files()}
    offenders: list[str] = []
    for path in (SOURCE_ROOT / "sciplot_gui").rglob("*.py"):
        module = _module_name(path)
        targets = _import_targets(module, path, known_modules)
        if any(
            target == "sciplot_core.studio_core"
            or target.startswith("sciplot_core.studio_core.")
            for target in targets
        ):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_veusz_worker_does_not_depend_on_the_studio_compatibility_facade() -> None:
    known_modules = {_module_name(path) for path in _source_files()}
    offenders: list[str] = []
    for path in (SOURCE_ROOT / "sciplot_core" / "veusz_worker").rglob("*.py"):
        module = _module_name(path)
        targets = _import_targets(module, path, known_modules)
        if "sciplot_core.studio" in targets:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_veusz_worker_uses_named_studio_core_ports() -> None:
    offenders: list[str] = []
    for path in (SOURCE_ROOT / "sciplot_core" / "veusz_worker").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not (
                node.module or ""
            ).startswith("sciplot_core.studio_core"):
                continue
            if any(alias.name.startswith("_") for alias in node.names):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert offenders == []


def test_generic_catchall_module_names_stay_absent() -> None:
    forbidden_names = {"common.py", "helpers.py", "utils.py"}
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _source_files()
        if path.name in forbidden_names or path.stem.endswith("_common")
    ]

    assert offenders == []


def test_non_probe_source_has_no_exact_duplicate_function_implementations() -> None:
    implementations: dict[str, list[str]] = {}
    for path in _source_files():
        if path.name.endswith("_probe.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            end_line = node.end_lineno or node.lineno
            if end_line - node.lineno + 1 < 8:
                continue
            signature = ast.dump(node.args, include_attributes=False)
            body = ast.dump(
                ast.Module(body=node.body, type_ignores=[]),
                include_attributes=False,
            )
            implementations.setdefault(f"{signature}\n{body}", []).append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
            )

    duplicates = sorted(
        locations for locations in implementations.values() if len(locations) > 1
    )
    assert duplicates == []


def test_removed_compatibility_runtime_stays_absent() -> None:
    core_root = SOURCE_ROOT / "sciplot_core"
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert not (core_root / "_vendor").exists()
    assert not (core_root / "_bootstrap.py").exists()
    assert "_vendor" not in pyproject
    for retired_dependency in (
        "charset-normalizer",
        "matplotlib",
        "seaborn",
        "scienceplots",
    ):
        assert f'"{retired_dependency}"' not in pyproject


def test_scoped_type_gate_has_one_strict_owned_scope_and_ci_entrypoint() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy = project["tool"]["mypy"]

    assert mypy == {
        "python_version": "3.11",
        "files": [
            "src/sciplot_core/foundation",
            "src/sciplot_core/json_contract.py",
            "src/sciplot_core/figure_plan",
            "src/sciplot_core/delivery/plan_binding.py",
            "src/sciplot_core/delivery/package_builder.py",
            "src/sciplot_core/delivery/package_validation.py",
            "src/sciplot_core/study_model/package_contract.py",
            "src/sciplot_core/publish_state.py",
            "src/sciplot_core/autoplot/publish_integrity.py",
            "src/sciplot_core/autoplot/evidence.py",
            "src/sciplot_core/autoplot/summary.py",
        ],
        "mypy_path": "src",
        "explicit_package_bases": True,
        "follow_imports": "silent",
        "strict": True,
        "disallow_any_unimported": True,
        "warn_unreachable": True,
        "warn_unused_configs": True,
        "show_error_codes": True,
        "pretty": True,
        "incremental": False,
    }
    owned_files: set[Path] = set()
    for value in mypy["files"]:
        target = REPO_ROOT / value
        if target.is_dir():
            owned_files.update(target.rglob("*.py"))
        else:
            owned_files.add(target)
    assert len(owned_files) == 43
    dev_dependencies = project["project"]["optional-dependencies"]["dev"]
    assert "mypy==2.3.0" in dev_dependencies
    assert "pandas-stubs==3.0.3.260530" in dev_dependencies

    workflow = (
        REPO_ROOT / ".github" / "workflows" / "minimal-repository.yml"
    ).read_text(encoding="utf-8")
    assert "Run scoped static type gate" in workflow
    assert "run: python3 -m mypy" in workflow


def test_first_party_source_does_not_import_the_removed_src_namespace() -> None:
    offenders: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        imports.extend(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        if any(name == "src" or name.startswith("src.") for name in imports):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []
