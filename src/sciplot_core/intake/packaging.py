"""Project archive, launcher, manifest, and preparation packaging."""

from __future__ import annotations

import json
import mimetypes
import os as os
import subprocess
import sys
import zipfile as zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.foundation.path_names import safe_filename
from sciplot_core._paths import resolved_path_is_within
from sciplot_core.assisted_cleanup import (
    CLEANUP_REQUEST_FILENAME,
    write_cleanup_request,
)
from sciplot_core.launchers import (
    LEGACY_WEB_WORKBENCH_LAUNCHER,
    PROJECT_EXPORT_LAUNCHER,
    PROJECT_PRIMARY_LAUNCHER,
    PROJECT_VEUSZ_LAUNCHER,
    inspect_project_launcher_contract,
)

from .path_security import _resolve_path_within_root
from .archive_storage import _write_zip_snapshot_unlocked
from sciplot_core.project_manifest import (
    locked_intake_project_manifest,
)
from sciplot_core.veusz_runtime import veusz_worker_environment


def _write_zip(project_dir: Path, zip_path: Path) -> None:
    _write_zip_snapshot_unlocked(project_dir.expanduser().resolve(strict=True), zip_path)


def _apply_launcher_contract_to_manifest(
    manifest: dict[str, Any],
    *,
    contract: dict[str, object],
) -> None:
    supplied = contract.get("primary")
    primary = supplied if isinstance(supplied, dict) else {}
    primary_path = primary.get("path")
    if contract.get("ready") is True and isinstance(primary_path, str):
        manifest["launcher"] = primary_path
    else:
        manifest.pop("launcher", None)
    manifest["launcher_contract"] = json_safe(contract)


def converge_intake_project_launchers(
    project_dir: str | Path,
    *,
    update_manifests: bool = True,
) -> dict[str, object]:
    """Retire the ambiguous Web launcher and register the Veusz-first entry."""

    project = Path(project_dir).expanduser().resolve()
    from sciplot_core.project_manifest import read_intake_project_manifest, stage_intake_project_manifest
    from sciplot_core.project_store.adapters import project_storage_scope, publish_files

    with locked_intake_project_manifest(project), project_storage_scope(project) as store:
        snapshot = store.snapshot()
        contract = inspect_project_launcher_contract(project)
        legacy = contract["legacy_web_workbench_launcher"]
        assert isinstance(legacy, dict)
        legacy["present"] = False
        primary, supporting = contract["primary"], contract["supporting"]
        assert isinstance(primary, dict) and isinstance(supporting, dict)
        ready = primary.get("safe") is True and all(item.get("safe") is True for item in supporting.values())
        contract.update(ready=ready, status="ready" if ready else "blocked")
        writes: dict[str, bytes | PreparedFile | None] = {}
        if LEGACY_WEB_WORKBENCH_LAUNCHER in snapshot["files"]:
            writes[LEGACY_WEB_WORKBENCH_LAUNCHER] = None
        manifest = read_intake_project_manifest(project) if update_manifests else None
        if manifest is not None:
            _apply_launcher_contract_to_manifest(
                manifest,
                contract=contract,
            )
            writes.update(stage_intake_project_manifest(project, manifest, include_snapshot=False, store=store))
        if writes:
            publish_files(store, writes, kind="publish", result={"launcher_contract": contract})
    return contract


def refresh_intake_project_zip(project_dir: str | Path) -> Path:
    with locked_intake_project_manifest(Path(project_dir)) as project:
        manifest_path = project / "intake_manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {}
        )
        return _refresh_intake_project_zip_unlocked(project, manifest)


def _refresh_intake_project_zip_unlocked(
    project: Path,
    manifest: dict[str, Any],
) -> Path:
    zip_name = f"{manifest.get('project_slug') or project.name}.zip"
    zip_path = project.parent / safe_filename(zip_name)
    _write_zip_snapshot_unlocked(project, zip_path)
    return zip_path


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_render_failure_cleanup_request(
    *,
    run_output: Path,
    request: dict[str, Any],
    request_path: Path,
    intervention: Path,
) -> str | None:
    cleanup_request = run_output / CLEANUP_REQUEST_FILENAME
    if cleanup_request.exists():
        return str(cleanup_request)
    input_value = request.get("input")
    if not isinstance(input_value, str) or not input_value.strip():
        return None
    input_path = Path(input_value).expanduser()
    if not input_path.is_absolute():
        input_path = request_path.parent / input_path
    write_cleanup_request(
        run_output,
        input_path=input_path,
        reason="render_failure",
        request=request,
        intervention_request=intervention if intervention.exists() else None,
        provider="codex",
    )
    return str(cleanup_request)


def _project_dir_fromslug(output_root: Path, project_slug: str) -> Path:
    safe_slug = safe_filename(project_slug)
    project_dir = (output_root.expanduser().resolve() / safe_slug).resolve()
    if not resolved_path_is_within(project_dir, output_root):
        raise PermissionError("Project path is outside the configured output root.")
    return project_dir


def _artifact_info(
    path: Path,
    *,
    project_slug: str,
    authorized_root: Path | None = None,
) -> dict[str, Any]:
    display_path = path
    authorized = True
    if authorized_root is not None:
        try:
            display_path = _resolve_path_within_root(
                path,
                root=authorized_root,
                require_regular_file=False,
            )
        except (FileNotFoundError, OSError, PermissionError, RuntimeError, ValueError):
            authorized = False
    artifact_stat = None
    if authorized:
        try:
            display_path = _resolve_path_within_root(
                display_path,
                root=authorized_root or display_path.parent,
                require_regular_file=True,
            )
            artifact_stat = display_path.stat()
        except (FileNotFoundError, OSError, PermissionError, RuntimeError, ValueError):
            artifact_stat = None
    exists = artifact_stat is not None
    return {
        "exists": exists,
        "path": str(display_path) if authorized else "",
        "name": path.name,
        "size_bytes": artifact_stat.st_size if artifact_stat is not None else 0,
        "mtime_ns": artifact_stat.st_mtime_ns if artifact_stat is not None else 0,
        "content_type": mimetypes.guess_type(path.name)[0]
        or "application/octet-stream",
        "url": (
            f"/api/projects/{quote(project_slug)}/artifact?"
            f"path={quote(str(display_path), safe='')}"
            if exists
            else None
        ),
    }


def _download_info(path: Path, *, authorized_root: Path) -> dict[str, Any]:
    try:
        safe_path = _resolve_path_within_root(
            path,
            root=authorized_root,
            require_regular_file=True,
        )
        download_stat = safe_path.stat()
    except (FileNotFoundError, OSError, PermissionError, RuntimeError, ValueError):
        safe_path = path
        download_stat = None
    exists = download_stat is not None
    return {
        "exists": exists,
        "path": str(safe_path) if exists else "",
        "name": path.name,
        "size_bytes": download_stat.st_size if download_stat is not None else 0,
        "mtime_ns": download_stat.st_mtime_ns if download_stat is not None else 0,
        "content_type": mimetypes.guess_type(path.name)[0]
        or "application/octet-stream",
        "url": f"/api/download/{quote(path.name)}" if exists else None,
    }


def _project_package_info(project_dir: Path, *, project_slug: str) -> dict[str, Any]:
    launcher_contract = inspect_project_launcher_contract(project_dir)
    studio_launcher = project_dir / PROJECT_PRIMARY_LAUNCHER
    studio_launcher_info = _artifact_info(
        studio_launcher,
        project_slug=project_slug,
        authorized_root=project_dir,
    )
    studio_launcher_info["executable"] = bool(
        studio_launcher_info["exists"] and (studio_launcher.stat().st_mode & 0o111)
    )
    veusz_launcher = project_dir / PROJECT_VEUSZ_LAUNCHER
    veusz_launcher_info = _artifact_info(
        veusz_launcher,
        project_slug=project_slug,
        authorized_root=project_dir,
    )
    veusz_launcher_info["executable"] = bool(
        veusz_launcher_info["exists"] and (veusz_launcher.stat().st_mode & 0o111)
    )
    export_edited_launcher = project_dir / PROJECT_EXPORT_LAUNCHER
    export_edited_launcher_info = _artifact_info(
        export_edited_launcher,
        project_slug=project_slug,
        authorized_root=project_dir,
    )
    export_edited_launcher_info["executable"] = bool(
        export_edited_launcher_info["exists"]
        and (export_edited_launcher.stat().st_mode & 0o111)
    )
    studio_documents = [
        _artifact_info(
            path,
            project_slug=project_slug,
            authorized_root=project_dir,
        )
        for path in sorted((project_dir / "studio").glob("*.vsz"))
    ]
    sciplot_manifests = [
        _artifact_info(
            path,
            project_slug=project_slug,
            authorized_root=project_dir,
        )
        for path in sorted(project_dir.glob("*.sciplot.json"))
    ]
    zip_path = project_dir.parent / safe_filename(f"{project_slug}.zip")
    zip_info = _download_info(zip_path, authorized_root=project_dir.parent)
    studio_complete = bool(
        studio_launcher_info["exists"]
        and studio_launcher_info["executable"]
        and veusz_launcher_info["exists"]
        and veusz_launcher_info["executable"]
        and export_edited_launcher_info["exists"]
        and export_edited_launcher_info["executable"]
        and studio_documents
        and all(item["exists"] for item in studio_documents)
    )
    return {
        "kind": "sciplot_project_package_status",
        "complete": bool(
            launcher_contract["ready"] is True
            and studio_complete
            and sciplot_manifests
            and all(item["exists"] for item in sciplot_manifests)
            and zip_info["exists"]
        ),
        "launcher": studio_launcher_info,
        "primary_launcher": studio_launcher_info,
        "launcher_contract": json_safe(launcher_contract),
        "studio": {
            "launcher": studio_launcher_info,
            "veusz_launcher": veusz_launcher_info,
            "export_edited_launcher": export_edited_launcher_info,
            "documents": studio_documents,
            "complete": studio_complete,
        },
        "sciplot_manifests": sciplot_manifests,
        "zip": zip_info,
    }


def _studio_prepare_env() -> dict[str, str]:
    return veusz_worker_environment()


def _prepare_studio_project_package(project_dir: Path) -> None:
    legacy = project_dir / LEGACY_WEB_WORKBENCH_LAUNCHER
    if legacy.exists() or legacy.is_symlink():
        from sciplot_core.project_store.adapters import project_storage_scope, publish_files

        with project_storage_scope(project_dir) as store:
            publish_files(store, {LEGACY_WEB_WORKBENCH_LAUNCHER: None}, kind="publish")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.cli",
                "studio",
                str(project_dir),
                "--prepare-only",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=True,
            env=_studio_prepare_env(),
        )
    except subprocess.CalledProcessError as exc:
        diagnostic = exc.stderr or exc.stdout
        detail = diagnostic.strip()[-2000:] if isinstance(diagnostic, str) else ""
        message = (
            f"SciPlot Studio package preparation failed for {project_dir} "
            f"with exit status {exc.returncode}."
        )
        if detail:
            message = f"{message} {detail}"
        raise RuntimeError(message) from exc
    except OSError as exc:
        raise RuntimeError(
            f"SciPlot Studio package preparation could not start for {project_dir}."
        ) from exc
    converge_intake_project_launchers(project_dir)
