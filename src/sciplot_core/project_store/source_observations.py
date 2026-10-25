"""Explicit raw-input observations advance witnesses without installing originals."""

from collections.abc import Mapping
from typing import Any

from pathlib import Path
from sciplot_core.project_commands.resources import PreparedSource, SourceAdoption

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, parts, sha
from .locators import original_for_logical


def observations(record: Mapping[str, Any]) -> dict[str, SourceAdoption]:
    values = record.get("metadata", {}).get("source_adoptions", [])
    if not isinstance(values, list):
        raise ProjectStoreError("Source observations require the fixed typed resource descriptors.")
    if values and record["metadata"].get("kind") not in {"source_update", "semantic_record"}:
        raise ProjectStoreError("Only an explicit source update may admit changed input observations.")
    result = {}
    for supplied in values:
        value = SourceAdoption(**supplied)
        if (value.resource in result or value.resource in record["write_set"]
                or record["read_set"].get(value.resource) != value.before_sha256):
            raise ProjectStoreError("A source observation must be one exact old read and cannot be an output write.")
        result[value.resource] = value
    return result


def require_bindings(baseline: Mapping[str, Any], record: Mapping[str, Any]) -> None:
    for name, value in observations(record).items():
        entry = baseline["sources"].get(value.source_id, {}).get(value.before_sha256)
        if (entry is None or entry.get("locator") != original_for_logical(dict(baseline), name)
                or entry.get("logical", name) != name):
            raise ProjectConflict("The observed input does not match its registered resource/source identity.")


def capture(io: StoreIO, current: dict[str, Any], resource: str, *, source_id: str,
            before_sha256: str) -> dict[str, Any]:
    SourceAdoption(resource, source_id, before_sha256, before_sha256)
    before = current["files"].get(resource)
    source = current["sources"].get(source_id, {}).get(before_sha256)
    origin = original_for_logical(current, resource)
    if before is None or before["sha256"] != before_sha256 or source is None or source.get("locator") != origin:
        raise ProjectConflict("The changed input must still bind its exact registered old resource/source identity.")
    physical = io.physical(resource, owned=False)
    if physical is None:
        raise ProjectConflict("The registered input is missing; it cannot reconnect to another file.")
    data, mode = physical
    value = PreparedSource(source_id, origin, sha(data), data, tuple(source.get("aliases", ())), mode).to_storage_payload()
    components = parts(resource)
    actual = (io.locations[components[0][1:]] / Path(*components[1:])
              if components[0].startswith("@") else io.root / Path(*components))
    return {**value, "path": str(actual)}


def local_versions(io: StoreIO, record: dict[str, Any]) -> None:
    local = io.read("local_sources.json")
    if local is not None:
        for value in observations(record).values():
            local["versions"].setdefault(value.source_id, {})[value.observed_sha256] = value.observed_sha256
        io.write("local_sources.json", local)


def adopt(io: StoreIO, current: dict[str, Any], value: dict[str, Any], record: dict[str, Any],
          frozen: dict[str, Any]) -> None:
    selected = observations(record)
    for name, observation in selected.items():
        entry = frozen.get("sources", {}).get(observation.source_id, {}).get(observation.observed_sha256)
        if (entry is None or entry.get("source_id") != observation.source_id
                or entry.get("locator") != original_for_logical(current, name)
                or entry["sha256"] != observation.observed_sha256
                or entry["mode"] != record["source_adoption_modes"][name]):
            raise ProjectConflict("The new input witness requires its exact frozen source bytes and original locator.")
        io.get(entry)
        before = current["files"][name]
        value["files"][name] = {**before, **{key: entry[key] for key in ("sha256", "size", "mode")}}
    value["input_resources"] = sorted(set(current.get("input_resources", [])) | set(selected))
