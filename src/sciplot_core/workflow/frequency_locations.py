"""Identify the canonical frequency creation record and its selected projection."""
from pathlib import Path
from typing import Any

from sciplot_core.delivery_identity import DELIVERY_IDENTITY, read_delivery_binding
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.output_contract import UserOutputLayout


FREQUENCY_AUTHORITY = ".sciplot-frequency"
FREQUENCY_RECORD = "frequency-creation.json"


def frequency_roots(layout: UserOutputLayout) -> tuple[Path, Path, Path]:
    workspace = layout.workspace_root
    return workspace / FREQUENCY_RECORD, workspace / "runs" / "run_001", workspace / FREQUENCY_AUTHORITY


def locate_frequency_project(value: Path) -> tuple[Path, Path, dict[str, Any], Path | None] | None:
    """Identify the written frequency authority without consulting its publication."""
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.foundation.json_io import read_json_object
    from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY
    from sciplot_core.policy.render_options import DELIVERY_PROJECT_DIR

    project = canonical_path(value)
    workspace = project.parent.parent if project.parent.name == FREQUENCY_AUTHORITY else None
    visible = binding = None
    document = project if project.suffix.casefold() == ".vsz" and project.parent.name == DELIVERY_PROJECT_DIR else None
    if workspace is None:
        if project.name == "plot_request.json":
            workspace = project.parent
        elif project.is_dir() and (project / FREQUENCY_RECORD).is_file():
            workspace = project
        else:
            visible = (project.parent.parent if document is not None
                       else project.parent if project.name == DELIVERY_IDENTITY else project)
            if not visible.is_dir() or not (visible / DELIVERY_IDENTITY).is_file():
                return None
            binding = read_delivery_binding(visible)
            if binding is None or not binding.request:
                return None
            workspace = Path(binding.request).parent
    creation = read_json_object(workspace / FREQUENCY_RECORD)
    if creation is None:
        return None
    request = creation["request"]
    canonical_request = workspace / "plot_request.json"
    if read_json_object(canonical_request) != request:
        raise ValueError("The saved Managed frequency plotting request changed.")
    authority = workspace / FREQUENCY_AUTHORITY / canonical_json_sha256(request)
    if ((visible is not None and (visible != Path(request[REQUEST_DELIVERY_ROOT_KEY])
                                  or binding.root != str(visible) or binding.request != str(canonical_request)))
            or (project.parent.name == FREQUENCY_AUTHORITY and project != authority)):
        raise ValueError("The selected frequency location does not match its exact saved project.")
    if document is not None:
        if not document.is_file():
            raise ValueError(f"The selected delivery document does not exist: {document}")
        if binding is None or document.name not in dict(binding.documents):
            raise ValueError(f"The selected VSZ is not registered in this delivery: {document}")
    return authority, canonical_request, creation, document
