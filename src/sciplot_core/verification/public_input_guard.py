"""Public test enforcement for CPython file access and child launch arguments.

This enforcement is not a complete native filesystem observer. Clean public CI
also has no private files; child-inclusive observation is a separate contract.
"""
from __future__ import annotations

import json
import hashlib
import ast
import os
from pathlib import Path
import sys
from typing import Any

ENVIRONMENT_KEY = "SCIPLOT_PUBLIC_INPUT_GUARD"
BOOTSTRAP_KEY = "SCIPLOT_PUBLIC_GUARD_BOOTSTRAP"
_installed: tuple[Path, ...] | None = None


def _owned_bootstrap(first: Path, child_paths: list[str], child_cwd: Path) -> bool:
    """A relocated common shim must retain actual source bytes/import owner."""
    root = Path(__file__).resolve().parents[3]
    sources = [Path(p) if Path(p).is_absolute() else child_cwd / p for p in child_paths]
    package = next((p for p in sources if (p / "sciplot_core/__init__.py").is_file()), None)
    if package is None or package.resolve() != root / "src":
        return False
    source = Path(__file__).with_name("private_observer.py")
    tree = ast.parse(source.read_bytes())
    expected = next((node.value.value for node in tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "_SITE" for target in node.targets)
                     and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)), None)
    if expected is not None and first.read_bytes() == expected.encode():
        return True
    public = Path(__file__).parent / "public_guard_bootstrap/sitecustomize.py"
    adjacent = first.parent.parent / "public_input_guard.py"
    return (first.read_bytes() == public.read_bytes() and adjacent.is_file()
            and hashlib.sha256(adjacent.read_bytes()).digest() == hashlib.sha256(Path(__file__).read_bytes()).digest())


def forbidden_roots(root: Path, environment: dict[str, str] | None = None) -> list[Path]:
    values = os.environ if environment is None else environment
    raw = Path(values.get("SCIPLOT_REFERENCE_DATA", str(root / ".local/reference_data"))).expanduser()
    if not raw.is_absolute():
        raw = root / raw
    paths = [root / "tests/fixtures" / name for name in
             ("real_world", "polymer_corpus", "archived_output_raw_data", "rendering_profiles")]
    paths.extend(raw / name for name in ("real_world", "polymer_corpus", "archived_sources"))
    # Keep lexical aliases too: a forbidden symlink must not escape the guard.
    return list(dict.fromkeys([*paths, *(path.resolve() for path in paths)]))


def install() -> None:
    """Install once from the inherited explicit root declaration."""
    global _installed
    encoded = os.environ.get(ENVIRONMENT_KEY)
    if encoded is None:
        return
    raw = json.loads(encoded)
    if not isinstance(raw, list) or not raw or any(not isinstance(p, str) or not Path(p).is_absolute() for p in raw):
        raise ValueError("Malformed public input guard roots.")
    roots = tuple(Path(p) for p in raw)
    bootstrap_binding = os.environ.get(BOOTSTRAP_KEY)
    if _installed is not None:
        if not set(_installed).issubset(roots):
            raise ValueError("An installed public input guard cannot weaken roots.")
        if roots == _installed:
            return

    def forbidden(value: Any) -> bool:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        try:
            path = Path(os.fsdecode(value)).expanduser()
            path = Path(os.path.abspath(path))
            resolved = path.resolve()
            return any(path.is_relative_to(r) or resolved.is_relative_to(r) for r in roots)
        except (OSError, ValueError, RuntimeError):
            return False

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event in {"open", "os.listdir", "os.scandir"} and args and forbidden(args[0]):
            raise PermissionError(f"Public input scope forbids private access: {os.fsdecode(args[0])}")
        if event == "subprocess.Popen":
            executable, argv, _cwd, environment = args
            arguments = list(argv) if isinstance(argv, (list, tuple)) else [argv]
            if any(forbidden(value) for value in [executable, *arguments]):
                raise PermissionError("Public input scope forbids a private child source argument.")
            from sciplot_core.verification.public_control_boundary import generated_launch_allowed
            if generated_launch_allowed(executable, arguments, _cwd, environment):
                return
            executable_path = Path(os.fsdecode(executable))
            if executable_path.name.startswith("python") or executable_path.resolve().name.startswith("python"):
                index = 1
                while index < len(arguments):
                    value = str(arguments[index])
                    if value in {"-c", "-m", "--"} or not str(value).startswith("-"):
                        break
                    if value in {"-W", "-X", "--check-hash-based-pycs"}:
                        index += 2
                        continue
                    if value.startswith(("-W", "-X")):
                        index += 1
                        continue
                    if value in {"--isolated", "--no-site", "--ignore-environment"} or any(flag in value.removeprefix("-") for flag in "SIE"):
                        raise PermissionError("A public Python child cannot disable its startup guard.")
                    index += 1
                child_environment = os.environ if environment is None else environment
                child_paths = child_environment.get("PYTHONPATH", "").split(os.pathsep)
                child_cwd = Path(_cwd or Path.cwd()).absolute()
                candidates = [(Path(p) if Path(p).is_absolute() else child_cwd / p) / "sitecustomize.py" for p in child_paths]
                first = next((p for p in candidates if p.is_file()), None)
                shadow = child_cwd / "sitecustomize.py"
                if shadow.is_file() and (first is None or shadow.resolve() != first.resolve()):
                    raise PermissionError("A public Python child cannot use an unbound startup shadow.")
                if index < len(arguments) and str(arguments[index]) not in {"-c", "-m", "--"}:
                    script = Path(str(arguments[index]))
                    script = script if script.is_absolute() else child_cwd / script
                    script_shadow = script.parent / "sitecustomize.py"
                    if script_shadow.is_file() and (first is None or script_shadow.resolve() != first.resolve()):
                        raise PermissionError("A public Python script cannot use an unbound startup shadow.")
                try:
                    binding = json.loads(child_environment.get(BOOTSTRAP_KEY, "null"))
                    supported = (bootstrap_binding is not None and first is not None
                                 and first.resolve() == Path(binding["path"]).resolve()
                                 and hashlib.sha256(first.read_bytes()).hexdigest() == binding["sha256"]
                                 and (child_environment.get(BOOTSTRAP_KEY) == bootstrap_binding
                                      or _owned_bootstrap(first, child_paths, child_cwd)))
                except (TypeError, ValueError, KeyError, OSError):
                    supported = False
                if not supported:
                    raise PermissionError("A public Python child requires its guard bootstrap.")
            if environment is not None:
                try:
                    child_roots = json.loads(environment.get(ENVIRONMENT_KEY, "null"))
                    retained = isinstance(child_roots, list) and set(raw).issubset(child_roots)
                except (ValueError, TypeError):
                    retained = False
                if not retained:
                    raise PermissionError("A public child cannot drop its input guard declaration.")

    sys.addaudithook(hook)
    _installed = roots


def configure_environment(root: Path, environment: dict[str, str], *, bootstrap: Path | None = None) -> dict[str, str]:
    result = dict(environment)
    inherited = json.loads(environment.get(ENVIRONMENT_KEY, "[]"))
    if not isinstance(inherited, list) or any(not isinstance(value, str) for value in inherited):
        raise ValueError("Malformed inherited public input guard.")
    result[ENVIRONMENT_KEY] = json.dumps(list(dict.fromkeys([*inherited, *(str(p) for p in forbidden_roots(root, environment))])))
    if bootstrap is not None:
        file = bootstrap / "sitecustomize.py"
        result[BOOTSTRAP_KEY] = json.dumps({"path": str(file.resolve()), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
        result["PYTHONPATH"] = os.pathsep.join(filter(None, [str(bootstrap), result.get("PYTHONPATH", "")]))
    return result
