"""Close and relocate Mach-O dependencies; fail on every unresolved reference."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

MAGICS = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def is_macho(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    with path.open("rb") as stream:
        return stream.read(4) in MAGICS


def system_library(value: str) -> bool:
    return value.startswith(("/usr/lib/", "/System/Library/", "/Library/Apple/System/Library/"))


def load_commands(path: Path) -> tuple[list[str], list[str], str | None]:
    text = subprocess.check_output(["/usr/bin/otool", "-l", str(path)], text=True)
    dependencies: list[str] = []
    rpaths: list[str] = []
    identity = None
    command = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("cmd "):
            command = line[4:]
        elif line.startswith("name "):
            value = line[5:].rsplit(" (offset ", 1)[0]
            if command == "LC_ID_DYLIB":
                identity = value
            elif command in {"LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB", "LC_LOAD_UPWARD_DYLIB"}:
                dependencies.append(value)
        elif command == "LC_RPATH" and line.startswith("path "):
            rpaths.append(line[5:].rsplit(" (offset ", 1)[0])
    return dependencies, rpaths, identity


def relocated_reference(binary: Path, dependency: Path) -> str:
    return "@loader_path/" + os.path.relpath(dependency, binary.parent)


class Relocator:
    def __init__(self, resources: Path, roots: dict[Path, Path]):
        self.resources = resources
        self.roots = roots
        self.qt_lib = next((resources / "runtime/lib").glob("python*/site-packages/PyQt6/Qt6/lib"))
        self.extra = resources / "runtime" / "native"
        self.extra.mkdir()
        self.records: list[dict[str, str | int]] = []

    def copy_native_licenses(self, source: Path) -> None:
        for parent in source.parents:
            if not (parent / ".brew").is_dir():
                continue
            destination = self.resources / "licenses" / (parent.parent.name + "-" + parent.name)
            for entry in parent.iterdir():
                if entry.is_file() and entry.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE")):
                    destination.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(entry, destination / entry.name)
            break

    def source_for(self, destination: Path) -> Path:
        for source, target in sorted(self.roots.items(), key=lambda item: len(str(item[1])), reverse=True):
            if destination == target:
                return source
            if destination.is_relative_to(target):
                return source / destination.relative_to(target)
        return destination

    def mapped(self, source: Path) -> Path | None:
        source = source.resolve()
        for root, target in sorted(self.roots.items(), key=lambda item: len(str(item[0])), reverse=True):
            if source == root:
                return target
            if source.is_relative_to(root):
                candidate = target / source.relative_to(root)
                if candidate.exists():
                    return candidate
        return None

    def dependency(self, name: str, origin: Path, rpaths: list[str]) -> Path:
        # Every Qt module, including locally built Veusz helpers, uses one Qt build.
        match = re.search(r"(Qt[^/]+\.framework/.+)$", name)
        if match:
            candidate = self.qt_lib / match.group(1)
            if candidate.exists():
                return candidate
        candidates: list[Path] = []
        if name.startswith("@loader_path/"):
            candidates.append(origin.parent / name.removeprefix("@loader_path/"))
        elif name.startswith("@rpath/"):
            suffix = name.removeprefix("@rpath/")
            for rpath in rpaths:
                value = rpath.replace("@loader_path", str(origin.parent))
                if not value.startswith("@"):
                    candidates.append(Path(value) / suffix)
            candidates.extend([origin.parent / suffix, self.qt_lib / suffix])
        elif name.startswith("/"):
            candidates.append(Path(name))
        else:
            raise ValueError(f"Unsupported dependency {name!r} in {origin}")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            source = candidate.resolve()
            if source.is_relative_to(self.resources):
                return source
            mapped = self.mapped(source)
            if mapped is not None:
                return mapped
            token = hashlib.sha256(str(source).encode()).hexdigest()[:12]
            destination = self.extra / token / source.name
            destination.parent.mkdir(exist_ok=True)
            shutil.copy2(source, destination)
            self.copy_native_licenses(source)
            self.roots[source] = destination
            return destination
        raise ValueError(f"Unresolved dependency {name!r} in {origin}; searched {candidates}")

    def run(self) -> list[dict[str, str | int]]:
        pending = sorted(path for path in self.resources.rglob("*") if is_macho(path))
        seen: set[Path] = set()
        while pending:
            binary = pending.pop()
            if binary in seen:
                continue
            seen.add(binary)
            dependencies, rpaths, identity = load_commands(binary)
            original = self.source_for(binary)
            source_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
            arguments: list[str] = []
            for name in dependencies:
                if system_library(name):
                    continue
                target = self.dependency(name, original, rpaths)
                pending.append(target)
                reference = relocated_reference(binary, target)
                if len(reference) > len(name):
                    # Locally compiled helpers may have no load-command padding.
                    # A short sibling link avoids requiring a compiler on rebuild.
                    token = hashlib.sha256(str(target.relative_to(self.resources)).encode()).hexdigest()[:10]
                    alias = binary.parent / (".sl_" + token)
                    if not alias.exists():
                        alias.symlink_to(os.path.relpath(target, binary.parent))
                    reference = "@loader_path/" + alias.name
                arguments.extend(["-change", name, reference])
            if identity:
                arguments.extend(["-id", "@loader_path/" + binary.name])
            for rpath in set(rpaths):
                if rpath.startswith("/") and not system_library(rpath):
                    arguments.extend(["-delete_rpath", rpath])
            if arguments:
                binary.chmod(binary.stat().st_mode | 0o200)
                subprocess.run(["/usr/bin/install_name_tool", *arguments, str(binary)], check=True, capture_output=True)
                subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(binary)], check=True, capture_output=True)
            self.records.append({
                "path": str(binary.relative_to(self.resources)),
                "dependencies": len(dependencies),
                "source_sha256": source_hash,
                "bundled_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            })
        audit_runtime(self.resources)
        return sorted(self.records, key=lambda item: str(item["path"]))


def audit_runtime(resources: Path) -> dict[str, int]:
    count = 0
    for binary in resources.rglob("*"):
        if not is_macho(binary):
            continue
        count += 1
        dependencies, rpaths, _ = load_commands(binary)
        for name in dependencies:
            if system_library(name):
                continue
            if not name.startswith("@loader_path/"):
                raise ValueError(f"External/unresolved dependency remains: {binary}: {name}")
            target = (binary.parent / name.removeprefix("@loader_path/")).resolve()
            if not target.is_relative_to(resources) or not target.is_file():
                raise ValueError(f"Dependency escapes bundle or is absent: {binary}: {name}")
        if any(path.startswith("/") and not system_library(path) for path in rpaths):
            raise ValueError(f"External runtime search path remains: {binary}")
    return {"mach_o_count": count, "external_non_system_dependencies": 0}
