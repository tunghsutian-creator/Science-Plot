"""Exact preserved literals resolve through registered generation identities only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, parts, sha


def logical_for_literal(value: dict[str, Any], original: str) -> str | None:
    path = Path(original)
    if not path.is_absolute():
        raise ProjectStoreError("A preserved source locator must be an exact absolute path.")
    matches = []
    for key, prefix in value["locators"].items():
        root = Path(prefix)
        if path.is_relative_to(root) and path != root:
            relative = path.relative_to(root).as_posix()
            parts(relative)
            logical = f"@{key}/{relative}" if key else relative
            if logical in value["files"]:
                matches.append(logical)
    if len(set(matches)) > 1:
        raise ProjectConflict("The preserved locator has ambiguous registered resource roots.")
    return matches[0] if matches else None


def original_for_logical(value: dict[str, Any], logical: str) -> str:
    components = parts(logical)
    key = components[0][1:] if components[0].startswith("@") else ""
    relative = Path(*components[1:]) if key else Path(*components)
    if key not in value["locators"] or logical not in value["files"]:
        raise ProjectStoreError("The resource has no preserved generation locator.")
    return str(Path(value["locators"][key]) / relative)


def source_entry(io: StoreIO, value: dict[str, Any], original: str, *, expected_sha256: str | None,
                 source_id: str | None) -> tuple[str, str, dict[str, Any]]:
    if expected_sha256 is None:
        raise ProjectStoreError("An external source locator requires its exact registered version hash.")
    matches = []
    for identity, versions in value["sources"].items():
        if source_id is not None and source_id != identity:
            continue
        entry = versions.get(expected_sha256)
        if entry is not None and entry.get("locator") == original:
            io.get(entry)
            matches.append((identity, expected_sha256, entry))
    if len(matches) != 1:
        raise ProjectConflict("The original locator, source identity and version do not resolve uniquely.")
    return matches[0]


def checked_member(io: StoreIO, value: dict[str, Any], logical: str, expected: str | None) -> dict[str, Any]:
    entry = value["files"].get(logical)
    if entry is None or expected is not None and expected != entry["sha256"]:
        raise ProjectConflict("The original locator does not bind this generation's exact bytes.")
    io.get(entry)
    physical = io.physical(logical)
    if physical is None or sha(physical[0]) != entry["sha256"]:
        raise ProjectConflict("The current resource view differs from the registered generation.")
    return dict(entry)
