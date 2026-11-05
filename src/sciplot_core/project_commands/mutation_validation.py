"""Shared candidate validation; no concrete command/application or IO dependency."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from .resources import InputRead, PreparedFile, PreparedSource, SourceAdoption, resource_key
from .generated_outputs import MissingGeneratedOutput


class MutationDeclaration(Protocol):
    @property
    def writes(self) -> Mapping[str, bytes | Path | PreparedFile | None]: ...
    @property
    def result(self) -> dict[str, Any]: ...
    @property
    def sources(self) -> Sequence[dict[str, Any]] | None: ...
    @property
    def review(self) -> dict[str, Any] | None: ...
    @property
    def artifacts(self) -> Mapping[str, bytes | Path | PreparedFile]: ...
    @property
    def prepared_sources(self) -> tuple[PreparedSource, ...]: ...
    @property
    def input_reads(self) -> tuple[InputRead, ...]: ...



class CommandFacts(Protocol):
    @property
    def read_set(self) -> tuple[tuple[str, str | None], ...]: ...
    @property
    def write_set(self) -> tuple[str, ...]: ...
    @property
    def input_reads(self) -> tuple[InputRead, ...]: ...
    @property
    def source_adoptions(self) -> tuple[SourceAdoption, ...]: ...
    @property
    def missing_outputs(self) -> tuple[MissingGeneratedOutput, ...]: ...


def validate_mutation_for(candidate: MutationDeclaration, command: CommandFacts) -> None:
    writes, artifacts, result, review = candidate.writes, candidate.artifacts, candidate.result, candidate.review
    sources, prepared_sources, input_reads = candidate.sources, candidate.prepared_sources, candidate.input_reads
    validate_input_reads(input_reads, command)
    combined = {item.resource: item for item in command.input_reads}
    for declared in input_reads:
        if declared.resource in combined and combined[declared.resource] != declared:
            raise ValueError("The command and candidate disagree on an immutable input.")
        combined[declared.resource] = declared
    if set(writes) != set(command.write_set):
        raise ValueError("A candidate must contain exactly its admitted writes and deletions.")
    if any(writes[item.resource] is None for item in command.missing_outputs):
        raise ValueError("A missing generated output requires a real non-deleted fresh candidate.")
    for name, value in writes.items():
        resource_key(name)
        if value is not None and not isinstance(value, (bytes, Path, PreparedFile)):
            raise ValueError("Candidate content must be bytes, a staged file, or an explicit deletion.")
        if isinstance(value, PreparedFile):
            value.__post_init__()
    for name, value in artifacts.items():
        resource_key(name)
        if not isinstance(value, (bytes, Path, PreparedFile)):
            raise ValueError("Review artifacts must be bytes or staged files.")
        if isinstance(value, PreparedFile):
            value.__post_init__()
    if not isinstance(result, dict) or review is not None and not isinstance(review, dict):
        raise ValueError("Candidate result and review must be JSON objects.")
    canonical_json_sha256(result, allow_nan=False)
    if review is not None:
        canonical_json_sha256(review, allow_nan=False)
    if sources is not None:
        canonical_json_sha256(list(sources), allow_nan=False)
    for source in prepared_sources:
        if not isinstance(source, PreparedSource):
            raise ValueError("Prepared sources must be explicit captured values.")
        source.__post_init__()
    declarations = [*sources] if sources is not None else []
    declarations.extend(source.to_storage_payload() for source in prepared_sources)
    for declared in combined.values():
        if not any(item.get("source_id") == declared.source_id and item.get("version") == declared.sha256
                   for item in declarations):
            raise ValueError("An immutable input needs its exact same-batch captured source version.")
    for observed in command.source_adoptions:
        if not any(item.get("source_id") == observed.source_id and item.get("version") == observed.observed_sha256
                   for item in declarations):
            raise ValueError("A new raw observation must have its exact declared source version.")


def validate_input_reads(values: Sequence[InputRead], command: CommandFacts | None = None) -> tuple[InputRead, ...]:
    declared: dict[str, InputRead] = {}
    for item in values:
        if not isinstance(item, InputRead):
            raise ValueError("Immutable input reads must use their typed resource declaration.")
        item.__post_init__()
        if item.resource in declared and declared[item.resource] != item:
            raise ValueError("Immutable input reads disagree on one resource identity/version.")
        declared[item.resource] = item
        if command is None:
            continue
        reads = dict(command.read_set)
        adoption = next((value for value in command.source_adoptions if value.resource == item.resource), None)
        expected = adoption.observed_sha256 if adoption else reads.get(item.resource)
        if (item.resource in command.write_set or expected is None or expected != item.sha256
                or adoption is not None and adoption.source_id != item.source_id):
            raise ValueError("An immutable input must bind a guarded source read and cannot be an output.")
    return tuple(declared[name] for name in sorted(declared))
