"""Explicit generation-owned semantic attachment identities and old-location fences."""
from dataclasses import dataclass
from functools import cached_property
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_store.io import STORE
from sciplot_core.project_store.repository import FileProjectStore
from .errors import EngineError

INDEX = ".sciplot_semantic/index.json"
OWNER = ".sciplot_semantic_owner.json"


def encode(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def read_index(store: FileProjectStore, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    if snapshot is not None and INDEX not in snapshot["files"]:
        current = snapshot
        data = None
    else:
        observation = store.observe_members((INDEX,), generation=snapshot["generation"] if snapshot else None,
                                             projection=snapshot is None)
        current = snapshot if snapshot is not None else observation.selected
        data = observation.members[INDEX].data
        if snapshot is not None and data is None:
            from sciplot_core.project_store.errors import ProjectStoreError

            raise ProjectStoreError("The logical resource is not a member of this generation.")
    if data is None:
        return {"kind": "sciplot_semantic_attachment_index", "version": 1,
                "project_id": current["project_id"], "attachments": {}}
    return validate_index(json.loads(data), current["project_id"])


def validate_index(value: Any, project_id: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != {"kind", "version", "project_id", "attachments"}
            or value["kind"] != "sciplot_semantic_attachment_index" or value["version"] != 1
            or value["project_id"] != project_id or not isinstance(value["attachments"], dict)):
        raise EngineError("semantic_attachment_index_invalid", "The project semantic attachment index is invalid.")
    for identity, item in value["attachments"].items():
        if (not isinstance(identity, str) or not isinstance(item, dict) or item.get("id") != identity
                or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity)
                or item.get("namespace") != ".sciplot_semantic/" + identity
                or not isinstance(item.get("origin_root"), str) or not Path(item["origin_root"]).is_absolute()
                or not isinstance(item.get("project_origin"), str) or not Path(item["project_origin"]).is_absolute()
                or not isinstance(item.get("plot_id"), str) or not isinstance(item.get("figure_id"), str)
                or item.get("history_root") is not None and not Path(item["history_root"]).is_absolute()):
            raise EngineError("semantic_attachment_index_invalid", "A semantic namespace has an invalid stable identity.")
    return value


@dataclass(frozen=True)
class Attachment:
    store: FileProjectStore
    entry: dict[str, Any]

    @property
    def root(self) -> Path:
        return self.store.root / str(self.entry["namespace"])

    @property
    def origin(self) -> Path:
        return Path(self.entry["origin_root"])

    @property
    def cache(self) -> Path:
        return self.store.root / STORE / "semantic-derived" / str(self.entry["id"])

    @property
    def namespace_origin(self) -> Path:
        return Path(self.entry.get("namespace_origin", str(Path(self.entry["project_origin"]) / self.entry["namespace"])))

    @cached_property
    def legacy_projection(self) -> Path | None:
        prefix = self.entry.get("legacy_prefix")
        if prefix is None:
            return None
        return Path(self.store.capture_namespace(prefix)["path"])

    @property
    def output(self) -> Path | None:
        value = self.entry.get("managed_output")
        if value is None:
            return None
        if self.entry.get("output_owner") == "derived":
            return self.cache / "output"
        original, project = Path(value), Path(self.entry["project_origin"])
        return self.store.root / original.relative_to(project) if original.is_relative_to(project) else self.cache / "output"

    def contains(self, path: Path) -> bool:
        roots = [self.cache]
        if self.output is not None:
            roots.extend((self.output, Path(self.entry["managed_output"])))
        return self.relative(path) is not None or any(path == root or path.is_relative_to(root) for root in roots)

    def relative(self, path: Path) -> Path | None:
        roots = [self.root, self.origin, self.namespace_origin]
        if self.entry.get("transfer_root") is not None:
            roots.append(Path(self.entry["transfer_root"]))
        for root in roots:
            if path == root or path.is_relative_to(root):
                return path.relative_to(root)
        if self.legacy_projection is not None:
            known = self.legacy_projection
            if path == known or path.is_relative_to(known):
                return path.relative_to(known)
        return None

    def logical(self, path: Path) -> str:
        relative = self.relative(path)
        if relative is None or not relative.parts:
            raise EngineError("semantic_attachment_path_invalid", "The path does not name this attachment's resource.")
        return str(self.entry["namespace"]) + "/" + relative.as_posix()


def attachment_id(project_id: str, key: str) -> str:
    return canonical_json_sha256(["semantic_attachment_v1", project_id, key], allow_nan=False)[:32]


def owned_marker(path: Path) -> tuple[Path, dict[str, Any]] | None:
    """Only inspect the fixed ownership filename on the explicit path's ancestors."""
    for candidate in (path, *path.parents):
        marker = candidate / OWNER
        if marker.is_symlink():
            raise EngineError("semantic_attachment_owner_invalid", "A semantic ownership fence cannot be a symbolic link.")
        if marker.is_file():
            value = read_json_object(marker)
            if (value is None or value.get("kind") != "sciplot_semantic_owner" or value.get("version") != 1
                    or not Path(value.get("origin_root", "")).is_absolute() or not isinstance(value.get("project_id"), str)
                    or not isinstance(value.get("attachment_id"), str) or not Path(value.get("project", "")).is_absolute()):
                raise EngineError("semantic_attachment_owner_invalid", "The old semantic namespace ownership fence is invalid.")
            if value.get("role") == "history" and (value.get("history_root") == str(candidate) or value["origin_root"] != str(candidate)):
                raise EngineError("semantic_attachment_history_read_only", "The registered original history is a read-only backup; open its attached project.")
            return candidate, value
    return None


def require_local_owner(path: Path) -> None:
    if owned_marker(path) is not None:
        raise EngineError("semantic_attachment_owner_required", "This namespace is read-only history of an attached project; use its project attachment.",
                          action="open_attached_project")
