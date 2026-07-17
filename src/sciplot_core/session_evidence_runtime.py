from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256

_PACKAGE_PREFIXES = (
    "sciplot_core/",
    "sciplot_gui/",
    "sciplot_recipes/",
)
_IGNORED_RUNTIME_PARTS = {
    "__pycache__",
    ".DS_Store",
    ".gitkeep",
}


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _decode_record_sha256(value: str) -> bytes:
    algorithm, separator, encoded = value.partition("=")
    if separator != "=" or algorithm != "sha256" or not encoded:
        raise ValueError(f"Unsupported wheel RECORD digest: {value!r}.")
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def _package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    locations = list(spec.submodule_search_locations or []) if spec else []
    if not locations:
        raise RuntimeError(f"Cannot locate the active {package} package.")
    return Path(locations[0]).expanduser().resolve()


def _runtime_package_inventory() -> tuple[dict[str, Path], set[str]]:
    roots = {
        package: _package_root(package)
        for package in ("sciplot_core", "sciplot_gui", "sciplot_recipes")
    }
    inventory: set[str] = set()
    for package, root in roots.items():
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix == ".pyc"
                or _IGNORED_RUNTIME_PARTS.intersection(path.parts)
            ):
                continue
            inventory.add(f"{package}/{path.relative_to(root).as_posix()}")
    return roots, inventory


def inspect_wheel_against_runtime(path: Path) -> dict[str, Any]:
    wheel = path.expanduser().resolve()
    if wheel.suffix.casefold() != ".whl" or not wheel.is_file():
        raise ValueError("Formal build artifacts must be existing .whl files.")
    try:
        archive = zipfile.ZipFile(wheel)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Build artifact is not a valid wheel ZIP: {wheel}") from exc
    with archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise ValueError(
                f"Wheel ZIP integrity failed at member {corrupt_member!r}."
            )
        names = set(archive.namelist())
        file_names = {name for name in names if not name.endswith("/")}
        record_names = sorted(
            name for name in names if name.endswith(".dist-info/RECORD")
        )
        metadata_names = sorted(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        if len(record_names) != 1 or len(metadata_names) != 1:
            raise ValueError(
                "Wheel must contain exactly one dist-info RECORD and METADATA."
            )
        record_name = record_names[0]
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
        record_by_path: dict[str, tuple[str, str]] = {}
        for row in rows:
            if len(row) != 3 or not row[0]:
                raise ValueError("Wheel RECORD contains an invalid row.")
            member, digest, size_text = row
            if member in record_by_path:
                raise ValueError(f"Wheel RECORD repeats {member!r}.")
            record_by_path[member] = (digest, size_text)
            if member not in file_names:
                raise ValueError(f"Wheel RECORD names a missing member: {member!r}.")
            content = archive.read(member)
            if size_text and len(content) != int(size_text):
                raise ValueError(f"Wheel RECORD size mismatch: {member!r}.")
            if digest:
                expected = _decode_record_sha256(digest)
                actual = hashlib.sha256(content).digest()
                if actual != expected:
                    raise ValueError(f"Wheel RECORD digest mismatch: {member!r}.")
        unrecorded = sorted(file_names - set(record_by_path))
        if unrecorded:
            raise ValueError(
                f"Wheel contains members absent from RECORD: {unrecorded[:3]!r}."
            )
        package_members = sorted(
            name
            for name in names
            if name.startswith(_PACKAGE_PREFIXES)
            and not name.endswith("/")
            and not name.endswith(".pyc")
        )
        if "sciplot_core/session_evidence.py" not in package_members:
            raise ValueError("Frozen wheel predates the session evidence contract.")
        roots, runtime_inventory = _runtime_package_inventory()
        package_member_set = set(package_members)
        missing_runtime = sorted(package_member_set - runtime_inventory)
        extra_runtime = sorted(runtime_inventory - package_member_set)
        if missing_runtime or extra_runtime:
            raise ValueError(
                "Active SciPlot package inventory differs from the frozen wheel: "
                f"missing={missing_runtime[:3]!r}, extra={extra_runtime[:3]!r}."
            )
        runtime_records: list[dict[str, Any]] = []
        for member in package_members:
            package, relative = member.split("/", 1)
            runtime_path = roots[package] / relative
            expected_bytes = archive.read(member)
            if not runtime_path.is_file():
                raise ValueError(f"Active runtime is missing wheel member {member!r}.")
            actual_hash = file_sha256(runtime_path)
            expected_hash = hashlib.sha256(expected_bytes).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Active runtime differs from frozen wheel at {member!r}."
                )
            runtime_records.append(
                {
                    "path": member,
                    "size_bytes": runtime_path.stat().st_size,
                    "sha256": actual_hash,
                }
            )
        metadata_text = archive.read(metadata_names[0]).decode(
            "utf-8",
            errors="replace",
        )
        metadata_lines = {
            key.strip(): value.strip()
            for line in metadata_text.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
            if key.strip() in {"Name", "Version"}
        }
    return {
        "kind": "sciplot_frozen_wheel_runtime_match",
        "version": 1,
        "wheel": str(wheel),
        "wheel_sha256": file_sha256(wheel),
        "wheel_size_bytes": wheel.stat().st_size,
        "distribution": {
            "name": metadata_lines.get("Name"),
            "version": metadata_lines.get("Version"),
        },
        "record_member": record_name,
        "record_verified": True,
        "package_member_count": len(package_members),
        "package_tree_sha256": _canonical_sha256(runtime_records),
        "runtime_import_roots": {
            package: str(root) for package, root in sorted(roots.items())
        },
        "runtime_content_matches_wheel": True,
    }


def _tree_runtime_fingerprint(
    root: Path,
    *,
    label: str,
    suffixes: set[str] | None = None,
) -> dict[str, Any]:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"{label} root not found: {resolved}")
    records: list[dict[str, Any]] = []
    for path in sorted(resolved.rglob("*")):
        if (
            not path.is_file()
            or _IGNORED_RUNTIME_PARTS.intersection(path.parts)
            or (suffixes is not None and path.suffix.casefold() not in suffixes)
        ):
            continue
        records.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    if not records:
        raise ValueError(f"{label} runtime inventory is empty: {resolved}")
    return {
        "root": str(resolved),
        "file_count": len(records),
        "tree_sha256": _canonical_sha256(records),
    }


def _qt_binding_runtime_fingerprint() -> dict[str, Any]:
    package = "PyQt6"
    spec = importlib.util.find_spec(package)
    locations = list(spec.submodule_search_locations or []) if spec else []
    if not locations:
        raise RuntimeError(f"Cannot locate the active {package} runtime.")
    root = Path(locations[0]).expanduser().resolve()
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or path.is_symlink()
            or _IGNORED_RUNTIME_PARTS.intersection(path.parts)
        ):
            continue
        relative = path.relative_to(root).as_posix()
        name = path.name.casefold()
        binary_suffix = (
            path.suffix.casefold()
            in {
                ".dll",
                ".dylib",
                ".pyd",
                ".so",
            }
            or ".so." in name
        )
        framework_binary = (
            ".framework/Versions/" in relative
            and not path.suffix
            and path.name.startswith("Qt")
        )
        if binary_suffix or framework_binary:
            candidates.append(path)
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
        for path in sorted(candidates)
    ]
    if not records:
        raise ValueError(f"Active {package} runtime inventory is empty.")
    return {
        "package": package,
        "root": str(root),
        "file_count": len(records),
        "tree_sha256": _canonical_sha256(records),
    }


def _macos_runtime_search_roots(
    binary: Path,
    *,
    qt_binding_root: Path,
) -> list[Path]:
    completed = subprocess.run(
        ["otool", "-l", str(binary)],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Could not inspect macOS runtime paths for {binary}.")
    raw_roots: list[str] = []
    lines = completed.stdout.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "cmd LC_RPATH":
            continue
        for candidate in lines[index + 1 : index + 6]:
            stripped = candidate.strip()
            if stripped.startswith("path "):
                raw_roots.append(stripped[5:].split(" (offset", 1)[0])
                break
    raw_roots.extend(
        value for value in os.environ.get("DYLD_FRAMEWORK_PATH", "").split(":") if value
    )
    raw_roots.append(str(qt_binding_root / "Qt6" / "lib"))
    resolved: list[Path] = []
    for value in raw_roots:
        if value.startswith("@loader_path/"):
            path = binary.parent / value.removeprefix("@loader_path/")
        elif value == "@loader_path":
            path = binary.parent
        elif value.startswith("@executable_path/"):
            path = Path(sys.executable).resolve().parent / value.removeprefix(
                "@executable_path/"
            )
        elif value.startswith("@"):
            continue
        else:
            path = Path(value).expanduser()
        normalized = path.resolve()
        if normalized not in resolved:
            resolved.append(normalized)
    return resolved


def _linked_qt_binaries(
    veusz_root: Path,
    *,
    qt_binding_root: Path,
) -> dict[str, Any]:
    if sys.platform != "darwin":
        return {
            "platform": sys.platform,
            "binaries": [],
            "tree_sha256": _canonical_sha256([]),
        }
    required_modules: list[Path] = []
    for module in (
        "QtCore",
        "QtGui",
        "QtWidgets",
        "QtSvg",
        "QtPrintSupport",
        "QtSvgWidgets",
    ):
        matches = sorted(qt_binding_root.glob(f"{module}.*.so"))
        if len(matches) != 1:
            raise ValueError(
                f"Expected one active PyQt6 {module} binary; found {len(matches)}."
            )
        required_modules.append(matches[0])
    helper_root = veusz_root / "veusz" / "helpers"
    helpers = sorted(helper_root.glob("*.so"))
    link_sources = [*required_modules, *helpers]
    dependencies: set[Path] = set()
    unresolved: set[str] = set()
    for source in link_sources:
        completed = subprocess.run(
            ["otool", "-L", str(source)],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Could not inspect linked Qt runtime for {source}.")
        search_roots = _macos_runtime_search_roots(
            source,
            qt_binding_root=qt_binding_root,
        )
        source_dependencies = 0
        for line in completed.stdout.splitlines()[1:]:
            candidate = line.strip().split(" ", 1)[0]
            if "Qt" not in candidate:
                continue
            resolved_candidates: list[Path] = []
            if candidate.startswith("@rpath/"):
                relative = candidate.removeprefix("@rpath/")
                resolved_candidates.extend(root / relative for root in search_roots)
            elif candidate.startswith("@loader_path/"):
                relative = candidate.removeprefix("@loader_path/")
                resolved_candidates.append(source.parent / relative)
            elif candidate.startswith("/"):
                resolved_candidates.append(Path(candidate).expanduser())
            resolved = next(
                (path.resolve() for path in resolved_candidates if path.is_file()),
                None,
            )
            if resolved is None:
                unresolved.add(f"{source.name}: {candidate}")
            else:
                dependencies.add(resolved)
                source_dependencies += 1
        if source in required_modules and source_dependencies == 0:
            unresolved.add(f"{source.name}: no Qt dependency resolved")
    if unresolved:
        raise ValueError(
            f"Could not resolve linked Qt runtime binaries: {sorted(unresolved)[:3]!r}."
        )
    if not dependencies:
        raise ValueError("No linked Qt runtime binaries were resolved.")
    records = [
        {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
        for path in sorted(dependencies)
    ]
    return {
        "platform": sys.platform,
        "binaries": records,
        "tree_sha256": _canonical_sha256(records),
    }


def _dependency_versions() -> dict[str, Any]:
    records = sorted(
        {
            (
                str(distribution.metadata.get("Name") or "").casefold(),
                str(distribution.version or ""),
            )
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )
    return {
        "count": len(records),
        "sha256": _canonical_sha256(records),
    }


def runtime_identity(
    *,
    veusz_root: Path,
    veusz_upstream_commit: str,
) -> dict[str, Any]:
    veusz = _tree_runtime_fingerprint(
        veusz_root / "veusz",
        label="Veusz",
        suffixes={
            ".py",
            ".pyx",
            ".so",
            ".dylib",
            ".json",
            ".xml",
            ".txt",
            ".svg",
        },
    )
    qt_binding = _qt_binding_runtime_fingerprint()
    payload = {
        "veusz_upstream_commit": veusz_upstream_commit,
        "veusz": veusz,
        "qt_binding": qt_binding,
        "linked_qt_binaries": _linked_qt_binaries(
            veusz_root,
            qt_binding_root=Path(str(qt_binding["root"])),
        ),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": str(Path(sys.executable).expanduser().resolve()),
        },
        "platform": platform.platform(),
        "dependencies": _dependency_versions(),
    }
    payload["identity_sha256"] = _canonical_sha256(payload)
    return payload


def freeze_runtime_wheel(
    *,
    repo_root: Path,
    output_root: Path,
    veusz_root: Path,
    veusz_upstream_commit: str,
) -> dict[str, Any]:
    repo = repo_root.expanduser().resolve()
    output = output_root.expanduser().resolve()
    if not (repo / "pyproject.toml").is_file():
        raise FileNotFoundError(f"SciPlot pyproject.toml not found: {repo}")

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Git {' '.join(args)} failed: {completed.stderr.strip()}"
            )
        return completed.stdout.strip()

    commit = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    dirty = git("status", "--porcelain", "--untracked-files=normal")
    if dirty:
        raise ValueError("Freeze-build requires a clean committed SciPlot checkout.")
    output.mkdir(parents=True, exist_ok=True)
    candidate_root = output / commit[:12]
    candidate_root.mkdir(parents=True, exist_ok=True)

    def require_unchanged_checkout() -> None:
        if (
            git("rev-parse", "HEAD") != commit
            or git("branch", "--show-current") != branch
            or git("status", "--porcelain", "--untracked-files=normal")
        ):
            raise RuntimeError(
                "SciPlot checkout changed while the frozen wheel was built."
            )

    build_env = os.environ.copy()
    build_env["SOURCE_DATE_EPOCH"] = git("show", "-s", "--format=%ct", commit)
    with tempfile.TemporaryDirectory(
        prefix="sciplot_freeze_build_",
        dir=output,
    ) as temporary:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(repo),
                "--no-deps",
                "--no-build-isolation",
                "-w",
                temporary,
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
            env=build_env,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "SciPlot freeze-build failed: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        wheels = sorted(Path(temporary).glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(
                f"Freeze-build produced {len(wheels)} wheel artifacts; expected one."
            )
        built = wheels[0]
        inspect_wheel_against_runtime(built)
        require_unchanged_checkout()
        destination = candidate_root / built.name
        staged = candidate_root / f".{built.name}.{os.getpid()}.tmp"
        if staged.exists():
            staged.unlink()
        shutil.copy2(built, staged)
        if destination.exists():
            if file_sha256(destination) != file_sha256(staged):
                staged.unlink()
                raise FileExistsError(
                    "A different frozen wheel already exists for this commit: "
                    f"{destination}"
                )
            staged.unlink()
        else:
            os.replace(staged, destination)
    require_unchanged_checkout()
    contract = inspect_wheel_against_runtime(destination)
    frozen_runtime = runtime_identity(
        veusz_root=veusz_root,
        veusz_upstream_commit=veusz_upstream_commit,
    )
    require_unchanged_checkout()
    result = {
        "kind": "sciplot_frozen_candidate_build",
        "version": 1,
        "status": "ready",
        "generated_at": datetime.now(UTC).isoformat(),
        "repo": str(repo),
        "git_commit": commit,
        "git_branch": branch or None,
        "worktree_clean": True,
        "artifact": {
            "path": str(destination),
            "size_bytes": destination.stat().st_size,
            "sha256": file_sha256(destination),
        },
        "runtime_match": contract,
        "runtime_identity": frozen_runtime,
    }
    manifest = candidate_root / "frozen_build.json"
    temporary_manifest = candidate_root / ".frozen_build.json.tmp"
    temporary_manifest.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest)
    result["manifest"] = str(manifest)
    return result


__all__ = [
    "freeze_runtime_wheel",
    "inspect_wheel_against_runtime",
    "runtime_identity",
]
