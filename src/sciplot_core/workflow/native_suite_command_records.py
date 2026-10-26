"""Read the saved display command and its exact export child from one repository."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.project_commands import ProjectCommands
from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow.native_suite_generation import open_store, command_key

def _application(context: dict[str, Any]) -> tuple[FileProjectStore, ProjectCommands]:
    store = open_store(Path(context["workspace"]), Path(context["delivery"]))
    return store, ProjectCommands(store)


def _request(context: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {"adapter": "native_display", "figure_id": context["figure_id"], "request": request}


def _key(context: dict[str, Any], request: dict[str, Any]) -> str:
    return command_key("native_patch", {"figure": context["figure_id"], "key": request["idempotency_key"]})


def _preview_export(app: ProjectCommands, parent: dict[str, Any]) -> dict[str, Any] | None:
    records = [item for item in app.commands()
               if item.get("metadata", {}).get("request", {}).get("adapter") == "native_preview_export"
               and item["metadata"]["request"].get("parent") == parent["command_digest"]
               and item["phase"] == "complete"]
    return records[-1] if records else None
