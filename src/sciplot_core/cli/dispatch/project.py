"""Expose saved-project services without importing a GUI or model provider."""

from __future__ import annotations

import json
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.studio_core.document_edit import (
    apply_document_edit,
    preview_document_edit,
    preview_project_document,
)
from sciplot_core.studio_core.document_edit_commit import read_edit_operation
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_path


def project_control_capabilities() -> dict[str, Any]:
    return {
        "kind": "sciplot_project_control_capabilities",
        "version": 1,
        "task_entry": "external_ai",
        "model_configuration_required": False,
        "commands": {
            "create": "project create SOURCE --expected-plan PLAN_JSON [--out VISIBLE_DIRECTORY] --json",
            "inspect": "project inspect PROJECT [--figure FIGURE_ID] [--object WIDGET_PATH] --json",
            "preview": "project preview PROJECT --figure FIGURE_ID --out NEW_DIRECTORY --json",
            "edit_preview": "project edit-preview PROJECT --figure FIGURE_ID --expected-document SHA256 --changes CHANGES_JSON --out NEW_DIRECTORY --json",
            "edit_apply": "project edit-apply PROJECT --preview EDIT_PREVIEW_JSON --json",
            "operation": "project operation PROJECT --operation-id OPERATION_ID --json",
            "export": "studio PROJECT --export pdf,tiff_300 --json",
        },
        "change_fields": ["object_path", "setting_path", "expected_value", "value"],
        "target_policy": "Use exact object paths and editable_fields from the current figure inspection.",
        "version_policy": "Bind changes to saved document SHA-256; stale project/source/delivery state is rejected.",
        "confirmation_policy": "Use existing user intent for authorized style changes; ask only for unresolved meaning or scope.",
        "readiness_policy": "Inspection and edit success are not a publication claim. Export validates the current complete delivery.",
        "session_policy": "External edits require all writable native windows for the project to be closed.",
    }


def dispatch_project_control(args: Any) -> int:
    action = args.project_action
    if action == "create":
        from sciplot_core.cli.dispatch.project_create import dispatch_project_create

        return dispatch_project_create(args)
    if action == "capabilities":
        payload = project_control_capabilities()
    elif action == "inspect":
        payload = inspect_project(
            args.target, figure_id=args.figure, object_path=args.object
        )
    elif action == "preview":
        payload = preview_project_document(
            args.target, output_dir=args.out, figure_id=args.figure
        )
    elif action == "edit-preview":
        changes = json.loads(args.changes.read_text(encoding="utf-8"))
        if not isinstance(changes, list) or not all(
            isinstance(item, dict) for item in changes
        ):
            raise ValueError(
                "Changes must be a JSON list of native setting operations."
            )
        payload = preview_document_edit(
            args.target,
            changes,
            output_dir=args.out,
            figure_id=args.figure,
            expected_document_sha256=args.expected_document,
        )
    elif action == "edit-apply":
        review = json.loads(args.preview.read_text(encoding="utf-8"))
        if not isinstance(review, dict):
            raise ValueError("An edit preview must be a JSON object.")
        payload = apply_document_edit(args.target, review)
    else:
        payload = read_edit_operation(
            resolve_project_path(args.target), args.operation_id
        )
    _print_json(payload)
    return 1 if payload.get("status") == "blocked" else 0
