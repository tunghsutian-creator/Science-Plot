"""Public Studio publication routes through one complete project command."""
from pathlib import Path
from typing import Any
from sciplot_core.studio_core.publication_prepare import prepare_studio_export_run as prepare_studio_export_run


def publish_studio_export_run(
    *, project_dir: Path, request_path: Path, document_path: Path,
    exports: list[dict[str, Any]], export_document_sha256: str,
    primary_native_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from sciplot_core.studio_core.project_publication_commands import publish_project_exports

    return publish_project_exports(project_dir=project_dir, request_path=request_path,
        document_path=document_path, exports=exports,
        export_document_sha256=export_document_sha256, primary_native_audit=primary_native_audit)
