"""Storage capability selected by composition, with one durable command owner."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from .resources import PreparedFile


class ProjectStore(Protocol):
    def snapshot(self, *, import_legacy: bool = False) -> dict[str, Any]: ...

    def reserve(self, command_id: str, command_digest: str, *, expected_generation: str | None,
                read_set: Mapping[str, str | None], write_set: Sequence[str],
                metadata: dict[str, Any] | None = None,
                projected_reads: Sequence[dict[str, str]] = ()) -> dict[str, Any]: ...

    def mark_applying(self, command_id: str, command_digest: str) -> dict[str, Any]: ...

    def publish(self, command_id: str, command_digest: str, *,
                writes: Mapping[str, bytes | Path | PreparedFile | None], result: dict[str, Any],
                sources: Sequence[dict[str, Any]] | None = None,
                artifacts: Mapping[str, bytes | Path | PreparedFile] | None = None,
                input_reads: Sequence[dict[str, str]] = ()) -> dict[str, Any]: ...

    def stage(self, command_id: str, command_digest: str, *,
              writes: Mapping[str, bytes | Path | PreparedFile | None], result: dict[str, Any], review: dict[str, Any],
              artifacts: Mapping[str, bytes | Path | PreparedFile] | None = None,
              sources: Sequence[dict[str, Any]] | None = None,
              input_reads: Sequence[dict[str, str]] = ()) -> dict[str, Any]: ...

    def decide(self, command_id: str, command_digest: str, *, decision_id: str, accept: bool) -> dict[str, Any]: ...

    def publish_staged(self, command_id: str, command_digest: str) -> dict[str, Any]: ...

    def query(self, command_id: str) -> dict[str, Any] | None: ...

    def commands(self) -> tuple[dict[str, Any], ...]: ...

    def recover(self) -> dict[str, Any]: ...
