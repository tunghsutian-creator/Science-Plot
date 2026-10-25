"""Admit once, prepare off-line, publish once; unknown outcomes never reexecute."""

from collections.abc import Callable
import json
from typing import Any

from .contracts import CommandKind, ProjectCommand, ProjectMutation
from .errors import ProjectCommandError, ProjectCommandUnknown
from .ports import ProjectStore


class ProjectCommands:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    @staticmethod
    def _sources(candidate: ProjectMutation) -> list[dict[str, Any]] | None:
        values = [*(candidate.sources or ()), *(source.to_storage_payload() for source in candidate.prepared_sources)]
        return values or None

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
            result=candidate.result, sources=self._sources(candidate), artifacts=candidate.artifacts))

    def publish_prepared(self, command: ProjectCommand, candidate: ProjectMutation) -> dict[str, Any]:
        """Resume a sealed physical write without admitting any native callback."""
        candidate.validate_for(command)
        expected = candidate.prepared_digest
        if (command.kind not in {CommandKind.SEMANTIC_RECORD, CommandKind.ATTACHMENT_IMPORT}
                or json.loads(command.request_json).get("prepared_digest") != expected):
            raise ProjectCommandError("project_prepared_publication_invalid", "The prepared bytes require their exact storage command binding.")
        record = self._admit(command)
        self.store.recover()
        current = self.store.query(command.key)
        if current is not None:
            record = self._bound(command, current)
        if record.get("phase") == "complete":
            return {**record, "replayed": True}
        if record.get("phase") == "reserved":
            record = self._bound(command, self.store.stage(
                command.key, command.command_digest, writes=candidate.writes, result=candidate.result,
                review={"publication": "prepared_storage", "prepared_digest": expected,
                        "candidate_review": candidate.review}, artifacts=candidate.artifacts,
                sources=self._sources(candidate)))
        if record.get("phase") in {"needs_review", "accepted"}:
            review = record.get("review", {})
            if review.get("publication") != "prepared_storage" or review.get("prepared_digest") != expected:
                raise ProjectCommandError("project_prepared_publication_invalid", "An interactive or different candidate cannot be automatically accepted.")
            return self.decide(command, decision_id=record["decision_id"], accept=True)
        raise ProjectCommandUnknown()

    def preview(self, command: ProjectCommand, prepare: Callable[[], ProjectMutation]) -> dict[str, Any]:
        candidate = self._prepare(command, prepare)
        if isinstance(candidate, dict):
            return candidate
        return self._bound(command, self.store.stage(
            command.key, command.command_digest, writes=candidate.writes,
            result=candidate.result, review=candidate.review or {}, artifacts=candidate.artifacts,
            sources=self._sources(candidate)))

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
        prior = self.store.query(command.key)
        if prior is None:
            raise ProjectCommandError("project_command_unknown", "No saved operation belongs to this command.")
        record = self._bound(command, prior)
        self.store.recover()
        repaired = self.store.query(command.key)
        if repaired is not None:
            record = self._bound(command, repaired)
        if record.get("phase") == "accepted":
            return self._bound(command, self.store.publish_staged(command.key, command.command_digest))
        review = record.get("review", {})
        if (record.get("phase") == "needs_review"
                and command.kind in {CommandKind.SEMANTIC_RECORD, CommandKind.ATTACHMENT_IMPORT}
                and review.get("publication") == "prepared_storage"
                and review.get("prepared_digest") == json.loads(command.request_json).get("prepared_digest")):
            return self.decide(command, decision_id=record["decision_id"], accept=True)
        if record.get("phase") in {"complete", "rejected", "needs_review", "reserved"}:
            return record
        raise ProjectCommandUnknown()

    def query(self, key: str) -> dict[str, Any] | None:
        return self.store.query(key)

    def commands(self) -> tuple[dict[str, Any], ...]:
        return self.store.commands()

    def query_decision(self, decision_id: str) -> dict[str, Any] | None:
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("Use the exact saved preview decision identity.")
        matching = [record for record in self.store.commands() if record.get("decision_id") == decision_id]
        if len(matching) > 1:
            raise ProjectCommandError("project_command_decision_ambiguous", "The decision is not uniquely bound to one command.")
        return matching[0] if matching else None
