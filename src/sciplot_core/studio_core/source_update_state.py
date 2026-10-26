"""Read-only source revision guards and returned result projection."""
import json
from pathlib import Path
from typing import Any
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.studio_core.source_update_files import file_inventory
from sciplot_core.studio_core.source_update_review import payload_hash


def _delivery_inventory(delivery: Path) -> dict[str, str] | None:
    return file_inventory(delivery) if delivery.exists() else None


def _check_external_state(project: Path, source: Path, review: dict[str, Any], *,
                          source_override: Path | None = None, delivery_override: Path | None = None) -> None:
    request = json.loads((project / "plot_request.json").read_text())
    delivery = delivery_override if delivery_override is not None else requested_delivery_root({"request": request}, run_output=project)
    if (
        file_inventory(source_override if source_override is not None else source) != review["source_files"]
        or payload_hash(_delivery_inventory(delivery)) != review["delivery_sha256"]
    ):
        raise ValueError(
            "The selected source or visible delivery changed; preview it again before applying."
        )


def _applied_result(
    project: Path, preview: dict[str, Any], archive: Path, *, status: str,
) -> dict[str, Any]:
    return {
        "kind": "sciplot_project_source_update",
        "version": 1,
        "status": status,
        "project": str(project),
        "document": str(project / "studio" / "document.vsz"),
        "archive": str(archive),
        "changes": preview["changes"],
        "styles": preview["styles"],
        "ready_to_use": False,
        "next_action": "save_and_export",
    }


