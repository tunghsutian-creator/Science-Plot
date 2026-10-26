"""Proven immutable input declarations, independent of ordinary source reads."""
from collections.abc import Mapping
from typing import Any

from sciplot_core.project_commands.resources import InputRead, SourceAdoption

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, digest
from .locators import original_for_logical


def values(record: Mapping[str, Any], frozen: Mapping[str, Any] | None = None) -> tuple[InputRead, ...]:
    result: dict[str, InputRead] = {}
    for supplied in (record.get("metadata", {}).get("input_reads", []),
                     frozen.get("input_reads", []) if frozen is not None else []):
        if not isinstance(supplied, list):
            raise ProjectStoreError("Immutable inputs require a closed typed declaration list.")
        for payload in supplied:
            item = InputRead.from_payload(payload)
            if item.resource in result and result[item.resource] != item:
                raise ProjectConflict("The command and sealed candidate disagree on an immutable input.")
            result[item.resource] = item
    return tuple(result[name] for name in sorted(result))


def require_metadata(record: Mapping[str, Any], expected_metadata: Mapping[str, Any] | None = None) -> None:
    metadata = record.get("metadata", {})
    supplied = expected_metadata if expected_metadata is not None else metadata
    typed = metadata.get("version") == 1 and {"project_id", "key", "request", "read_set", "write_set"}.issubset(metadata)
    if expected_metadata is None and not typed:
        return  # The low-level repository also supports existing opaque business metadata/digests.
    from sciplot_core.project_commands.contracts import ProjectCommand

    try:
        canonical = ProjectCommand.from_payload(supplied).command_digest
        valid = canonical == record["command_digest"] == digest(supplied) == digest(metadata)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ProjectConflict("The immutable input command metadata differs from its exact command digest.")


def require(io: StoreIO, current: Mapping[str, Any], record: Mapping[str, Any], *,
            observed: Mapping[str, SourceAdoption], frozen: Mapping[str, Any] | None = None) -> set[str]:
    require_metadata(record)
    if frozen is None and isinstance(record.get("draft"), dict):
        if record.get("metadata", {}).get("input_reads") or "input_reads" in record["draft"]:
            from .state import sealed_draft

            frozen = sealed_draft(io, dict(record))
    selected = values(record, frozen)
    if not selected:
        return set()
    for item in selected:
        entry = current["files"].get(item.resource)
        before = record["read_set"].get(item.resource)
        observation = observed.get(item.resource)
        expected = observation.observed_sha256 if observation else before
        if (entry is None or before != entry["sha256"] or before is None or expected != item.sha256
                or item.resource in record["write_set"]
                or observation is not None and observation.source_id != item.source_id):
            raise ProjectConflict("An immutable input must bind an exact existing read and cannot be an output write.")
        io.split(item.resource)
        if frozen is None:
            continue  # Reserve admits structure, not source bytes which do not exist yet.
        source = frozen.get("sources", {}).get(item.source_id, {}).get(item.sha256)
        if (source is None or source.get("source_id") != item.source_id or source.get("version") != item.sha256
                or source["sha256"] != item.sha256
                or source.get("locator") != original_for_logical(dict(current), item.resource)):
            raise ProjectConflict("An immutable input requires its exact same-batch source identity, origin and version.")
        mode = record.get("source_adoption_modes", {}).get(item.resource) if observation else entry["mode"]
        data = io.get(source)
        if (source["mode"] != mode or len(data) != source["size"]
                or observation is None and source["size"] != entry["size"]):
            raise ProjectConflict("The captured immutable input bytes, size or mode differ from the guarded member.")
    return {item.resource for item in selected}
