"""Integrity of additive command metadata inside the original transaction journal."""
from typing import Any

from sciplot_core.project_lifecycle.errors import EngineError
from .contracts import AuthorityMode, NormalizedCommand, RevisionToken


def saved_command(transaction: dict[str, Any]) -> NormalizedCommand | None:
    saved = transaction.get("normalized_command")
    if saved is None:
        return None
    try:
        expected = saved["expected_revision"]
        token = RevisionToken(**{**expected, "authority": AuthorityMode(expected["authority"])}) if expected else None
        command = NormalizedCommand.create(saved["kind"], saved["original_request"], expected_revision=token,
                                           authority=AuthorityMode(saved["authority"]), business_request=saved["business_request"])
        business = transaction["request"]
        if transaction.get("mode") == "reimport":
            business = {**transaction["reimport_request"], "idempotency_key": business["idempotency_key"]}
        if (command.to_payload() != saved or command.business_request != business
                or command.idempotency_key != transaction["request"]["idempotency_key"]
                or token != RevisionToken.of(transaction["before"])):
            raise ValueError("Command and original journal disagree.")
        return command
    except (KeyError, TypeError, ValueError) as exc:
        raise EngineError("document_state_invalid", "The saved normalized command does not match its frozen journal.") from exc
