"""Typed command dispatch into the same public application use cases."""
from pathlib import Path
from typing import Any, Protocol, cast

from sciplot_core.project_lifecycle.errors import EngineError
from .admission import usecase
from .contracts import RevisionToken, NormalizedCommand, AuthorityMode
from .context import command_scope, exists, external_project_session, read, transaction_path, load_head, project_query
from .paths import canonical_path


class CommandTarget(Protocol):
    def create(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def patch(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]: ...
    def intent(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]: ...
    def rollback(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]: ...


class CommandDispatch:
    @usecase
    def execute(self, plot: Path, command: NormalizedCommand) -> dict[str, Any]:
        """Admit a typed command against its tagged immutable base snapshot."""
        if not isinstance(command, NormalizedCommand):
            raise EngineError("document_command_invalid", "Use a validated normalized command.")
        command.validate()
        target = cast(CommandTarget, self)
        if command.kind == "create":
            if command.expected_revision is not None:
                raise EngineError("document_revision_conflict", "Creation has no previous revision.")
            authority = (AuthorityMode.MANAGED if "template_definition" in command.original_request
                         and command.original_request.get("mode") != "legacy" else AuthorityMode.LEGACY_NATIVE)
            if command.authority != authority or command.business_request != command.original_request:
                raise EngineError("document_command_invalid", "Creation authority or canonical request does not match its use case.")
            return target.create(command.original_request)
        if command.kind not in {"patch", "intent", "rollback"} or command.expected_revision is None:
            raise EngineError("document_command_unsupported", "Use a supported command with its expected revision token.")
        root = canonical_path(plot)
        planning = command.kind == "intent" and command.original_request.get("mode") == "plan"
        with project_query(root) if planning else external_project_session(root):
            path = transaction_path(root, command.idempotency_key)
            document = read(path)["before"] if exists(path) else load_head(root)["document"]
            if RevisionToken.of(document) != command.expected_revision:
                raise EngineError("document_revision_conflict", "The command's authority or revision token is stale.")
            business = command.original_request
            if command.kind == "intent":
                from sciplot_core.plot_engine.typed_intent import compile_intent

                business, _ = compile_intent(document, command.original_request)
            if command.business_request != business:
                raise EngineError("document_command_invalid", "The canonical business request does not match the original command.")
            if planning:
                with command_scope(command):
                    return target.intent(root, command.original_request)
        with command_scope(command):
            return {"patch": target.patch, "intent": target.intent, "rollback": target.rollback}[command.kind](root, command.original_request)
