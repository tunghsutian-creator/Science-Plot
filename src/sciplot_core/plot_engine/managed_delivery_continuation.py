"""Guarded local continuation from a snapshot index, never registry relocation."""

from pathlib import Path
from typing import Any

from sciplot_core.project_lifecycle.ports import ProjectRepository

from sciplot_core.delivery.filesystem_metadata import is_delivery_finder_metadata
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.storage import digest
from sciplot_core.project_lifecycle.context import repository
from sciplot_core.project_lifecycle.head_observation import observe_plot_head
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.studio_core.source_update_files import file_inventory


def delivery_inventory(root: Path) -> dict[str, str]:
    """Exact file members, except the existing narrow Finder metadata allowance."""
    return {name: value for name, value in file_inventory(root).items()
            if not is_delivery_finder_metadata(root / name)}


def require_native_seal(head: dict[str, Any], expected: str) -> None:
    native = Path(head["binding"]["document"])
    if not native.is_file() or file_sha256(native) != expected:
        raise EngineError("managed_delivery_original_native_changed", "The original native bytes are missing or differ from this delivery's audited seal. Nothing was rebuilt or restored.")


def managed_delivery_location(path: Path) -> tuple[Path, Path | None, dict[str, Any]] | None:
    """Recognize the package directory, exact index or an exact native member path."""
    snapshot = path if path.suffix.casefold() == ".vsz" and path.parent.name == "project" else None
    root = snapshot.parent.parent if snapshot is not None else path.parent if path.name == "index.json" else path
    index = root / "index.json"
    if not index.is_file() or index.is_symlink():
        return None
    manifest = read_json_object(index)
    if manifest is None or manifest.get("kind") != "sciplot_managed_delivery":
        return None
    return root, snapshot, manifest


def local_managed_target(root: Path, figure_id: str | None, *, native_snapshot: Path | None = None,
                         manifest: dict[str, Any] | None = None, owner: ProjectRepository | None = None) -> dict[str, Any]:
    if manifest is None:
        path = canonical_path(root / "index.json")
        manifest = read_json_object(path)
        if manifest is None:
            raise EngineError("document_state_missing", "Required document state is missing or invalid.", evidence=str(path))
    if (manifest.get("kind") != "sciplot_managed_delivery" or manifest.get("version") != 1
            or manifest.get("mode") != "native_snapshot" or manifest.get("managed_project_included") is not False
            or manifest.get("manifest_sha256") != digest({key: value for key, value in manifest.items() if key != "manifest_sha256"})):
        raise EngineError("managed_delivery_manifest_changed", "The delivery index is invalid or changed; no original was opened.")
    items = manifest["items"]
    if native_snapshot is not None:
        if not native_snapshot.is_file():
            raise EngineError("managed_delivery_snapshot_missing", f"The selected Managed delivery document does not exist: {native_snapshot}")
        matches = [item for item in items if root / item["files"]["editable"] == native_snapshot]
        if len(matches) != 1 or figure_id is not None and matches[0]["id"] != figure_id:
            raise EngineError("managed_delivery_snapshot_identity", "The selected VSZ and figure ID must identify the same exact delivery member.")
    else:
        matches = items if figure_id is None else [item for item in items if item["id"] == figure_id]
    if len(matches) != 1:
        raise EngineError("managed_delivery_choose_figure", "Choose one exact delivery item ID with --figure.",
                          action="choose_figure", items=[{"id": item["id"], "label": item["label"]} for item in items])
    actual = {name: value for name, value in delivery_inventory(root).items() if name not in {"index.json", "Figures.zip"}}
    if actual != manifest["snapshot_files"]:
        raise EngineError("managed_delivery_snapshot_changed", "Snapshot members are added, missing or changed. Keep those edits; do not silently reconnect to an older original.",
                          action="inspect_snapshot_index", index=str(root / "index.json"))
    item = matches[0]
    original = item["local_managed_continuation"]
    try:
        plot = canonical_path(Path(original["plot"]))
        head = observe_plot_head(plot, owner=owner if owner is not None else repository())
        assert head is not None
    except (OSError, ValueError) as exc:
        raise EngineError("managed_delivery_native_snapshot_only", "The original local ManagedPlot is unavailable. This package contains an independent native snapshot, not a portable ManagedPlot registry.",
                          action="inspect_native_snapshot", document=str(root / item["files"]["editable"])) from exc
    document = head["document"]
    if (document.get("plot_type") != "ManagedPlot" or (document["plot_id"], document["revision"],
            document["scientific_hash"], document["presentation_hash"]) != (
                original["plot_id"], original["revision"], item["scientific_hash"], item["presentation_hash"])):
        raise EngineError("managed_delivery_original_changed", "The original ManagedPlot advanced or changed. Open it explicitly to review current authority; this snapshot was not promoted or restored.",
                          action="plot.describe", plot=str(plot))
    require_native_seal(head, item["audit"]["native_sha256"])
    return {"plot": plot, "item_id": item["id"], "label": item["label"], "head": head,
            "native_snapshot": str(root / item["files"]["editable"])}
