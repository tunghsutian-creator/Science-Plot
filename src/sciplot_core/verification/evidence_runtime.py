"""Discover the real local Python/Qt/native/font inputs for opt-in evidence.

No persisted metadata cache: every capture rediscovers membership and hashes all
declared bytes. Apple sealed system libraries use the OS build identity; all
non-system Mach-O dependencies must resolve to actual bound files.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import platform
import re
import site
import subprocess
import sys
import sysconfig
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.verification.evidence_identity import digest

QT_MODULES = frozenset({"QtCore", "QtGui", "QtWidgets", "QtPrintSupport", "QtSvg", "QtSvgWidgets", "sip", "uic"})
QT_PLUGIN_KINDS = frozenset({"platforms", "imageformats", "iconengines", "printsupport", "styles", "platforminputcontexts"})


def qt_import_bindings(roots: list[Path]) -> dict[str, str]:
    """Keep the reviewed Qt entrypoint policy bound to current project imports."""
    bindings = {}
    for root in roots:
        for path in root.rglob("*.py"):
            bindings[digest(str(path.resolve()))] = file_sha256(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "PyQt6":
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PyQt6."):
                    names.append(node.module.split(".")[1])
                elif isinstance(node, ast.Import):
                    names.extend(alias.name.split(".")[1] for alias in node.names if alias.name.startswith("PyQt6."))
                elif isinstance(node, ast.Call) and node.args and (
                    (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
                    or (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                ):
                    target = node.args[0]
                    if isinstance(target, ast.Constant) and isinstance(target.value, str) and target.value.startswith("PyQt6."):
                        names.append(target.value.split(".")[1])
            if any(name and name not in QT_MODULES for name in names):
                raise ValueError("project Qt imports exceed the reviewed native entrypoints")
    return bindings


def _native_entrypoint(name: str) -> bool:
    path = Path(name)
    if "/PyQt6/" in name or "/Qt6/" in name:
        if path.suffix == ".so" and path.name.split(".")[0] in QT_MODULES:
            return True
        marker = "/Qt6/plugins/"
        return marker in name and name.split(marker, 1)[1].split("/")[0] in QT_PLUGIN_KINDS and path.suffix == ".dylib"
    framework = str(path).split(".framework/Versions/", 1)
    return path.suffix in {".so", ".dylib"} or (len(framework) == 2 and path.name == Path(framework[0]).name)


def _expand_loader(path: str, binary: Path, executable: Path) -> Path:
    return Path(path.replace("@loader_path", str(binary.parent))
                .replace("@executable_path", str(executable.parent)))


def native_dependencies(files: list[str], *, executable: Path,
                        environment: dict[str, str], bindings: dict[str, str] | None = None,
                        aliases: dict[str, str] | None = None) -> list[Path]:
    """Resolve the linked non-system native closure, rejecting unknown loaders."""
    if sys.platform != "darwin":
        raise ValueError("default native evidence currently requires macOS")
    if any(environment.get(key) for key in environment
           if key.startswith(("DYLD_", "LD_")) and key != "DYLD_FRAMEWORK_PATH"):
        raise ValueError("native loader overrides have no reviewed closure policy")
    queue = [Path(name) for name in files if _native_entrypoint(name)]
    queue.append(executable.resolve())
    known = {Path(name).resolve() for name in files}
    visited: set[Path] = set()
    found: set[Path] = set()
    # Loader-inherited rpaths may point to other already bound Qt framework dirs.
    framework_roots = {Path(str(path).split(".framework/", 1)[0] + ".framework").parent for path in known
                       if ".framework/Versions/" in str(path) and path.is_file()}
    while queue:
        binary = queue.pop().resolve()
        if binary in visited:
            continue
        visited.add(binary)
        with binary.open("rb") as stream:
            magic = stream.read(4)
        if magic not in {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}:
            continue
        before = file_sha256(binary)
        output = subprocess.run(["/usr/bin/otool", "-L", str(binary)],
                                capture_output=True, text=True, check=True).stdout
        loads = subprocess.run(["/usr/bin/otool", "-l", str(binary)],
                               capture_output=True, text=True, check=True).stdout
        rpaths = re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset", loads)
        self_names = set(re.findall(r"cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.*?) \(offset", loads))
        if before != file_sha256(binary):
            raise ValueError("native input changed during dependency discovery")
        if bindings is not None:
            bindings[digest(str(binary))] = before
        for line in output.splitlines()[1:]:
            if not line.startswith("\t"):
                continue  # Universal Mach-O repeats an architecture header.
            name = line.strip().split(" (compatibility", 1)[0]
            if name in self_names or not name:
                continue
            if name.startswith(("/usr/lib/", "/System/Library/")):
                continue
            if name.startswith("@rpath/"):
                suffix = name.removeprefix("@rpath/")
                candidates = {_expand_loader(path, binary, executable) / suffix for path in rpaths}
                if not any(path.is_file() for path in candidates):
                    candidates.update(root / suffix for root in framework_roots)
            else:
                candidates = {_expand_loader(name, binary, executable)}
            resolved = {path.resolve() for path in candidates if path.is_file()}
            if len(resolved) != 1:
                raise ValueError(f"native dependency is unresolved or ambiguous: {binary.name} -> {Path(name).name}")
            dependency = resolved.pop()
            logical = [path for path in candidates if path.is_file() and path.resolve() == dependency]
            # Missing loader candidates can become preferred without old bytes changing.
            found.update(candidates)
            if aliases is not None:
                for candidate in candidates:
                    aliases[digest(str(candidate.absolute()))] = digest(str(candidate.resolve()) if candidate.exists() else "missing")
            queue.extend(logical)
    return sorted(found)


def runtime_inputs(*, repo_root: Path, environment: dict[str, str]) -> tuple[dict[str, list[Path]], dict[str, Any]]:
    """Return actual runtime paths, never a user-supplied applicability claim."""
    if any(environment.get(key) for key in ("QML_IMPORT_PATH", "QML2_IMPORT_PATH")):
        raise ValueError("QML loader overrides have no reviewed closure policy")
    if environment.get("PYTHONHOME") or environment.get("PYTHONUSERBASE"):
        raise ValueError("custom Python runtime roots have no reviewed closure policy")
    runtime_root = Path(environment.get("SCIPLOT_RUNTIME_REPO", str(repo_root))).expanduser()
    veusz = Path(environment.get("SCIPLOT_VEUSZ_ROOT", str(runtime_root / "third_party/veusz"))).expanduser()
    python = [Path(sys.executable), Path(sysconfig.get_path("stdlib")),
              Path(sys.base_prefix) / "Python", Path(sys.prefix) / "pyvenv.cfg"]
    dependencies = [Path(path) for path in site.getsitepackages()]
    if site.ENABLE_USER_SITE:
        dependencies.append(Path(site.getusersitepackages()))
    # Bind editable-install .pth additions and any explicitly configured imports.
    search = [Path(path).absolute() for path in [*sys.path, *environment.get("PYTHONPATH", "").split(os.pathsep)] if path]
    for path in search:
        if path.resolve() == repo_root:
            continue  # cwd is covered by trusted repository domains, not .git/outputs.
        if not any(path == root or path.is_relative_to(root) for root in [*python, *dependencies]):
            dependencies.append(path)
    qt = [path / "PyQt6" for path in dependencies if (path / "PyQt6").is_dir()]
    plugins = [Path(value).expanduser() for value in environment.get("QT_PLUGIN_PATH", "").split(os.pathsep) if value]
    if any(not path.is_dir() for path in plugins):
        raise ValueError("configured Qt plugin search root is unavailable")
    qt.extend(plugins)
    if not qt or not veusz.is_dir():
        raise ValueError("real Qt/Veusz runtime is unavailable")
    frameworks = [Path(value).expanduser() for value in environment.get("DYLD_FRAMEWORK_PATH", "").split(os.pathsep) if value]
    if any(not path.is_dir() for path in frameworks):
        raise ValueError("configured framework search root is unavailable")
    fonts = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
    for key in ("QT_QPA_FONTDIR", "FONTCONFIG_PATH", "FONTCONFIG_FILE"):
        fonts.extend(Path(path).expanduser() for path in environment.get(key, "").split(os.pathsep) if path)
    if not any(path.exists() for path in fonts):
        raise ValueError("actual font search roots are unavailable")
    system = Path("/System/Library/CoreServices/SystemVersion.plist")
    if not system.is_file():
        raise ValueError("sealed system build identity is unavailable")
    domains = {"python": python, "dependencies": dependencies, "qt": qt,
               "native": [veusz, system, Path("/usr/bin/otool"), *frameworks, *plugins], "fonts": fonts}
    return domains, {"system": platform.platform(), "machine": platform.machine(),
                     "python_version": sys.version, "system_native_policy": "apple-sealed-os-build-v1"}
