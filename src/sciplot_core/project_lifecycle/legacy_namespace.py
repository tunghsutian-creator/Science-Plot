"""Locate one known old head through an explicit store or an explicit directory."""
from dataclasses import dataclass
from pathlib import Path

from sciplot_core.project_store.errors import ProjectStoreError
from sciplot_core.project_store.locators import logical_for_literal
from sciplot_core.project_store.repository import FileProjectStore
from .namespace_capture import namespace_bytes


@dataclass(frozen=True)
class LegacyNamespace:
    origin: Path
    physical: Path
    prefix: str | None
    members: dict[str, bytes]
    modes: dict[str, int]
    directory: dict[str, int]


def capture(store: FileProjectStore, target: Path) -> LegacyNamespace:
    with store._locked(import_legacy=True, allow_pending=True) as (_io, current):
        logical = logical_for_literal(current, str(target / "head.json"))
        if logical is None:
            try:
                candidate = store.logical_path(target / "head.json")
                logical = candidate if candidate in current["files"] else None
            except ProjectStoreError:
                pass
    if logical is not None:
        prefix = logical.removesuffix("/head.json")
        observed = store.capture_namespace(prefix)
        entries = {name: entry for name, entry in observed["members"].items() if name != ".sciplot_semantic_owner.json"}
        return LegacyNamespace(Path(observed["origin_root"]), Path(observed["path"]), prefix,
            {name: entry["data"] for name, entry in entries.items()},
            {name: entry["mode"] for name, entry in entries.items()}, observed["directory"])
    modes: dict[str, int] = {}
    members = namespace_bytes(target, modes=modes)
    observed_stat = target.stat(follow_symlinks=False)
    return LegacyNamespace(target, target, None, members, modes,
        {"device": observed_stat.st_dev, "inode": observed_stat.st_ino, "mode": observed_stat.st_mode & 0o777})


def known_head(store: FileProjectStore, original: Path) -> bool:
    with store._locked(allow_pending=True) as (_io, current):
        if logical_for_literal(current, str(original / "head.json")) is not None:
            return True
        try:
            return store.logical_path(original / "head.json") in current["files"]
        except ProjectStoreError:
            return False


def capture_registered(store: FileProjectStore, target: Path) -> LegacyNamespace:
    """Observe existing canonical membership; never import, repair or adopt."""
    from sciplot_core.project_store.namespace_io import capture as observe
    from .errors import EngineError

    with store._locked() as (io, current):
        logical = logical_for_literal(current, str(target / "head.json"))
        if logical is None:
            logical = store.logical_path(target / "head.json")
        prefix = logical.removesuffix("/head.json")
        observed = observe(io, current, prefix)
        expected = {name[len(prefix) + 1:]: entry for name, entry in current["files"].items()
                    if name.startswith(prefix + "/")}
        members = observed["members"]
        if (set(members) != set(expected) or any(
                members[name]["sha256"] != entry["sha256"] or members[name]["mode"] != entry["mode"]
                for name, entry in expected.items())):
            raise EngineError("document_inputs_changed", "The registered semantic namespace differs from its committed generation.")
        return LegacyNamespace(Path(observed["origin_root"]), Path(observed["path"]), prefix,
            {name: entry["data"] for name, entry in members.items()},
            {name: entry["mode"] for name, entry in members.items()}, observed["directory"])
