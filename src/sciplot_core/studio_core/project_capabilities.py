"""Shared external control discovery for CLI and MCP adapters."""

from __future__ import annotations

from typing import Any


def project_control_capabilities() -> dict[str, Any]:
    from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities

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
            "annotations": "project annotations PROJECT [--figure FIGURE_ID] --json",
            "style_capture": "project style-capture PROJECT [--figure FIGURE_ID] [--sample LABEL] --out NEW_PRESET_DIRECTORY --json",
            "operations_preview": "project operations-preview PROJECT --figure FIGURE_ID --expected-document SHA256 --operations OPERATIONS_JSON --out NEW_DIRECTORY --json",
            "peaks": "project peaks PROJECT --figure FIGURE_ID --object WIDGET_PATH --expected-document SHA256 --window WINDOW_JSON --polarity maximum|minimum --json",
            "task_start": "task start --request REQUEST_JSON [--task-dir NEW_DIRECTORY] --json",
            "task_inspect": "task inspect TASK_DIRECTORY --json",
            "task_find": "task find SOURCE [--tasks-root HISTORY_DIRECTORY] [--limit 20] --json",
            "task_resume": "task resume TASK_DIRECTORY --response RESPONSE_JSON --json",
            "task_schema": "task capabilities --json",
            "group_start": "task group start --request EXPERIMENTS_JSON --group-dir NEW_DIRECTORY --json",
            "group_inspect": "task group inspect GROUP_DIRECTORY --json",
            "group_resume": "task group resume GROUP_DIRECTORY [--responses RESPONSES_JSON] --json",
            "group_schema": "task group capabilities --json",
            "comparison_start": "task compare start --request CANDIDATES_JSON --comparison-dir NEW_DIRECTORY --json",
            "comparison_inspect": "task compare inspect COMPARISON_DIRECTORY --json",
            "comparison_resume": "task compare resume COMPARISON_DIRECTORY --json",
            "comparison_select": "task compare select COMPARISON_DIRECTORY --selection SELECTION_JSON --json",
            "comparison_schema": "task compare capabilities --json",
            "mcp": "mcp",
        },
        "change_fields": ["object_path", "setting_path", "expected_value", "value"],
        "target_policy": "Use exact object paths and editable_fields from the current figure inspection.",
        "version_policy": "Bind changes to saved document SHA-256; stale project/source/delivery state is rejected.",
        "confirmation_policy": "Use existing user intent for authorized style changes; ask only for unresolved meaning or scope.",
        "readiness_policy": "Inspection and edit success are not a publication claim. Export validates the current complete delivery.",
        "session_policy": "External edits require all writable native windows for the project to be closed.",
        "annotation_operations": annotation_operation_capabilities(),
        "task_policy": "Local create/edit/export orchestration, durable tasks, reviewed edits and fresh source validation; no model calls by SciPlot.",
    }
