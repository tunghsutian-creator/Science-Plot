"""Bounded session resources; arbitrary filesystem reads are never exposed."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from sciplot_core.mcp_server.errors import AdapterError


@dataclass(frozen=True)
class ResourceSnapshot:
    uri: str
    name: str
    mime_type: str
    data: bytes

    def metadata(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "mimeType": self.mime_type,
            "size": len(self.data),
        }


class ResourceStore:
    """Immutable result/PNG snapshots, valid until eviction or server restart."""

    def __init__(self, *, byte_limit: int = 32 * 1024 * 1024) -> None:
        self._entries: OrderedDict[str, ResourceSnapshot] = OrderedDict()
        self._byte_limit = byte_limit

    def add(self, name: str, mime_type: str, data: bytes) -> ResourceSnapshot:
        if len(data) > self._byte_limit:
            raise AdapterError("resource_too_large", "This result exceeds the session resource limit.")
        digest = sha256(mime_type.encode() + b"\0" + data).hexdigest()
        uri = f"sciplot://result/{digest}"
        entry = ResourceSnapshot(uri, name, mime_type, data)
        self._entries[uri] = entry
        self._entries.move_to_end(uri)
        while len(self._entries) > 128 or sum(len(item.data) for item in self._entries.values()) > self._byte_limit:
            self._entries.popitem(last=False)
        return entry

    def add_json(self, payload: dict[str, Any]) -> ResourceSnapshot:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        return self.add("Full SciPlot result", "application/json", data)

    def add_preview(self, path: Path, *, expected_sha256: str | None = None) -> ResourceSnapshot:
        # The path comes only from an executed owner result, never a read-tool argument.
        if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
            raise AdapterError("invalid_preview_resource", "The generated preview must be an ordinary PNG file.")
        if path.stat().st_size > self._byte_limit:
            raise AdapterError("resource_too_large", "The generated preview exceeds the session resource limit.")
        data = path.read_bytes()
        if expected_sha256 is not None and sha256(data).hexdigest() != expected_sha256:
            raise AdapterError("stale_preview_resource", "The generated PNG changed after its owner returned it; request a new preview.")
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AdapterError("invalid_preview_resource", "The generated preview is not a PNG image.")
        return self.add("SciPlot preview", "image/png", data)

    def get(self, uri: str) -> ResourceSnapshot:
        if uri not in self._entries:
            raise AdapterError(
                "unknown_resource",
                "Use a resource URI returned in this connection. Requery after a server restart or eviction.",
            )
        self._entries.move_to_end(uri)
        return self._entries[uri]

    def list(self) -> list[ResourceSnapshot]:
        return list(self._entries.values())
