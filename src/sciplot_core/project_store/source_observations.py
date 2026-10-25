"""Explicit raw-input observations advance witnesses without installing originals."""

from collections.abc import Mapping
from typing import Any

from sciplot_core.project_commands.resources import SourceAdoption

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO
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
