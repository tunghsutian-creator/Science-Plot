"""Pin complete export and visible-delivery bytes for current cache evidence."""

from pathlib import Path
from typing import Any

from sciplot_core.delivery.filesystem_metadata import is_delivery_finder_metadata
from sciplot_core.studio_core.source_update_commit import file_inventory


def export_evidence(run: dict[str, Any]) -> dict[str, Any]:
    files: dict[str, str] = {}
    inventories: dict[str, list[str]] = {}
    roots = [Path(run["output"])]
    delivery = run.get("delivery_package") or {}
    if delivery.get("path"):
        roots.append(Path(delivery["path"]))
    for root in roots:
        inventory = {name: digest for name, digest in file_inventory(root).items()
                     if not is_delivery_finder_metadata(root / name)}
        files.update({str(root / name): digest for name, digest in inventory.items()})
        inventories[str(root)] = sorted(inventory)
    return {"evidence_files": files, "evidence_inventories": inventories}
