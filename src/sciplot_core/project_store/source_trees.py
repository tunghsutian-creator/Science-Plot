"""Read-only exact source-tree witnesses; never grant an output resource root."""

from pathlib import Path
from typing import Any

from sciplot_core.project_commands.resources import SourceTreeRead

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO
from .source_tree_io import observe as observe


def _selected(io: StoreIO, current: dict[str, Any], locator: str) -> tuple[str, set[str] | None]:
    literal = Path(locator)
    matches = []
    for key, saved in current["locators"].items():
        if key and key not in io.locations:
            continue
        root = Path(saved)
        if not literal.is_relative_to(root):
            continue
        relative = literal.relative_to(root).as_posix()
        logical = ("@" + key + ("/" + relative if relative != "." else "")) if key else (relative if relative != "." else "")
        if not any(name == logical or name.startswith(logical + "/") or not logical and not name.startswith("@")
                   for name in current["files"]):
            continue
        host = io.locations[key] if key else io.root
        members = io.location_members.get(key)
        prefix = relative + "/" if relative != "." else ""
        allowed = {name[len(prefix):] for name in members if name.startswith(prefix)} if members is not None else None
        if members is not None and relative != "." and relative not in members and not allowed:
            continue
        matches.append((str(host / relative), allowed))
    if len({path for path, _allowed in matches}) > 1:
        raise ProjectConflict("A selected source tree has ambiguous preserved root mappings.")
    return matches[0] if matches else (locator, None)


def require(io: StoreIO, current: dict[str, Any], record: dict[str, Any], *,
            admit: bool = False, _live: bool = False) -> None:
    values = record.get("metadata", {}).get("source_trees", [])
    if not isinstance(values, list):
        raise ProjectStoreError("Source trees require closed selected-source read witnesses.")
    if (values and record.get("draft") is not None
            and record["draft"].get("source_tree_origins") != record.get("source_tree_origins")):
        raise ProjectConflict("The selected source-tree admission differs from its sealed candidate proof.")
    seen = set()
    for supplied in values:
        if not isinstance(supplied, dict) or set(supplied) != {"locator", "tree_sha256"}:
            raise ProjectStoreError("A source-tree read must bind only its exact locator and composite hash.")
        guard = SourceTreeRead(**supplied)
        locator = guard.locator
        if not isinstance(locator, str) or locator in seen:
            raise ProjectStoreError("Source-tree reads require distinct canonical source locators.")
        seen.add(locator)
        if not admit and not _live and record.get("draft") is not None:
            from .prepared_inputs import tree_path

            if tree_path(io, current, record, locator=locator, tree_sha256=guard.tree_sha256) is not None:
                continue
        actual, allowed = _selected(io, current, locator)
        version, observed = observe(actual, allowed=allowed)
        observed["actual"] = actual
        if version != guard.tree_sha256:
            raise ProjectConflict("A selected source tree changed its complete file membership or bytes.")
        if admit:
            record.setdefault("source_tree_origins", {})[locator] = observed
        if record.get("source_tree_origins", {}).get(locator) != observed:
            raise ProjectConflict("A selected source tree changed its admitted inode or permissions.")
