"""Project archive, launcher, manifest, and preparation packaging."""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote
from sciplot_core.foundation.json_values import json_safe
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


def _write_zip(project_dir: Path, zip_path: Path) -> None:
    project_root = Path(project_dir).expanduser().resolve(strict=True)
    zip_path = Path(zip_path).expanduser()
    if zip_path.is_symlink():
        raise PermissionError("Refusing to replace a symlink-backed SciPlot ZIP.")

    archive_files: list[Path] = []
    for path in sorted(project_root.rglob("*")):
        if path.is_symlink():
            raise PermissionError(
                f"Refusing to archive symlink-backed project entry: {path}"
            )
        if path.is_file():
            archive_files.append(
                _resolve_path_within_root(
                    path,
                    root=project_root,
                    require_regular_file=True,
                )
            )

    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in archive_files:
            archive.write(path, path.relative_to(project_root.parent))


def _remove_legacy_project_launcher(project_dir: Path) -> bool:
    legacy_launcher = project_dir / LEGACY_WEB_WORKBENCH_LAUNCHER
    if not (legacy_launcher.is_file() or legacy_launcher.is_symlink()):
        return False
    legacy_launcher.unlink()
    return True


def _apply_launcher_contract_to_manifest(
    manifest: dict[str, Any],
    *,
    contract: dict[str, object],
) -> None:
    primary = (
        contract.get("primary") if isinstance(contract.get("primary"), dict) else {}
    )
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
    _remove_legacy_project_launcher(project)
    contract = inspect_project_launcher_contract(project)
    if not update_manifests:
        return contract
    for manifest_path in [
        project / "intake_manifest.json",
        *sorted(project.glob("*.sciplot.json")),
    ]:
        manifest = _read_json_if_exists(manifest_path)
        if manifest is None:
            continue
        _apply_launcher_contract_to_manifest(
            manifest,
            contract=contract,
        )
        manifest_path.write_text(
            json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return contract


def refresh_intake_project_zip(project_dir: str | Path) -> Path:
    project_dir = Path(project_dir).expanduser().resolve()
    manifest_path = project_dir / "intake_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        zip_name = f"{manifest.get('project_slug') or project_dir.name}.zip"
    else:
        zip_name = f"{project_dir.name}.zip"
    zip_path = project_dir.parent / safe_filename(zip_name)
    _write_zip(project_dir, zip_path)
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
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    framework_paths = [
        Path("/opt/homebrew/opt/qtbase/lib"),
        Path("/opt/homebrew/opt/qt/lib"),
    ]
    existing = [str(path) for path in framework_paths if path.exists()]
    if existing:
        joined = ":".join(existing)
        for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
            current = env.get(key)
            env[key] = f"{joined}:{current}" if current else joined
        env.setdefault("SCIPLOT_STUDIO_QT_RUNTIME", "1")
    return env


def _prepare_studio_project_package(project_dir: Path) -> None:
    _remove_legacy_project_launcher(project_dir)
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
    except Exception:
        pass
    converge_intake_project_launchers(project_dir)
