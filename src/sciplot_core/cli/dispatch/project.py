"""Expose saved-project services without importing a GUI or model provider."""

from __future__ import annotations

import json
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.studio_core.control_results import compact_result
from sciplot_core.studio_core.document_edit import (
    apply_document_edit,
    preview_document_edit,
    preview_project_document,
)
from sciplot_core.studio_core.document_edit_commit import read_edit_operation
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_path


from sciplot_core.studio_core.project_capabilities import project_control_capabilities


def dispatch_project_control(args: Any) -> int:
    action = args.project_action
    if action == "create":
        from sciplot_core.cli.dispatch.project_create import dispatch_project_create

        return dispatch_project_create(args)
    if action == "capabilities":
        payload = project_control_capabilities()
    elif action == "style-capture":
        from sciplot_core.studio_core.sample_style_presets import capture_sample_style_preset

        payload = capture_sample_style_preset(args.target, figure_id=args.figure,
                                              samples=args.sample, output_dir=args.out)
    elif action == "annotations":
        from sciplot_core.studio_core.annotation_operations import inspect_annotation_state

        payload = inspect_annotation_state(args.target, figure_id=args.figure)
    elif action == "operations-preview":
        from sciplot_core.studio_core.annotation_operations import preview_document_operations

        operations = json.loads(args.operations.read_text(encoding="utf-8"))
        payload = preview_document_operations(
            args.target, operations, output_dir=args.out, figure_id=args.figure,
            expected_document_sha256=args.expected_document,
        )
    elif action == "peaks":
        from sciplot_core.studio_core.peak_analysis import inspect_peak_candidates

        payload = inspect_peak_candidates(
            args.target, figure_id=args.figure, object_path=args.object,
            window=json.loads(args.window.read_text(encoding="utf-8")),
            polarity=args.polarity, expected_document_sha256=args.expected_document,
        )
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
    _print_json(payload if getattr(args, "full", False) else compact_result(payload))
    return 1 if payload.get("status") == "blocked" else 0
