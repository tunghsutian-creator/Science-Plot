"""Application orchestration for project creation followed by one run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.operation_modes import (
    assisted_cleanup_mode_payload,
    normal_mode_payload,
)
from sciplot_core.studio import export_project_document

from .config import _DEFAULT_OUTPUT_ROOT
from .models import IntakeGroupInput
from .packaging import _write_render_failure_cleanup_request, refresh_intake_project_zip
from .application import create_intake_project
from sciplot_core.project_manifest import (
    edit_intake_project_manifest,
    read_intake_project_manifest,
)


def create_and_run_intake_project(
    *,
    project_name: str,
    data_type_id: str,
    experiment_type_id: str,
    groups: list[IntakeGroupInput],
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    plot_output: str | Path | None = None,
    exports: list[str] | tuple[str, ...] | None = None,
    render_options: dict[str, Any] | None = None,
    column_confirmations: list[dict[str, Any]] | None = None,
    replicate_mode: str | None = None,
) -> dict[str, Any]:
    project = create_intake_project(
        project_name=project_name,
        data_type_id=data_type_id,
        experiment_type_id=experiment_type_id,
        groups=groups,
        output_root=output_root,
        plot_output=plot_output,
        exports=exports,
        render_options=render_options,
        column_confirmations=column_confirmations,
        replicate_mode=replicate_mode,
    )
    project_dir = Path(str(project["project_dir"]))
    plot_request_path = Path(str(project["plot_request"]))
    manifest: dict[str, Any] | None = None
    request: dict[str, Any] = {}
    try:
        studio = project.get("studio") or {}
        if studio.get("status") == "blocked":
            raise ValueError(studio.get("error") or "Studio preparation is blocked.")
        request_payload = json.loads(plot_request_path.read_text(encoding="utf-8"))
        if not isinstance(request_payload, dict):
            raise ValueError("The current project request must be a JSON object.")
        request = request_payload
        published = export_project_document(
            project_dir=project_dir,
            formats=list(request.get("exports") or ["pdf", "tiff_300"]),
        )
        manifest = published.run_payload
        if not published.ready_to_use:
            raise RuntimeError(
                manifest.get("failure_reason") or "Project export is incomplete."
            )
    except Exception as exc:
        intake_manifest = read_intake_project_manifest(project_dir)
        if intake_manifest is None:
            raise RuntimeError(
                f"Intake project manifest disappeared from {project_dir}."
            ) from exc
        run_output, own_diagnostic = _failure_output(project_dir, manifest)
        current_run = manifest or {}
        intervention = run_output / "intervention_request.json"
        needs_cleanup = bool(
            current_run.get("intervention_request") == str(intervention)
            and intervention.is_file()
        )
        cleanup_request = (
            _write_render_failure_cleanup_request(
                run_output=run_output,
                request=request,
                request_path=plot_request_path,
                intervention=intervention,
            )
            if needs_cleanup
            else None
        )
        failed_run = {
            "failed_at": utc_now_iso(),
            "output": str(run_output),
            "figures": [],
            "analysis_metrics": [],
            "qa": {},
            "failure": str(exc),
            "document": str(project_dir / "studio" / "document.vsz"),
            "state": "failed",
            "ready_to_use": False,
            "failure_kind": "source_intervention"
            if needs_cleanup
            else "execution_error",
            "operation_mode": (
                assisted_cleanup_mode_payload(reason="source_intervention")
                if needs_cleanup
                else normal_mode_payload(route="web")
            ),
            "needs_assisted_cleanup": needs_cleanup,
            "intervention_request": str(intervention) if needs_cleanup else None,
            "assisted_cleanup_request": cleanup_request,
        }
        if own_diagnostic:
            atomic_write_json(run_output / "manifest.json", failed_run)
        with edit_intake_project_manifest(
            project_dir,
            require_existing=True,
        ) as current_manifest:
            assert current_manifest is not None
            current_manifest["last_run"] = failed_run
            current_manifest["run_failed"] = True
            current_manifest["failure"] = str(exc)
            intake_manifest = current_manifest
        refreshed_zip = refresh_intake_project_zip(project_dir)
        return {
            **project,
            **intake_manifest,
            "project_dir": str(project_dir),
            "zip_path": str(refreshed_zip),
            "download_name": refreshed_zip.name,
            "last_run": failed_run,
        }
    intake_manifest = read_intake_project_manifest(project_dir)
    if intake_manifest is None:
        raise RuntimeError(f"Intake project manifest disappeared from {project_dir}.")
    refreshed_zip = refresh_intake_project_zip(project_dir)
    return {
        **project,
        **intake_manifest,
        "project_dir": str(project_dir),
        "zip_path": str(refreshed_zip),
        "download_name": refreshed_zip.name,
        "last_run": intake_manifest.get("last_run", manifest),
    }


def _failure_output(
    project_dir: Path,
    manifest: dict[str, Any] | None,
) -> tuple[Path, bool]:
    """Use this publication's returned evidence, never an obsolete request run."""
    value = manifest.get("output") if manifest is not None else None
    if isinstance(value, str) and value.strip():
        candidate = Path(value).expanduser().resolve()
        if candidate.is_relative_to(project_dir.resolve()) and candidate.is_dir():
            return candidate, False
    # An exception before a result has no bound publication output. Record that
    # attempt separately instead of guessing the latest directory or reusing the
    # old Workflow request.output and its possibly stale intervention artifacts.
    diagnostic = project_dir / "runs" / f"intake_failed_{uuid4().hex}"
    diagnostic.mkdir(parents=True)
    return diagnostic, True
