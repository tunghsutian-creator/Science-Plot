"""Validate exact native request and decision identity before any project repair."""
from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any
from sciplot_core.plot_document import validate_patch
from sciplot_core.plot_engine.contracts import validate_decide, validate_resume
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.project_commands import ProjectCommands
from sciplot_core.workflow.native_suite_generation import command_key
from sciplot_core.workflow.native_suite_objects import native_identity

NativeHandler = Callable[[Path, dict[str, Any]], dict[str, Any]]

def _admit_wire_before_runtime(operation: str) -> Callable[[NativeHandler], NativeHandler]:
    from functools import wraps
    def decorate(function: NativeHandler) -> NativeHandler:
        @wraps(function)
        def wrapped(target: Path, request: dict[str, Any]) -> dict[str, Any]:
            target = Path(target)
            value = ({"patch": validate_patch, "resume": validate_resume, "decide": validate_decide}[operation])(request)
            from sciplot_core.workflow.native_suite_runtime import read_bound_store
            store = read_bound_store(target)
            if store is not None:
                manifest = json.loads((store.root / "suite.json").read_bytes())
                selected = ([item["id"] for item in manifest["documents"] if item["id"] == target.stem]
                            if target.suffix.lower() == ".vsz" else [item["id"] for item in manifest["documents"]])
                if len(selected) != 1:
                    raise EngineError("native_object_figure_required", "Select one exact existing native figure.")
                identifier = selected[0]
                app = ProjectCommands(store)
                if operation == "decide":
                    if set(value) != {"decision_id", "base_revision", "accept"}:
                        raise EngineError("document_invalid_decision", "Native display decisions require boolean accept.")
                    record = app.query_decision(value["decision_id"])
                    if record is None:
                        aliases = [item for item in app.commands() if item.get("review", {}).get("legacy_decision_id") == value["decision_id"]]
                        if len(aliases) > 1:
                            raise EngineError("document_invalid_decision", "The decision identity is ambiguous.")
                        record = aliases[0] if aliases else None
                    if record is not None and (record.get("review", {}).get("adapter") != "native_display"
                            or record["result"].get("figure_id") != identifier
                            or record["result"].get("request", {}).get("base_revision") != value["base_revision"]):
                        raise EngineError("document_invalid_decision", "Use the exact saved decision for this selected figure.")
                else:
                    identity = native_identity(manifest["workspace"], identifier, [], "", "")["plot_id"]
                    if value["plot_id"] != identity:
                        raise EngineError("document_identity_conflict", "The request belongs to another native figure.")
                    record = app.query(command_key("native_patch", {"figure": identifier, "key": value["idempotency_key"]}))
                    if record is not None:
                        saved = record["metadata"]["request"]
                        saved_request = saved.get("request", {})
                        matches = (saved_request == value if operation == "patch" else
                                   all(saved_request.get(key) == item for key, item in value.items()))
                        if saved.get("adapter") != "native_display" or saved.get("figure_id") != identifier or not matches:
                            raise EngineError("document_idempotency_conflict", "Use the command's exact original identity.")
                # A new/unknown operation cannot repair another pending command.
                # Legacy record discovery proceeds only while all views are current.
                if record is None:
                    store.snapshot()
            return function(target, value)
        return wrapped
    return decorate
