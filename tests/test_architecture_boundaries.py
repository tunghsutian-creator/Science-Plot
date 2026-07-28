from __future__ import annotations

import ast
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
