"""Application invocation scope and original-command admission."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar

from sciplot_core.plot_document import DocumentError

from .context import command_scope, exists, load_head, read, repository_scope, transaction_path
from .contracts import NormalizedCommand, RevisionToken


P = ParamSpec("P")
R = TypeVar("R")


def usecase(operation: Callable[Concatenate[Any, P], R]) -> Callable[Concatenate[Any, P], R]:
    @wraps(operation)
    def invoke(self: Any, /, *args: P.args, **kwargs: P.kwargs) -> R:
        with repository_scope(self.repository, capabilities=self.capabilities):
            return operation(self, *args, **kwargs)
    return invoke


@contextmanager
def admitted(root: Path, kind: str, request: dict[str, Any]) -> Iterator[NormalizedCommand]:
    """An idempotency key binds the literal business command before compilation.

    Replays use their original base snapshot. Old journal payloads remain intact;
    their established request-hash validation stays in the old-format reader.
    """
    path = transaction_path(root, request["idempotency_key"])
    saved = read(path) if exists(path) else None
    document = saved["before"] if saved is not None else load_head(root)["document"]
    token = RevisionToken.of(document)
    business = request
    if kind == "intent":
        from sciplot_core.plot_engine.typed_intent import compile_intent

        business, _ = compile_intent(document, request)
    command = NormalizedCommand.create(kind, request, expected_revision=token, business_request=business)
    if saved is None:
        if request.get("plot_id", token.plot_id) != token.plot_id:
            raise DocumentError("document_identity_conflict", "The command belongs to a different plot.")
        if request["base_revision"] != token.revision:
            raise DocumentError("document_revision_conflict", "The command requires the current revision.")
    else:
        from .context import validate_saved_command

        with command_scope(command):
            validate_saved_command(saved)
    with command_scope(command):
        yield command
