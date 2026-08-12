"""Validate, atomically save, and migrate existing Veusz documents."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from collections.abc import Callable
from typing import Any
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
    file_sha256,
)
from sciplot_core.materials_rules import (
    format_plot_text_units,
    unit_solidus_violations,
)

from sciplot_core.studio_core.runtime import (
    _ensure_veusz_on_path,
)

from sciplot_core.studio_core.launchers import (
    _prefer_offscreen_export_platform,
)


def _is_project_secondary_document(document_path: Path) -> bool:
    resolved = document_path.expanduser().resolve()
    return bool(
        resolved.parent.name == "figures"
        and resolved.parent.parent.name == "studio"
        and resolved.name != "document.vsz"
        and (resolved.parent.parent / "document.vsz").is_file()
        and (resolved.parent.parent.parent / "plot_request.json").is_file()
    )


def _standalone_export_artifact_root(document_path: Path) -> Path:
    resolved = document_path.expanduser().resolve()
    if _is_project_secondary_document(resolved):
        return resolved.parent / "exports" / resolved.stem
    return resolved.parent / "exports"


def _validate_staged_veusz_document(
    staged_path: Path,
    *,
    mode: str,
    source_document: Any,
) -> bool:
    """Validate staged bytes and report whether secure Veusz reopen succeeded.

    Syntax, non-empty, and I/O failures raise.  A secure-mode rejection of
    owner-approved commands returns ``False`` so the caller can preserve the
    document atomically while withholding any verified-export claim.
    """

    with staged_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size <= 0:
            raise OSError("Veusz produced an empty staged document.")
        handle.seek(0)
        handle.read(1)

    if mode == "vsz":
        source = staged_path.read_text(encoding="utf-8")
        compile(source, str(staged_path), "exec")

    from veusz import document as veusz_document

    reopened = veusz_document.Document()
    try:
        reopened.load(
            str(staged_path),
            mode=mode,
            callbackunsafe=lambda: False,
            callbackimporterror=lambda _filename, _error: False,
        )
    except Exception as exc:
        # A document which the owner explicitly opened in Veusz secure mode
        # may legitimately serialize commands that a fresh validation
        # document refuses to execute.  The staged source has still passed
        # UTF-8 decoding, Python compilation, fsync, and non-empty checks.
        # Never execute those commands a second time merely to validate save.
        if mode == "vsz" and "unsafe command" in str(exc).casefold():
            return False
        raise
    expected_datasets = sorted(str(name) for name in source_document.data)
    reopened_datasets = sorted(str(name) for name in reopened.data)
    expected_pages = [
        (str(child.name), str(getattr(child, "typename", "")))
        for child in source_document.basewidget.children
    ]
    reopened_pages = [
        (str(child.name), str(getattr(child, "typename", "")))
        for child in reopened.basewidget.children
    ]
    if reopened_datasets != expected_datasets or reopened_pages != expected_pages:
        raise OSError(
            "The staged Veusz document reopened with a different dataset or "
            "page structure."
        )
    return True


def stage_veusz_document(
    document: Any,
    target: Path,
    *,
    staged_validator: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """Serialize beside a target while leaving both target and live state intact."""

    requested = target.expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    parent = requested.parent.resolve(strict=True)
    if not parent.is_dir():
        raise NotADirectoryError(parent)
    resolved_target = parent / requested.name
    mode = "hdf5" if resolved_target.suffix.casefold() == ".vszh5" else "vsz"
    old_document_filename = str(getattr(document, "filename", "") or "")
    old_modified = bool(document.isModified())
    old_changeset = int(getattr(document, "changeset", 0))
    signals_blocked = bool(
        document.signalsBlocked() if hasattr(document, "signalsBlocked") else False
    )
    existing_mode = (
        resolved_target.stat().st_mode & 0o777 if resolved_target.exists() else 0o644
    )
    staged_fd, staged_name = tempfile.mkstemp(
        prefix=f".{resolved_target.stem}.sciplot-save-",
        suffix=resolved_target.suffix,
        dir=parent,
    )
    os.close(staged_fd)
    staged_path = Path(staged_name)

    def restore_live_state() -> None:
        document.filename = old_document_filename
        document.modified = old_modified
        document.changeset = old_changeset

    try:
        if hasattr(document, "blockSignals"):
            document.blockSignals(True)
        try:
            document.save(str(staged_path), mode)
        finally:
            restore_live_state()
            if hasattr(document, "blockSignals"):
                document.blockSignals(signals_blocked)

        with staged_path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        validate_staged_document = (
            staged_validator
            if staged_validator is not None
            else _validate_staged_veusz_document
        )
        reopen_validated = validate_staged_document(
            staged_path,
            mode=mode,
            source_document=document,
        )
        os.chmod(staged_path, existing_mode)
        staged_size = staged_path.stat().st_size
        staged_sha256 = file_sha256(staged_path)
        return {
            "kind": "sciplot_staged_veusz_document",
            "version": 1,
            "status": "passed" if reopen_validated else "saved_unvalidated",
            "target": str(resolved_target),
            "staged": str(staged_path),
            "mode": mode,
            "size_bytes": staged_size,
            "sha256": staged_sha256,
            "reopen_validated": reopen_validated,
            "ready_for_export": reopen_validated,
        }
    except Exception:
        restore_live_state()
        if hasattr(document, "blockSignals"):
            document.blockSignals(signals_blocked)
        staged_path.unlink(missing_ok=True)
        raise


def atomic_save_veusz_document(
    document: Any,
    target: Path,
    *,
    staged_validator: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """Serialize, validate, and atomically replace one Veusz target."""

    stage = stage_veusz_document(
        document,
        target,
        staged_validator=staged_validator,
    )
    staged_path = Path(stage["staged"])
    resolved_target = Path(stage["target"])
    parent = resolved_target.parent
    replaced = False
    try:
        os.replace(staged_path, resolved_target)
        replaced = True
        directory_fd: int | None = None
        directory_fsync = False
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
            os.fsync(directory_fd)
            directory_fsync = True
        except OSError:
            pass
        finally:
            if directory_fd is not None:
                try:
                    os.close(directory_fd)
                except OSError:
                    pass

        document.filename = str(resolved_target)
        try:
            document.setModified(False)
        except Exception:
            document.modified = False
        return {
            **{key: value for key, value in stage.items() if key != "staged"},
            "kind": "sciplot_atomic_veusz_save",
            "directory_fsync": directory_fsync,
        }
    finally:
        if not replaced:
            staged_path.unlink(missing_ok=True)


def migrate_studio_document_unit_labels(document_path: Path) -> dict[str, Any]:
    """Apply the global unit-expression contract through native Veusz settings.

    This maintenance adapter is deliberately narrower than regeneration: it
    changes only semantic text settings that contain a recognized unit
    solidus, preserves data and all other document settings, and saves through
    the same atomic VSZ lifecycle used by Studio.
    """

    resolved = document_path.expanduser().resolve()
    if not resolved.is_file() or resolved.suffix.casefold() != ".vsz":
        raise FileNotFoundError(f"Veusz document not found: {resolved}")

    from sciplot_core.veusz_runtime import (
        needs_veusz_worker_process,
        veusz_worker_environment,
    )

    if needs_veusz_worker_process():
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.veusz_worker",
                "migrate-unit-labels",
                str(resolved),
            ],
            text=True,
            capture_output=True,
            check=True,
            env=veusz_worker_environment(),
        )
        return json.loads(result.stdout)

    _prefer_offscreen_export_platform()
    _ensure_veusz_on_path()
    from PyQt6 import QtWidgets
    from veusz import dataimport, document, widgets
    from veusz.document.operations import OperationSettingSet

    _ = dataimport, widgets
    existing_app = QtWidgets.QApplication.instance()
    app = existing_app or QtWidgets.QApplication([])
    try:
        loaded = document.Document()
        loaded.load(str(resolved))
        candidates: list[tuple[str, Any, str, str]] = []

        def collect(widget_path: str, widget: Any) -> None:
            settings = getattr(getattr(widget, "settings", None), "setdict", {})
            for setting_name in ("label", "title", "key"):
                setting = settings.get(setting_name)
                if setting is None:
                    continue
                current = str(setting.get() or "")
                if not unit_solidus_violations(current):
                    continue
                updated = format_plot_text_units(current)
                if updated != current:
                    candidates.append(
                        (
                            f"{widget_path.rstrip('/')}/{setting_name}",
                            setting,
                            current,
                            updated,
                        )
                    )

        loaded.walkNodes(collect, nodetypes=("widget",))
        before_sha256 = existing_file_sha256(resolved)
        if not candidates:
            return {
                "kind": "sciplot_unit_label_migration",
                "version": 1,
                "status": "unchanged",
                "document": str(resolved),
                "document_sha256_before": before_sha256,
                "document_sha256_after": before_sha256,
                "operation_count": 0,
                "operations": [],
                "save": None,
            }

        operations: list[dict[str, Any]] = []
        for setting_path, setting, current, updated in candidates:
            normalized = setting.normalize(updated)
            loaded.applyOperation(OperationSettingSet(setting_path, normalized))
            operations.append(
                {
                    "setting_path": setting_path,
                    "before": current,
                    "after": str(normalized),
                }
            )
        save = atomic_save_veusz_document(loaded, resolved)
        return {
            "kind": "sciplot_unit_label_migration",
            "version": 1,
            "status": "migrated",
            "document": str(resolved),
            "document_sha256_before": before_sha256,
            "document_sha256_after": existing_file_sha256(resolved),
            "operation_count": len(operations),
            "operations": operations,
            "save": save,
        }
    finally:
        if existing_app is None:
            app.quit()
