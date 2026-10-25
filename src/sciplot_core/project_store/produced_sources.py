"""Bind an explicitly produced source to its own exact sealed command output."""

from pathlib import Path
from typing import Any

from .errors import ProjectConflict
from .io import StoreIO, parts
import sciplot_core.project_store.state as state


def bind(entry: dict[str, Any], resource: str | None) -> dict[str, Any]:
    if resource is not None:
        from sciplot_core.project_commands.resources import resource_key

        resource_key(resource)
        if entry.get("produced_resource", resource) != resource:
            raise ProjectConflict("An immutable source version already has another produced resource binding.")
        entry["produced_resource"] = resource
    return entry


def frozen_output(io: StoreIO, entry: dict[str, Any], record: dict[str, Any] | None) -> bool:
    name = entry.get("produced_resource")
    if name is None:
        return False
    if record is None or record.get("draft") is None:
        raise ProjectConflict("A produced source requires its exact sealed output command.")
    current = state.head(io)
    assert current is not None
    components = parts(name)
    key = components[0][1:] if components[0].startswith("@") else ""
    relative = Path(*components[1:]) if key else Path(*components)
    if name in current.get("input_resources", []) or not key and components[0] in {"raw", "source"}:
        raise ProjectConflict("An observed original input cannot be rebound as a produced source.")
    io.split(name)  # The finite trusted output capability must admit it.
    host = io.locations[key] if key else io.root
    original = Path(current["locators"].get(key, str(host)))
    if entry["locator"] not in {str(original / relative), str(host / relative)}:
        raise ProjectConflict("A produced source does not bind its exact preserved output locator.")
    if name not in record["write_set"]:
        return False  # A later read still validates this version's live bytes.
    candidate = record["draft"]["writes"].get(name)
    if candidate is None or any(candidate[key] != entry[key] for key in ("sha256", "size", "mode")):
        raise ProjectConflict("A produced source must match its exact sealed output bytes and mode.")
    if io.get(candidate) != io.get(entry):
        raise ProjectConflict("The sealed produced source differs from its candidate output.")
    return True
