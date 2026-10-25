"""Export and publish one current managed document for CLI, Intake and Qt."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, cast

from sciplot_core.foundation.json_values import json_safe
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
    expected_binding: dict[str, Any] | None = None,
) -> ProjectExportResult:
    """Publish the saved current document once, without regenerating its data."""

    project, request, document = _canonical_publish_paths(
        project_dir=project_dir,
        request_path=request_path or project_dir / "plot_request.json",
        document_path=document_path or project_dir / "studio" / "document.vsz",
    )
    from sciplot_core.studio_core.project_publication_commands import publish_project_exports

    run = publish_project_exports(project_dir=project, request_path=request,
                                  document_path=document, formats=formats, expected_binding=expected_binding)
    exported = {"kind": "sciplot_studio_export", "document": str(document),
                "document_sha256": run["document_sha256"],
                "exports": run["exports"]}
    return ProjectExportResult(
        document_sha256=exported["document_sha256"],
        ready_to_use=run.get("ready_to_use") is True,
        _export_json=json.dumps(json_safe(exported), ensure_ascii=False),
        _run_json=json.dumps(json_safe(run), ensure_ascii=False),
    )


__all__ = ["ProjectExportResult", "export_project_document"]
