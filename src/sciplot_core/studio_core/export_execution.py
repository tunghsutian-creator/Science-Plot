"""Select the project command or the standalone native export adapter."""
from pathlib import Path
from typing import Any
from sciplot_core.studio_core.native_export_adapter import (
    _project_studio_document as _project_studio_document, _count_veusz_series as _count_veusz_series,
)


def export_studio_document(document_path: Path, *, formats: list[str], output_dir: Path | None = None,
                           audit_spec_path: Path | None = None) -> dict[str, Any]:
    from sciplot_core.studio_core.context import _project_context_for_document
    if output_dir is None and _project_context_for_document(document_path) is not None:
        from sciplot_core.studio_core.native_export_commands import export_saved_native
        return export_saved_native(document_path, formats=formats, audit_spec_path=audit_spec_path)
    from sciplot_core.studio_core.native_export_adapter import export_studio_document as export_private
    return export_private(document_path, formats=formats, output_dir=output_dir, audit_spec_path=audit_spec_path)
