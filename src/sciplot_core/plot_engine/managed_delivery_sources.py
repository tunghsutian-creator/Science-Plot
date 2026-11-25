"""One exact original-data copy per private delivery, not per figure attempt."""

from pathlib import Path
from typing import Any

from sciplot_core.delivery.native_snapshot import SnapshotSealChanged
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.source_coverage.file_snapshots import _physical_file_snapshot, _require_snapshot_identity, _write_private_snapshot

from .errors import EngineError

_LABEL = "Managed delivery original source"


def stage_originals(root: Path, sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not sources:
        return []
    originals = canonical_path(root / "data" / "originals")
    originals.mkdir(parents=True, exist_ok=True)
    return [_stage_original(originals, source) for source in sources]


def _stage_original(originals: Path, source: dict[str, Any]) -> dict[str, str]:
    literal, sha, identity = Path(source["path"]), source["sha256"], source["source_id"]

    def actual() -> Path:
        return canonical_path(resolve_source_path(literal, expected_sha256=sha, source_id=identity))

    def capture(path: Path) -> dict[str, Any]:
        return _physical_file_snapshot(path, literal=literal, label=_LABEL, expected_sha256=sha)

    try:
        path = actual()
        snapshot = capture(path)
        name = sha + literal.suffix.lower()
        target = canonical_path(originals / name)
        try:
            _write_private_snapshot(target, snapshot["bytes"])
        except FileExistsError:
            if not target.is_file() or file_sha256(target) != sha:
                raise EngineError("managed_delivery_staging_changed", "A shared staged original differs from its selected source bytes.") from None
        current_path = actual()
        if current_path != path:
            raise ValueError("The selected original source changed its resolved location.")
        _require_snapshot_identity(snapshot, capture(current_path), label=_LABEL)
    except EngineError:
        raise
    except (ValueError, OSError) as exc:
        raise EngineError("managed_delivery_source_changed", "An original source changed during delivery.") from exc
    return {"source_id": identity, "original_name": literal.name, "sha256": sha,
            "path": "data/originals/" + name}


def shared_original(root: Path, item: dict[str, Any], source: dict[str, str]) -> Path | None:
    if source["path"] in item["files"]:
        return None  # Historical exact attempts kept their originals beside each figure.
    name = Path(source["path"]).name
    path = canonical_path(root / "data" / "originals" / name)
    if source["path"] != f"data/originals/{name}" or not name.startswith(source["sha256"]):
        raise SnapshotSealChanged("A shared original left its exact delivery namespace.")
    return path


def require_originals(root: Path, item: dict[str, Any]) -> None:
    for source in item["sources"]:
        path = shared_original(root, item, source)
        if path is not None and (not path.is_file() or file_sha256(path) != source["sha256"]):
            raise SnapshotSealChanged(f"The sealed shared original changed: {path}")
