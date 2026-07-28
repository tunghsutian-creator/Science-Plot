"""Register Studio document, export, and run state in the project manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe

from sciplot_core.studio_core.json_files import (
    _read_json,
)


def _register_studio_block(project_dir: Path, studio_block: dict[str, Any]) -> None:
    for manifest_path in [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]:
        if manifest_path.exists():
            payload = _read_json(manifest_path)
            payload["studio"] = studio_block
            manifest_path.write_text(
                json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    # Existing or moved projects can carry a retired Web launcher and stale
    # absolute launcher paths in both manifests.  Converge only after the
    # current portable launchers and Studio block are written so normal
    # `studio PROJECT` is itself the repair path.
    from sciplot_core.intake.packaging import converge_intake_project_launchers

    converge_intake_project_launchers(project_dir)


def _register_studio_exports(
    project_dir: Path,
    exports: list[dict[str, Any]],
    *,
    studio_run: dict[str, Any] | None = None,
) -> None:
    for manifest_path in [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]:
        if manifest_path.exists():
            payload = _read_json(manifest_path)
            studio = (
                payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
            )
            studio["exports"] = exports
            if studio_run is not None:
                studio["last_export_run"] = studio_run
            payload["studio"] = studio
            manifest_path.write_text(
                json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )


def _register_studio_run(project_dir: Path, manifest: dict[str, Any]) -> None:
    figure_set_export_scope = (
        manifest.get("figure_set_export_scope")
        if isinstance(manifest.get("figure_set_export_scope"), dict)
        else None
    )
    last_run = {
        "completed_at": manifest.get("created_at"),
        "route": "studio",
        "output": manifest.get("output"),
        "figures": manifest.get("figures", []),
        "qa": manifest.get("qa", {}),
        "revision_brief": manifest.get("revision_brief"),
        "package_contract": manifest.get("package_contract", {}),
        "delivery_package": manifest.get("delivery_package", {}),
        "layout_quality": manifest.get("layout_quality", {}),
    }
    if figure_set_export_scope is not None:
        last_run["figure_set_export_scope"] = json_safe(figure_set_export_scope)
    for manifest_path in [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]:
        if not manifest_path.exists():
            continue
        payload = _read_json(manifest_path)
        payload["last_run"] = last_run
        payload["package_contract"] = manifest.get("package_contract", {})
        payload["delivery_package"] = manifest.get("delivery_package", {})
        payload["layout_quality"] = manifest.get("layout_quality", {})
        if figure_set_export_scope is not None:
            payload["figure_set_export_scope"] = json_safe(figure_set_export_scope)
        else:
            payload.pop("figure_set_export_scope", None)
        studio = (
            payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        )
        studio["last_export_run"] = {
            "kind": "sciplot_studio_export_run",
            "output": manifest.get("output"),
            "manifest": str(Path(str(manifest.get("output"))) / "manifest.json")
            if manifest.get("output")
            else None,
            "review_html": str(Path(str(manifest.get("output"))) / "review.html")
            if manifest.get("output")
            else None,
            "figures": manifest.get("figures", []),
            "qa": manifest.get("qa", {}),
        }
        if figure_set_export_scope is not None:
            studio["last_export_run"]["figure_set_export_scope"] = json_safe(
                figure_set_export_scope
            )
        payload["studio"] = studio
        payload["study_model"] = manifest.get(
            "study_model", payload.get("study_model", {})
        )
        manifest_path.write_text(
            json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    try:
        from sciplot_core.intake.packaging import refresh_intake_project_zip

        refresh_intake_project_zip(project_dir)
    except Exception:
        return
