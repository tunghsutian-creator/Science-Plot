from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.rendering.data_containers import source_table_data_containers
from src.rendering.source_table_preview import source_table_preview

SUPPORTED_LIVE_SOURCE_KINDS = {"file_tail", "folder_watch", "periodic_csv", "periodic_csv_refresh"}


def _diagnostic(status_code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status_code": status_code, "message": message, **extra}


def _source_identity(source: dict[str, Any]) -> str:
    source_id = str(source.get("source_id") or source.get("id") or "live-source")
    source["source_id"] = source_id
    source["id"] = source_id
    source["graph_node_id"] = source.get("graph_node_id") or f"live_source:{source_id}"
    return source_id


def _stamp_source(
    source: dict[str, Any],
    diagnostic: dict[str, Any],
    *,
    data_revision: int | None = None,
    container_ids: list[str] | None = None,
) -> dict[str, Any]:
    _source_identity(source)
    source["last_update_diagnostic"] = diagnostic
    source["last_diagnostic"] = diagnostic
    source["last_update_at"] = datetime.now(UTC).isoformat()
    if data_revision is not None:
        source["last_revision"] = data_revision
    if container_ids is not None:
        source["container_ids"] = container_ids
    return source


def _resolve_live_source_path(kind: str, input_path: str | Path) -> tuple[Path | None, dict[str, Any] | None]:
    path = Path(input_path).expanduser()
    if kind == "folder_watch":
        if not path.exists() or not path.is_dir():
            return None, _diagnostic(
                "folder_not_found",
                "Folder watch live source requires an existing directory.",
                input_path=str(path),
            )
        candidates = sorted(path.glob("*.csv"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
        if not candidates:
            return None, _diagnostic(
                "folder_watch_empty",
                "Folder watch did not find a CSV file to refresh.",
                input_path=str(path),
            )
        return candidates[0], None
    if not path.exists() or not path.is_file():
        return None, _diagnostic(
            "source_not_found",
            "Live source update requires an existing local file.",
            input_path=str(path),
        )
    return path, None


def update_live_source(
    *,
    live_source: dict[str, Any],
    input_path: str | Path,
    sheet: str | int = 0,
    options: dict[str, Any] | None = None,
    current_revision: int = 0,
) -> dict[str, Any]:
    source = dict(live_source)
    _source_identity(source)
    kind = str(source.get("kind") or "")
    if kind not in SUPPORTED_LIVE_SOURCE_KINDS:
        diagnostic = _diagnostic(
            "live_source_disabled",
            "This live source kind is disabled until sandbox, dependency, and fixture policy exists.",
            kind=kind,
        )
        source["status"] = "disabled"
        _stamp_source(source, diagnostic, data_revision=int(source.get("last_revision") or 0), container_ids=[])
        return {
            "live_source": source,
            "input_path": str(input_path),
            "sheet": sheet,
            "data_revision": 0,
            "data_containers": [],
            "diagnostics": [diagnostic],
            "render_invalidation": {"reason": "live_source_disabled"},
            "help": source.get("help") or diagnostic["message"],
        }

    if source.get("paused") is True or source.get("status") != "enabled":
        diagnostic = _diagnostic("live_source_paused", "Live source is disabled or paused.")
        _stamp_source(source, diagnostic, data_revision=int(source.get("last_revision") or 0), container_ids=[])
        return {
            "live_source": source,
            "input_path": str(input_path),
            "sheet": sheet,
            "data_revision": 0,
            "data_containers": [],
            "diagnostics": [diagnostic],
            "render_invalidation": {"reason": "live_source_paused"},
            "help": source.get("help") or diagnostic["message"],
        }

    last_revision = int(source.get("last_revision") or 0)
    if current_revision and last_revision > current_revision:
        diagnostic = _diagnostic(
            "stale_live_source_revision",
            "Live source update response is stale relative to the current session revision.",
            current_revision=current_revision,
            last_revision=last_revision,
        )
        _stamp_source(
            source,
            diagnostic,
            data_revision=last_revision,
            container_ids=list(source.get("container_ids") or []),
        )
        return {
            "live_source": source,
            "input_path": str(input_path),
            "sheet": sheet,
            "data_revision": last_revision,
            "data_containers": [],
            "diagnostics": [diagnostic],
            "render_invalidation": {"reason": "stale_live_source_revision", "data_revision": last_revision},
            "help": source.get("help") or diagnostic["message"],
        }

    resolved_path, error = _resolve_live_source_path(kind, source.get("path") or input_path)
    if resolved_path is None:
        _stamp_source(source, error or {}, data_revision=last_revision, container_ids=[])
        return {
            "live_source": source,
            "input_path": str(input_path),
            "sheet": sheet,
            "data_revision": 0,
            "data_containers": [],
            "diagnostics": [error or _diagnostic("source_not_found", "Live source could not be resolved.")],
            "render_invalidation": {"reason": "live_source_error"},
            "help": source.get("help") or "Resolve the live source path and refresh again.",
        }

    sample_window = max(1, int(source.get("sample_window") or 1000))
    preview = source_table_preview(
        resolved_path,
        sheet=sheet,
        offset=0,
        limit=min(sample_window, 10_000),
        encoding=(options or {}).get("encoding"),
        delimiter=(options or {}).get("delimiter"),
    )
    containers = source_table_data_containers(preview)
    data_revision = max(current_revision + 1, last_revision + 1, 1)
    container_ids = [str(item["id"]) for item in containers]
    diagnostic = _diagnostic(
        "live_source_updated",
        "Live source refreshed from the current local file snapshot.",
        input_path=str(resolved_path),
        data_revision=data_revision,
    )
    source["path"] = str(resolved_path)
    _stamp_source(source, diagnostic, data_revision=data_revision, container_ids=container_ids)
    return {
        "live_source": source,
        "input_path": str(resolved_path),
        "sheet": sheet,
        "data_revision": data_revision,
        "data_containers": containers,
        "diagnostics": [diagnostic],
        "render_invalidation": {"reason": "live_source_updated", "data_revision": data_revision},
        "help": source.get("help") or "Live source refreshed.",
    }


def pause_live_source(
    *,
    live_source: dict[str, Any],
    input_path: str | Path,
    sheet: str | int = 0,
) -> dict[str, Any]:
    source = dict(live_source)
    source["paused"] = True
    source["status"] = source.get("status") or "enabled"
    diagnostic = _diagnostic("live_source_paused", "Live source polling is paused.")
    data_revision = int(source.get("last_revision") or 0)
    _stamp_source(
        source,
        diagnostic,
        data_revision=data_revision,
        container_ids=list(source.get("container_ids") or []),
    )
    return {
        "live_source": source,
        "input_path": str(source.get("path") or input_path),
        "sheet": sheet,
        "data_revision": data_revision,
        "data_containers": [],
        "diagnostics": [diagnostic],
        "render_invalidation": {"reason": "live_source_paused", "data_revision": data_revision},
        "help": source.get("help") or "Live source polling is paused.",
    }


def resume_live_source(
    *,
    live_source: dict[str, Any],
    input_path: str | Path,
    sheet: str | int = 0,
) -> dict[str, Any]:
    source = dict(live_source)
    source["paused"] = False
    source["status"] = source.get("status") or "enabled"
    diagnostic = _diagnostic("live_source_resumed", "Live source polling is resumed.")
    data_revision = int(source.get("last_revision") or 0)
    _stamp_source(
        source,
        diagnostic,
        data_revision=data_revision,
        container_ids=list(source.get("container_ids") or []),
    )
    return {
        "live_source": source,
        "input_path": str(source.get("path") or input_path),
        "sheet": sheet,
        "data_revision": data_revision,
        "data_containers": [],
        "diagnostics": [diagnostic],
        "render_invalidation": {"reason": "live_source_resumed", "data_revision": data_revision},
        "help": source.get("help") or "Live source polling is resumed.",
    }


__all__ = ["SUPPORTED_LIVE_SOURCE_KINDS", "pause_live_source", "resume_live_source", "update_live_source"]
