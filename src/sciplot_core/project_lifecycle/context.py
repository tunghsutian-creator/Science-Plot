"""Invocation-scoped repository and command binding for format-compatible helpers.

Every application invocation installs its repository. Nested scientific/render
helpers cannot fall back to another writer; token reset also covers exceptions.
The stateless default serves historical standalone storage callers only.
"""
from collections.abc import Iterator, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .contracts import NormalizedCommand, RevisionToken
from .repository import FileProjectRepository, ProjectRepository, digest as digest, document_root as document_root, transaction_path as transaction_path

_repository: ContextVar[ProjectRepository | None] = ContextVar("sciplot_project_repository", default=None)
_command: ContextVar[NormalizedCommand | None] = ContextVar("sciplot_project_command", default=None)
_capabilities: ContextVar[dict[str, Any] | None] = ContextVar("sciplot_backend_capabilities", default=None)


def repository() -> ProjectRepository:
    selected = _repository.get()
    return selected if selected is not None else FileProjectRepository()


@contextmanager
def repository_scope(selected: ProjectRepository, *, capabilities: dict[str, Any] | None = None) -> Iterator[None]:
    token = _repository.set(selected)
    profile = _capabilities.set(capabilities)
    try:
        yield
    finally:
        _capabilities.reset(profile)
        _repository.reset(token)


@contextmanager
def command_scope(command: NormalizedCommand | None) -> Iterator[None]:
    token = _command.set(command)
    try:
        yield
    finally:
        _command.reset(token)


def capability_profile() -> dict[str, Any]:
    from copy import deepcopy

    profile = _capabilities.get()
    if profile is None and _repository.get() is None:
        from .capabilities import COMPATIBILITY_CAPABILITIES

        profile = COMPATIBILITY_CAPABILITIES
    if profile is None:
        raise RuntimeError("Managed compilation requires an explicitly composed backend capability profile.")
    return deepcopy(profile)


def command_for_transaction(transaction: dict[str, Any]) -> NormalizedCommand:
    request = transaction["request"]
    command = _command.get()
    if command is not None and command.idempotency_key == request["idempotency_key"]:
        return command
    original = transaction.get("rollback_request", transaction.get("reimport_request", request))
    original = {**original, "idempotency_key": request["idempotency_key"]}
    kind = ("rollback" if "rollback_request" in transaction else "reimport" if transaction.get("mode") == "reimport"
            else "export" if request.get("action") == "export" else "patch")
    return NormalizedCommand.create(kind, original, expected_revision=RevisionToken.of(transaction["before"]))


def validate_saved_command(transaction: dict[str, Any]) -> None:
    from sciplot_core.project_lifecycle.errors import EngineError

    current = _command.get()
    saved = transaction.get("normalized_command")
    from .journal_identity import saved_command

    saved_command(transaction)
    if current is not None and saved is not None and current.idempotency_key == saved["idempotency_key"]:
        if (current.kind != saved["kind"] or current.request_digest != saved["request_digest"]
                or current.authority.value != saved["authority"]
                or current.expected_revision is not None and current.expected_revision.to_payload() != saved["expected_revision"]):
            raise EngineError("document_idempotency_conflict", "This key identifies another original command.",
                              action="use_original_request")


def exists(path: Path) -> bool:
    return repository().exists(path)


def read(path: Path) -> dict[str, Any]:
    return repository().read(path)


def write(path: Path, payload: dict[str, Any]) -> None:
    repository().write(path, payload)


def load_head(root: Path) -> dict[str, Any]:
    return repository().load_head(root)


def load_revision(root: Path, revision: int) -> dict[str, Any]:
    return repository().load_revision(root, revision)


def commit(root: Path, document: dict[str, Any], binding: dict[str, Any], transaction: str) -> None:
    repository().commit(root, document, binding, transaction)


def active(root: Path) -> dict[str, Any] | None:
    return repository().active(root)


def persist(root: Path, transaction: dict[str, Any]) -> None:
    selected = repository()
    if not selected.exists(transaction_path(root, transaction["request"]["idempotency_key"])):
        transaction["normalized_command"] = command_for_transaction(transaction).to_payload()
    selected.persist(root, transaction)


def reserve(root: Path, transaction: dict[str, Any]) -> None:
    selected = repository()
    if not selected.exists(transaction_path(root, transaction["request"]["idempotency_key"])):
        transaction["normalized_command"] = command_for_transaction(transaction).to_payload()
    selected.reserve(root, transaction)


def external_project_session(root: Path) -> Any:
    return repository().lease(root)


def prepare_namespace(root: Path) -> None:
    repository().prepare_namespace(root)


def has_head(root: Path) -> bool:
    return repository().has_head(root)


def require_empty_output(output: Path) -> None:
    repository().require_empty_output(output)


def content_snapshot(path: Path) -> dict[str, Any]:
    return repository().content_snapshot(path)


def publish_content(path: Path, payload: bytes, verify_existing: Callable[[], Any]) -> None:
    repository().publish_content(path, payload, verify_existing)


def content_sha256(path: Path) -> str | None:
    try:
        snapshot = content_snapshot(path)
        value: str = snapshot["sha256"]
        return value
    except (OSError, ValueError):
        return None


def json_members(directory: Path, pattern: str) -> list[Path]:
    return repository().json_members(directory, pattern)


def create_namespace(root: Path) -> None:
    repository().create_namespace(root)
