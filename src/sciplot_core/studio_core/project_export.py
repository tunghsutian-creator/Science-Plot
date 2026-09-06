"""Export and publish one current managed document for CLI, Intake and Qt."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, cast

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.publish_run import publish_studio_export_run
from sciplot_core.studio_core.request_paths import _canonical_publish_paths


@dataclass(frozen=True)
class ProjectExportResult:
    """Immutable boundary snapshot; callers receive independent JSON projections."""

    document_sha256: str
    ready_to_use: bool
    _export_json: str
    _run_json: str

    @property
    def export_payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._export_json))

    @property
    def run_payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._run_json))

    @property
    def exports(self) -> list[dict[str, Any]]:
        run = self.run_payload
        exports = run.get("exports")
        return exports if isinstance(exports, list) else self.export_payload["exports"]


def export_project_document(
    *,
    project_dir: Path,
    formats: list[str],
    request_path: Path | None = None,
    document_path: Path | None = None,
    export_document: Callable[..., dict[str, Any]] | None = None,
    publish_export: Callable[..., dict[str, Any]] | None = None,
) -> ProjectExportResult:
    """Publish the saved current document once, without regenerating its data."""

    project, request, document = _canonical_publish_paths(
        project_dir=project_dir,
        request_path=request_path or project_dir / "plot_request.json",
        document_path=document_path or project_dir / "studio" / "document.vsz",
    )
    exporter = export_document or export_studio_document
    publisher = publish_export or publish_studio_export_run
    exported = exporter(document, formats=formats)
    document_hash = str(exported["document_sha256"])
    run = publisher(
        project_dir=project,
        request_path=request,
        document_path=document,
        exports=exported["exports"],
        export_document_sha256=document_hash,
    )
    return ProjectExportResult(
        document_sha256=document_hash,
        ready_to_use=run.get("ready_to_use") is True,
        _export_json=json.dumps(json_safe(exported), ensure_ascii=False),
        _run_json=json.dumps(json_safe(run), ensure_ascii=False),
    )


__all__ = ["ProjectExportResult", "export_project_document"]
