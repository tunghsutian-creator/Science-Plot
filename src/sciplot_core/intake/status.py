"""Read-only intake project listing and result status assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.assisted_cleanup import (
    CLEANUP_REQUEST_FILENAME,
    CLEANUP_RESULT_FILENAME,
)
from sciplot_core.operation_modes import (
    assisted_cleanup_mode_payload,
    normal_mode_payload,
)
from sciplot_core.policy import canonical_figure_stem

from .artifact_previews import _figure_preview_info
from .packaging import _artifact_info, _project_package_info, _read_json_if_exists
from .path_security import _resolve_path_within_root


def list_intake_projects(output_root: Path) -> list[dict[str, Any]]:
    output_root = output_root.expanduser().resolve()
    if not output_root.is_dir():
        return []
    projects: list[dict[str, Any]] = []
    for entry in sorted(output_root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "intake_manifest.json"
        manifest = _read_json_if_exists(manifest_path)
        if manifest is None:
            continue
        sciplot_path = next(entry.glob("*.sciplot.json"), None)
        sciplot_meta = _read_json_if_exists(sciplot_path) if sciplot_path else {}
        stat = entry.stat()
        last_run = (
            manifest.get("last_run")
            if isinstance(manifest.get("last_run"), dict)
            else {}
        )
        figure_count = len(last_run.get("figures", []))
        projects.append(
            {
                "slug": entry.name,
                "project_name": manifest.get("project_name") or entry.name,
                "data_type": manifest.get("data_type"),
                "experiment": manifest.get("experiment"),
                "created": sciplot_meta.get("created", ""),
                "figure_count": figure_count,
                "has_failure": bool(last_run.get("failure")),
                "last_run_output": last_run.get("output", ""),
                "mtime_ns": stat.st_mtime_ns,
                "group_count": len(manifest.get("groups", [])),
                "file_count": sum(
                    len(group.get("files", [])) for group in manifest.get("groups", [])
                ),
            }
        )
    projects.sort(key=lambda p: p["mtime_ns"], reverse=True)
    return projects


def _resolve_project_artifact(project_dir: Path, artifact_path: str) -> Path:
    if not artifact_path.strip():
        raise ValueError("Artifact path is required.")
    try:
        return _resolve_path_within_root(
            artifact_path,
            root=project_dir,
            require_regular_file=True,
        )
    except PermissionError as exc:
        raise PermissionError("Artifact path is outside this SciPlot project.") from exc


def _project_scoped_manifest_path(
    project_dir: Path,
    value: object,
    *,
    fallback: Path | None = None,
) -> Path | None:
    text = str(value or "").strip()
    if text:
        try:
            return _resolve_path_within_root(
                text,
                root=project_dir,
                require_regular_file=False,
            )
        except (FileNotFoundError, OSError, PermissionError, RuntimeError, ValueError):
            pass
    if fallback is None:
        return None
    return _resolve_path_within_root(
        fallback,
        root=project_dir,
        require_regular_file=False,
    )


def intake_project_status(project_dir: str | Path) -> dict[str, Any]:
    project_path = Path(project_dir).expanduser().resolve()
    manifest_path = project_path / "intake_manifest.json"
    manifest = _read_json_if_exists(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"No intake project manifest found at {manifest_path}.")
    project_slug = str(manifest.get("project_slug") or project_path.name)
    last_run = (
        manifest.get("last_run") if isinstance(manifest.get("last_run"), dict) else {}
    )
    run_output = _project_scoped_manifest_path(
        project_path,
        last_run.get("output") or manifest.get("outputs_dir"),
        fallback=project_path / "runs" / "run_001",
    )
    assert run_output is not None
    intervention_path = run_output / "intervention_request.json"
    cleanup_request_path = run_output / CLEANUP_REQUEST_FILENAME
    cleanup_result_path = run_output / CLEANUP_RESULT_FILENAME
    artifacts = {
        "manifest": _artifact_info(
            run_output / "manifest.json",
            project_slug=project_slug,
            authorized_root=project_path,
        ),
        "analysis_report": _artifact_info(
            run_output / "analysis_report.md",
            project_slug=project_slug,
            authorized_root=project_path,
        ),
        "analysis_metrics": _artifact_info(
            run_output / "tables" / "analysis_metrics.csv",
            project_slug=project_slug,
            authorized_root=project_path,
        ),
        "revision_brief": _artifact_info(
            run_output / "revision_brief.md",
            project_slug=project_slug,
            authorized_root=project_path,
        ),
        "review_html": _artifact_info(
            run_output / "review.html",
            project_slug=project_slug,
            authorized_root=project_path,
        ),
        "intervention_request": _artifact_info(
            intervention_path,
            project_slug=project_slug,
            authorized_root=project_path,
        ),
        "assisted_cleanup_request": _artifact_info(
            cleanup_request_path,
            project_slug=project_slug,
            authorized_root=project_path,
        ),
        "cleanup_result": _artifact_info(
            cleanup_result_path,
            project_slug=project_slug,
            authorized_root=project_path,
        ),
    }
    delivery = (
        last_run.get("delivery_package")
        if isinstance(last_run.get("delivery_package"), dict)
        else {}
    )
    project_file = delivery.get("project_file")
    data_csvs = (
        delivery.get("data_csvs") if isinstance(delivery.get("data_csvs"), list) else []
    )
    if isinstance(project_file, str) and project_file.strip():
        artifacts["delivery_project"] = _artifact_info(
            Path(project_file),
            project_slug=project_slug,
            authorized_root=project_path,
        )
    artifacts["delivery_data"] = [
        _artifact_info(
            Path(str(item.get("path"))),
            project_slug=project_slug,
            authorized_root=project_path,
        )
        for item in data_csvs
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item.get("path")
    ]
    figure_paths = [
        safe_path
        for path in last_run.get("figures", [])
        if isinstance(path, str)
        for safe_path in [_project_scoped_manifest_path(project_path, path)]
        if safe_path is not None
    ]
    figures = [
        {
            **_artifact_info(
                path,
                project_slug=project_slug,
                authorized_root=project_path,
            ),
            "canonical_figure_stem": canonical_figure_stem(path),
        }
        for path in figure_paths
    ]
    preview_figure = _figure_preview_info(figure_paths, project_slug=project_slug)
    cleanup_result = _read_json_if_exists(cleanup_result_path)
    cleanup_ready = bool(
        cleanup_result and cleanup_result.get("ready_for_normal_mode") is True
    )
    has_cleanup_blocker = bool(
        last_run.get("failure")
        or artifacts["intervention_request"]["exists"]
        or artifacts["assisted_cleanup_request"]["exists"]
    )
    needs_assisted_cleanup = bool(has_cleanup_blocker and not cleanup_ready)
    operation_mode = (
        assisted_cleanup_mode_payload(reason="project_failure_or_intervention")
        if needs_assisted_cleanup
        else normal_mode_payload(route="web")
    )
    return {
        "kind": "sciplot_project_status",
        "project_slug": project_slug,
        "project_dir": str(project_path),
        "manifest": json_safe(manifest),
        "plot_request": manifest.get("plot_request"),
        "outputs_dir": str(run_output),
        "last_run": json_safe(last_run),
        "artifacts": artifacts,
        "project_package": _project_package_info(
            project_path, project_slug=project_slug
        ),
        "figures": figures,
        "preview_figure": preview_figure,
        "review": {
            "mode": "read_only",
            "preview_source": "rendered_artifacts_only",
        },
        "operation_mode": operation_mode,
        "needs_assisted_cleanup": needs_assisted_cleanup,
        "cleanup": {
            "request": artifacts["assisted_cleanup_request"],
            "result": artifacts["cleanup_result"],
            "ready_for_normal_mode": cleanup_ready,
            "payload": json_safe(cleanup_result)
            if cleanup_result is not None
            else None,
        },
    }
