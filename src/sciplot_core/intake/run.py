"""Application orchestration for project creation followed by one run."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.operation_modes import assisted_cleanup_mode_payload

from .config import _DEFAULT_OUTPUT_ROOT
from .models import IntakeGroupInput
from .packaging import _write_render_failure_cleanup_request, refresh_intake_project_zip
from .application import create_intake_project


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
    from sciplot_core.workflow import run_request

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
    try:
        manifest = run_request(plot_request_path)
    except Exception as exc:
        intake_manifest = json.loads(
            (project_dir / "intake_manifest.json").read_text(encoding="utf-8")
        )
        request = json.loads(plot_request_path.read_text(encoding="utf-8"))
        run_output = Path(
            str(request.get("output") or intake_manifest.get("outputs_dir"))
        )
        intervention = run_output / "intervention_request.json"
        cleanup_request = _write_render_failure_cleanup_request(
            run_output=run_output,
            request=request,
            request_path=plot_request_path,
            intervention=intervention,
        )
        failed_run = {
            "failed_at": datetime.now(UTC).isoformat(),
            "output": str(run_output),
            "figures": [],
            "analysis_metrics": [],
            "qa": {},
            "failure": str(exc),
            "operation_mode": assisted_cleanup_mode_payload(reason="render_failure"),
            "needs_assisted_cleanup": True,
            "intervention_request": str(intervention)
            if intervention.exists()
            else None,
            "assisted_cleanup_request": cleanup_request,
        }
        intake_manifest["last_run"] = failed_run
        intake_manifest["run_failed"] = True
        intake_manifest["failure"] = str(exc)
        (project_dir / "intake_manifest.json").write_text(
            json.dumps(json_safe(intake_manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for path in sorted(project_dir.glob("*.sciplot.json")):
            path.write_text(
                json.dumps(json_safe(intake_manifest), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        refreshed_zip = refresh_intake_project_zip(project_dir)
        return {
            **project,
            **intake_manifest,
            "project_dir": str(project_dir),
            "zip_path": str(refreshed_zip),
            "download_name": refreshed_zip.name,
            "last_run": failed_run,
        }
    intake_manifest = json.loads(
        (project_dir / "intake_manifest.json").read_text(encoding="utf-8")
    )
    refreshed_zip = refresh_intake_project_zip(project_dir)
    return {
        **project,
        **intake_manifest,
        "project_dir": str(project_dir),
        "zip_path": str(refreshed_zip),
        "download_name": refreshed_zip.name,
        "last_run": intake_manifest.get("last_run", manifest),
    }
