"""Integrity of additive command metadata inside the original transaction journal."""
from typing import Any
from sciplot_core.foundation.json_hashing import canonical_json_sha256

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
        rollback = transaction.get("rollback_request")
        if (command.kind == "rollback") != (rollback is not None):
            raise ValueError("Rollback semantics and command kind disagree.")
        if rollback is not None:
            business = rollback
            execution = transaction["request"]
            if execution != rollback:
                from sciplot_core.plot_document import validate_patch

                validate_patch(execution)
                if (token is None or execution["plot_id"] != token.plot_id or execution["base_revision"] != token.revision
                        or execution["idempotency_key"] != rollback["idempotency_key"]
                        or execution["intent_class"] != "review"):
                    raise ValueError("The frozen legacy inverse patch does not bind this rollback.")
            if transaction["request_hash"] != canonical_json_sha256(execution, allow_nan=False):
                raise ValueError("The frozen rollback execution request changed.")
        if (command.to_payload() != saved or command.business_request != business
                or command.idempotency_key != transaction["request"]["idempotency_key"]
                or token != RevisionToken.of(transaction["before"])):
            raise ValueError("Command and original journal disagree.")
        return command
    except (KeyError, TypeError, ValueError) as exc:
        raise EngineError("document_state_invalid", "The saved normalized command does not match its frozen journal.") from exc
