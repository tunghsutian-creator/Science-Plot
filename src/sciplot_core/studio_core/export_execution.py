"""Export one exact-current Studio document and collect its artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.policy import (
    normalize_export_formats,
)

from sciplot_core.studio_core.runtime import (
    _ensure_veusz_on_path,
    _capture_process_stderr,
    _export_suffix,
)

from sciplot_core.studio_core.launchers import (
    _prefer_offscreen_export_platform,
)

from sciplot_core.studio_core.json_files import (
    _read_json,
)


def _project_studio_document(project_dir: Path) -> Path | None:
    document = project_dir / "studio" / "document.vsz"
    if document.exists() and document.is_file():
        return document.resolve()
    manifest_paths = [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]
    for manifest_path in manifest_paths:
        if not manifest_path.exists():
            continue
        try:
            payload = _read_json(manifest_path)
        except Exception:
            continue
        studio = (
            payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        )
        document_value = studio.get("document")
        if isinstance(document_value, str) and document_value.strip():
            candidate = Path(document_value).expanduser()
            if not candidate.is_absolute():
                candidate = project_dir / candidate
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
    return None


def _count_veusz_series(document_path: Path) -> int:
    try:
        text = document_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    count = text.count("Add('xy',")
    return max(count - text.count("Add('xy', name='category_axis_label_provider'"), 0)


def export_studio_document(
    document_path: Path,
    *,
    formats: list[str],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    from sciplot_core.veusz_runtime import (
        needs_veusz_worker_process,
        veusz_worker_environment,
    )

    normalized_formats = list(normalize_export_formats(formats, default=()))
    if not normalized_formats:
        raise ValueError("At least one export format is required.")
    resolved_output_dir = (
        output_dir.expanduser().resolve() if output_dir is not None else None
    )
    if needs_veusz_worker_process():
        command = [
            sys.executable,
            "-m",
            "sciplot_core.veusz_worker",
            "export-document",
            str(document_path),
            "--formats",
            ",".join(normalized_formats),
        ]
        if resolved_output_dir is not None:
            command.extend(["--out", str(resolved_output_dir)])
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=True,
            env=veusz_worker_environment(),
        )
        return json.loads(result.stdout)
    export_dir = resolved_output_dir or document_path.parent / "exports"
    log_root = (
        export_dir.parent if resolved_output_dir is not None else document_path.parent
    )
    stderr_log = log_root / "logs" / "veusz_export_stderr.log"
    exports: list[dict[str, Any]] = []
    pending_exports: list[dict[str, Any]] = []
    cleanup_warnings: list[str] = []
    document_sha256_before = existing_file_sha256(document_path)
    document_sha256_after = document_sha256_before
    try:
        with _capture_process_stderr(stderr_log):
            _prefer_offscreen_export_platform()
            _ensure_veusz_on_path()
            from PyQt6 import QtWidgets
            from veusz import dataimport, document, widgets
            from veusz.document import CommandInterface

            _ = dataimport, widgets
            existing_app = QtWidgets.QApplication.instance()
            app = existing_app or QtWidgets.QApplication([])
            try:
                doc = document.Document()
                doc.load(str(document_path))
                interface = CommandInterface(doc)
                export_dir.mkdir(parents=True, exist_ok=True)
                for fmt in normalized_formats:
                    suffix, dpi = _export_suffix(fmt)
                    output_path = export_dir / f"{document_path.stem}{suffix}"
                    temporary_path = export_dir / (
                        f".{document_path.stem}.{uuid4().hex}{suffix}"
                    )
                    kwargs: dict[str, Any] = {"page": [0]}
                    if dpi is not None:
                        kwargs["dpi"] = dpi
                    if fmt == "pdf":
                        kwargs["pdfdpi"] = 72
                    interface.Export(str(temporary_path), **kwargs)
                    if (
                        not temporary_path.is_file()
                        or temporary_path.stat().st_size <= 0
                    ):
                        raise RuntimeError(
                            f"Veusz did not create a non-empty {fmt} export."
                        )
                    pending_exports.append(
                        {
                            "format": fmt,
                            "temporary_path": temporary_path,
                            "output_path": output_path,
                            "sha256": existing_file_sha256(temporary_path),
                        }
                    )
            finally:
                if existing_app is None:
                    app.quit()
        document_sha256_after = existing_file_sha256(document_path)
        if document_sha256_before != document_sha256_after:
            raise RuntimeError(
                "The Veusz document changed while SciPlot was exporting it; "
                "the generated files were not accepted as exact-current evidence."
            )
        replacements: list[dict[str, Any]] = []
        try:
            for pending in pending_exports:
                temporary_path = pending["temporary_path"]
                output_path = pending["output_path"]
                backup_path = (
                    export_dir / f".{output_path.name}.{uuid4().hex}.previous"
                    if output_path.exists()
                    else None
                )
                replacement = {
                    "output_path": output_path,
                    "backup_path": backup_path,
                    "installed": False,
                }
                replacements.append(replacement)
                if backup_path is not None:
                    output_path.replace(backup_path)
                temporary_path.replace(output_path)
                replacement["installed"] = True
                actual_hash = existing_file_sha256(output_path)
                if (
                    not output_path.is_file()
                    or output_path.stat().st_size <= 0
                    or actual_hash != pending["sha256"]
                ):
                    raise RuntimeError(
                        f"Installed {pending['format']} export failed its "
                        "post-replacement hash check."
                    )
                exports.append(
                    {
                        "format": pending["format"],
                        "path": str(output_path),
                        "exists": True,
                        "size_bytes": output_path.stat().st_size,
                        "sha256": actual_hash,
                    }
                )
            if existing_file_sha256(document_path) != document_sha256_before:
                raise RuntimeError(
                    "The Veusz document changed while SciPlot was publishing "
                    "the export set; the prior canonical files were restored."
                )
        except Exception:
            exports.clear()
            for replacement in reversed(replacements):
                output_path = replacement["output_path"]
                backup_path = replacement["backup_path"]
                if replacement["installed"] and output_path.exists():
                    output_path.unlink()
                if backup_path is not None and backup_path.exists():
                    backup_path.replace(output_path)
            raise
        else:
            for replacement in replacements:
                backup_path = replacement["backup_path"]
                if backup_path is not None and backup_path.exists():
                    try:
                        backup_path.unlink()
                    except OSError as exc:
                        cleanup_warnings.append(
                            f"Could not remove committed export backup "
                            f"{backup_path}: {exc}"
                        )
    finally:
        for pending in pending_exports:
            temporary_path = pending["temporary_path"]
            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError as exc:
                    cleanup_warnings.append(
                        f"Could not remove uncommitted export temporary file "
                        f"{temporary_path}: {exc}"
                    )
    payload: dict[str, Any] = {
        "kind": "sciplot_studio_export",
        "document": str(document_path),
        "document_sha256": document_sha256_after,
        "export_dir": str(export_dir),
        "exports": exports,
    }
    if stderr_log.exists():
        payload["stderr_log"] = str(stderr_log)
    if cleanup_warnings:
        payload["cleanup_warnings"] = cleanup_warnings
    return payload
