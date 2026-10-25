"""Admit once, prepare off-line, publish once; unknown outcomes never reexecute."""

from collections.abc import Callable
from typing import Any

from .contracts import ProjectCommand, ProjectMutation
from .errors import ProjectCommandError, ProjectCommandUnknown
from .ports import ProjectStore


class ProjectCommands:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    def _bound(self, command: ProjectCommand, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("command_digest") != command.command_digest:
            raise ProjectCommandError("project_command_key_conflict", "This key belongs to a different immutable command.")
        if record.get("project_id") != command.project_id:
            raise ProjectCommandError("project_command_project_conflict", "The saved command belongs to another project.")
        return record

    def _admit(self, command: ProjectCommand) -> dict[str, Any]:
        command.__post_init__()
        prior = self.store.query(command.key)
        if prior is not None:
            return self._bound(command, prior)
        current = self.store.snapshot()
        if current["project_id"] != command.project_id:
            raise ProjectCommandError("project_command_project_conflict", "The command belongs to another project.")
        return self._bound(command, self.store.reserve(
            command.key, command.command_digest, expected_generation=command.expected_generation,
            read_set=dict(command.read_set), write_set=command.write_set, metadata=command.to_payload(),
            projected_reads=[item.to_payload() for item in command.projected_reads]))

    @staticmethod
    def _may_prepare(record: dict[str, Any]) -> bool:
        phase = record.get("phase")
        if phase == "reserved":
            return True
        if phase in {"complete", "rejected", "needs_review", "accepted"}:
            return False
        raise ProjectCommandUnknown()

    def _prepare(self, command: ProjectCommand, prepare: Callable[[], ProjectMutation]) -> ProjectMutation | dict[str, Any]:
        record = self._admit(command)
        if not self._may_prepare(record):
            return {**record, "replayed": True}
        # The repository atomically admits only one reserved->applying transition.
        # If preparation raises or the process dies, its saved state remains unknown.
        entered = self._bound(command, self.store.mark_applying(command.key, command.command_digest))
        if entered.get("phase") != "applying":
            raise ProjectCommandUnknown()
        candidate = prepare()
        if not isinstance(candidate, ProjectMutation):
            raise TypeError("A project preparation must return one complete typed mutation.")
        candidate.validate_for(command)
        return candidate

    def execute(self, command: ProjectCommand, prepare: Callable[[], ProjectMutation]) -> dict[str, Any]:
        candidate = self._prepare(command, prepare)
        if isinstance(candidate, dict):
            return candidate
        return self._bound(command, self.store.publish(
            command.key, command.command_digest, writes=candidate.writes,
            result=candidate.result, sources=candidate.sources, artifacts=candidate.artifacts))

    def preview(self, command: ProjectCommand, prepare: Callable[[], ProjectMutation]) -> dict[str, Any]:
        candidate = self._prepare(command, prepare)
        if isinstance(candidate, dict):
            return candidate
        if candidate.sources is not None:
            # Source updates must retain this fact inside the frozen staged payload;
            # this is not an implicit source-registration side effect of a preview.
            review = {**(candidate.review or {}), "source_versions": list(candidate.sources)}
        else:
            review = candidate.review or {}
        return self._bound(command, self.store.stage(
            command.key, command.command_digest, writes=candidate.writes,
            result=candidate.result, review=review, artifacts=candidate.artifacts))

    def decide(self, command: ProjectCommand, *, decision_id: str, accept: bool) -> dict[str, Any]:
        if type(accept) is not bool:
            raise ValueError("A decision must explicitly accept or reject the exact frozen preview.")
        prior = self.store.query(command.key)
        if prior is None:
            raise ProjectCommandError("project_command_unknown", "No saved preview belongs to this command.")
        record = self._bound(command, prior)
        if record.get("phase") not in {"needs_review", "accepted", "rejected", "complete"}:
            raise ProjectCommandUnknown()
        decided = self._bound(command, self.store.decide(
            command.key, command.command_digest, decision_id=decision_id, accept=accept))
        if accept and decided.get("phase") == "accepted":
            return self._bound(command, self.store.publish_staged(command.key, command.command_digest))
        return decided

    def resume(self, command: ProjectCommand) -> dict[str, Any]:
        self.store.recover()
        prior = self.store.query(command.key)
        if prior is None:
            raise ProjectCommandError("project_command_unknown", "No saved operation belongs to this command.")
        record = self._bound(command, prior)
        if record.get("phase") == "accepted":
            return self._bound(command, self.store.publish_staged(command.key, command.command_digest))
        if record.get("phase") in {"complete", "rejected", "needs_review", "reserved"}:
            return record
        raise ProjectCommandUnknown()

    def query(self, key: str) -> dict[str, Any] | None:
        return self.store.query(key)
