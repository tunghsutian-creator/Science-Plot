"""Stage, validate and replace a visible package without losing prior work."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from tempfile import mkdtemp
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers.delivery_binding import delivery_binding_from_content
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_LAUNCHER,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
)
from sciplot_core.delivery.package_validation import verify_delivery_package


def _package_snapshot(root: Path) -> dict[str, str]:
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError(
            "The visible SciPlot output must be a dedicated real directory."
        )
    if not root.exists():
        return {}
    allowed = {
        DELIVERY_DATA_DIR,
        DELIVERY_PDF_DIR,
        DELIVERY_TIFF_DIR,
        DELIVERY_PROJECT_DIR,
        DELIVERY_LAUNCHER,
    }
    unknown = {item.name for item in root.iterdir()} - allowed
    if unknown:
        raise ValueError(
            "Refusing to replace a non-dedicated SciPlot output directory; "
            f"unexpected entries: {', '.join(sorted(unknown))}."
        )
    snapshot = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(
                f"Refusing to replace a delivery containing a symbolic link: {path}"
            )
        if path.is_file():
            digest = existing_file_sha256(path)
            if not digest:
                raise RuntimeError(
                    f"Cannot establish the existing delivery snapshot: {path}"
                )
            snapshot[str(path.relative_to(root))] = digest
    return snapshot


def _protect_editable_documents(root: Path, candidate: Path) -> None:
    if not root.exists():
        return
    existing = sorted(
        path for path in (root / DELIVERY_PROJECT_DIR).rglob("*") if path.is_file()
    )
    launcher = root / DELIVERY_LAUNCHER
    try:
        binding = (
            delivery_binding_from_content(launcher.read_text(encoding="utf-8"))
            if launcher.is_file()
            else None
        )
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"Cannot verify the prior delivery at {root}; all files were preserved."
        ) from exc
    baseline = dict(binding.documents) if binding is not None else {}
    candidates = sorted(
        path for path in (candidate / DELIVERY_PROJECT_DIR).rglob("*") if path.is_file()
    )
    # A single-figure package may change its filename with the new run number.
    # Exact reconciled bytes remain safe when the sole editable file is retained
    # under that new name; no unknown or additional document gains this exception.
    reconciled_single_hash = (
        existing_file_sha256(candidates[0])
        if len(existing) == len(candidates) == len(baseline) == 1
        and str(existing[0].relative_to(root / DELIVERY_PROJECT_DIR)) in baseline
        and candidates[0].suffix.casefold() == ".vsz"
        else None
    )
    conflicts = []
    for document in existing:
        # Legacy packages have no persisted baseline. Only identical replacement
        # bytes are demonstrably safe; an unknown revision must remain untouched.
        name = str(document.relative_to(root / DELIVERY_PROJECT_DIR))
        expected = baseline.get(name)
        candidate_hash = existing_file_sha256(candidate / DELIVERY_PROJECT_DIR / name)
        current = existing_file_sha256(document)
        if not current or current not in {
            expected,
            candidate_hash,
            reconciled_single_hash,
        }:
            conflicts.append(str(document))
    if conflicts:
        raise ValueError(
            "Delivery contains edited or unverified Veusz documents; no files were replaced: "
            + ", ".join(conflicts)
            + ". Keep these edits by saving the visible package under another name, "
            "or incorporate them into the managed project before exporting again."
        )


def _relocate_value(value: Any, source: Path, target: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _relocate_value(item, source, target) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_relocate_value(item, source, target) for item in value]
    if isinstance(value, str) and value.startswith(str(source) + "/"):
        return str(target / Path(value).relative_to(source))
    if value == str(source):
        return str(target)
    return value


def _relocate_record(
    record: dict[str, Any],
    source: Path,
    target: Path,
) -> dict[str, Any]:
    return {
        key: _relocate_value(value, source, target) for key, value in record.items()
    }


def publish_delivery_transaction(
    *,
    root: Path,
    output_dir: Path,
    manifest: dict[str, Any],
    build: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    """Retain failed diagnostics and install only a complete verified package."""
    before = _package_snapshot(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(mkdtemp(prefix=f".{root.name}.sciplot-stage-", dir=root.parent))
    backup = root.with_name(f".{root.name}.sciplot-previous-{uuid4().hex}")
    installed = False
    moved_previous = False
    try:
        record = build(stage)
        if record.get("complete") is not True:
            # Failed packages are diagnostic evidence in the hidden run, never a
            # replacement for a usable visible delivery.
            failed = output_dir / "failed_delivery" / uuid4().hex
            failed.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stage), failed)
            record = _relocate_record(record, stage, failed)
            record["verification"] = verify_delivery_package(
                record,
                expected_root=failed,
                expected_manifest=manifest,
            )
            return record
        _protect_editable_documents(root, stage)
        if _package_snapshot(root) != before:
            raise RuntimeError(
                "The visible delivery changed during export; no files were replaced."
            )
        final_record = _relocate_record(record, stage, root)
        if root.exists():
            root.replace(backup)
            moved_previous = True
        stage.replace(root)
        installed = True
        final_record["verification"] = verify_delivery_package(
            final_record,
            expected_root=root,
            expected_manifest=manifest,
        )
        if final_record["verification"]["passed"] is not True:
            raise RuntimeError(
                "Installed delivery failed verification; the previous package was restored."
            )
    except BaseException:
        if installed:
            shutil.rmtree(root)
        if moved_previous:
            backup.replace(root)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    if backup.exists():
        shutil.rmtree(backup)
    return final_record
