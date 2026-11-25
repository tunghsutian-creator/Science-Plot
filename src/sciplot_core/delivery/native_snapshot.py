"""Capture and install exact, independently reopenable native figure snapshots.

The callers own selected science/revision, layout and persisted receipts. This
module owns the byte operations shared by both ordered paper publishers.
"""

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any

from sciplot_core.delivery import install
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.source_update_files import file_inventory
from sciplot_core.veusz_runtime import veusz_worker_environment


class NativeSnapshotError(ValueError):
    """The native worker could not establish an independent saved snapshot."""


class SnapshotSealChanged(NativeSnapshotError):
    """Bytes at a capture, relocation or installation boundary did not match."""


class SnapshotImportUnselected(SnapshotSealChanged):
    """Native Save consumed a linked import not admitted for this handoff."""


def _native(*arguments: str) -> Any:
    result = subprocess.run([sys.executable, "-m", "sciplot_core.task_paper_native", *arguments],
                            env=veusz_worker_environment(), capture_output=True, text=True,
                            timeout=120, check=False)
    if result.returncode:
        raise NativeSnapshotError(result.stderr[-2000:])
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise NativeSnapshotError("The native worker did not return its expected evidence.") from exc


def _require_file(path: Path, expected: str) -> None:
    if not path.is_file() or file_sha256(canonical_path(path)) != expected:
        raise SnapshotSealChanged(f"The sealed snapshot member is missing or changed: {path}")


def capture_native(
    source: Path, target: Path, imports: Path, *, original_sha256: str,
    selected_imports: Mapping[str, str],
) -> dict[str, Any]:
    """Native Save the exact signed document and admit only selected import bytes."""
    try:
        result = _native("save", str(source), str(target), "--imports", str(imports),
                         "--expected-sha256", original_sha256)
    except NativeSnapshotError:
        # Distinguish original drift from a worker failure. On success the
        # child already checked the source before its native open.
        _require_file(source, original_sha256)
        raise
    if (not isinstance(result, dict) or result.get("status") != "passed"
            or not isinstance(result.get("native_state_sha256"), str)
            or result.get("native_state_sha256") != result.get("reopened_native_state_sha256")
            or not isinstance(result.get("portable_sha256"), str)
            or not isinstance(result.get("imports"), list)):
        raise NativeSnapshotError("Native Save did not preserve the selected saved figure.")
    if result.get("original_sha256") != original_sha256:
        raise SnapshotSealChanged("Native Save did not consume the exact selected VSZ bytes.")
    _require_file(source, original_sha256)
    _require_file(target, result["portable_sha256"])
    for entry in result["imports"]:
        if selected_imports.get(entry["source"]) != entry["sha256"]:
            raise SnapshotImportUnselected("Native Save consumed a linked source outside the selected byte seals.")
    return result


def copy_sealed_file(source: Path, target: Path, expected: str) -> None:
    """Copy an existing export; never rerender or replace a populated target."""
    try:
        source, target = canonical_path(source), canonical_path(target)
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as original:
            if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
                raise SnapshotSealChanged(f"The sealed snapshot source is not a regular file: {source}")
            hasher = hashlib.sha256()
            with target.open("xb") as copied:
                while chunk := original.read(1024 * 1024):
                    hasher.update(chunk)
                    copied.write(chunk)
            if hasher.hexdigest() != expected:
                raise SnapshotSealChanged(f"The selected snapshot source changed during copy: {source}")
        shutil.copystat(source, target, follow_symlinks=False)
        _require_file(target, expected)
    except OSError as exc:
        raise SnapshotSealChanged(f"Cannot copy the sealed snapshot member: {source} -> {target}") from exc


def require_inventory(root: Path, expected: Mapping[str, str]) -> None:
    if file_inventory(root) != expected:
        raise SnapshotSealChanged(f"The sealed snapshot attempt changed: {root}")


def _member(root: Path, name: str) -> Path:
    path = canonical_path(root / name)
    if not path.is_relative_to(root) or path == root:
        raise SnapshotSealChanged(f"A snapshot path escapes its package: {name}")
    return path


def stage_native(
    attempt: Path, candidate: Path, files: Mapping[str, str], *,
    layout: Mapping[str, str], assembled: dict[str, str], stem: str, portable: Mapping[str, Any],
) -> None:
    """Relocate one sealed attempt while preserving its exact native import paths."""
    require_inventory(attempt, files)
    (candidate / "data" / "imports" / stem).mkdir(parents=True, exist_ok=True)
    for name, destination in layout.items():
        source, target = _member(attempt, name), _member(candidate, destination)
        expected = files[name]
        if destination in assembled:
            # Managed figures can legitimately share an identical original
            # data object. No export, spec or editable filename is shared.
            if not destination.startswith("data/originals/") or assembled[destination] != expected:
                raise SnapshotSealChanged(f"Selected figures collide at {destination}.")
            _require_file(target, expected)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_sealed_file(source, target, expected)
            assembled[destination] = expected
    editable = f"project/{stem}.vsz"
    _verify_relocated_native(candidate, editable, portable, assembled)


def _verify_relocated_native(
    root: Path, editable: str, portable: Mapping[str, Any], assembled: Mapping[str, str],
) -> None:
    """Reopen relocated exact VSZ and observe every import inside this package."""
    path = _member(root, editable)
    expected_sha256 = portable["portable_sha256"]
    if assembled.get(editable) != expected_sha256:
        raise SnapshotSealChanged("The relocated editable figure is not the sealed portable VSZ.")
    imports = {}
    for entry in portable["imports"]:
        relative, sha256 = entry["relative_path"], entry["sha256"]
        if assembled.get(relative) != sha256:
            raise SnapshotSealChanged("A relocated native import is not sealed with the figure.")
        imports[str(_member(root, relative))] = sha256
    opened = _native("inspect", str(path), "--expected-sha256", expected_sha256)
    if not isinstance(opened, list) or {item["path"]: item["sha256"] for item in opened} != imports:
        raise SnapshotSealChanged("The relocated native figure does not open with its exact packaged imports.")
    for name, sha256 in imports.items():
        _require_file(Path(name), sha256)
    _require_file(path, expected_sha256)


def stage_standalone_native(source: Path, target: Path, scratch: Path, *, original_sha256: str) -> dict[str, Any]:
    """Stage only the saved VSZ in its own directory and reopen it there."""
    saved = scratch / target.name
    portable = capture_native(source, saved, scratch / "imports",
                              original_sha256=original_sha256, selected_imports={})
    expected = portable["portable_sha256"]
    copy_sealed_file(saved, target, expected)
    _verify_relocated_native(target.parent, target.name, portable, {target.name: expected})
    return portable


def publish_snapshot(
    candidate: Path, destination: Path, *, assembled: Mapping[str, str],
    freeze: Callable[[dict[str, str]], None], validate: Callable[[], None],
) -> dict[str, str]:
    """Name the complete candidate before atomic non-replacing installation."""
    files = file_inventory(candidate)
    if any(files.get(name) != sha256 for name, sha256 in assembled.items()):
        raise SnapshotSealChanged("The publication candidate differs from its assembled figure seals.")
    freeze(files)
    validate()
    require_inventory(candidate, files)
    install.install_new_delivery(candidate, destination)
    validate()
    require_inventory(destination, files)
    return files


def installed_snapshot_matches(
    destination: Path, files: Mapping[str, str], *, pending_candidate: Path | None,
    inventory: Callable[[Path], dict[str, str]] = file_inventory,
) -> bool:
    """A pending candidate can only recover an install that consumed its stage."""
    if pending_candidate is not None and (pending_candidate.exists() or pending_candidate.is_symlink()):
        return False
    return bool(files) and inventory(destination) == files
