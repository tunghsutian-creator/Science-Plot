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
from sciplot_core.project_lifecycle.figure_observation import resolve_project_path
from sciplot_core.studio_core.project_query import inspect_project


from sciplot_core.studio_core.project_capabilities import project_control_capabilities


def dispatch_project_control(args: Any) -> int:
    action = args.project_action
    if action == "create":
        from sciplot_core.cli.dispatch.project_create import dispatch_project_create

        return dispatch_project_create(args)
    if action in {"pdf-review-create", "pdf-review-read"}:
        from sciplot_core.cli.dispatch.pdf_review import dispatch_pdf_review

        return dispatch_pdf_review(args)
    if action in {"bundle-export", "bundle-import"}:
        from sciplot_core.project_lifecycle.relocation import export_project_bundle, import_project_bundle

        relocate = export_project_bundle if action == "bundle-export" else import_project_bundle
        _print_json(relocate(args.target, args.out))
        return 0
    if action == "legacy-convert":
        from sciplot_core.studio_core.legacy_conversion import convert_legacy_plot

        result = convert_legacy_plot(args.target, output=args.out, figure_id=args.figure,
                                     x_unit=args.x_unit, y_unit=args.y_unit)
        _print_json(result)
        return 0 if result["status"] == "converted" else 1
    if action == "legacy-redraw":
        from sciplot_core.studio_core.legacy_saved_plot import redraw_legacy_plot

        _print_json(redraw_legacy_plot(args.target, output=args.out, formats=args.formats.split(","), figure_id=args.figure))
        return 0
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
        from sciplot_core.project_lifecycle.legacy_public_policy import require_public_editable

        require_public_editable(args.target, figure_id=args.figure)
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
        from .project_create import with_project_owner

        payload = with_project_owner(lambda: inspect_project(
            args.target, figure_id=args.figure, object_path=args.object
        ))
    elif action == "preview":
        payload = preview_project_document(
            args.target, output_dir=args.out, figure_id=args.figure
        )
    elif action == "edit-preview":
        from sciplot_core.project_lifecycle.legacy_public_policy import require_public_editable

        require_public_editable(args.target, figure_id=args.figure)
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
        from sciplot_core.project_lifecycle.legacy_public_policy import require_public_editable

        require_public_editable(args.target, figure_id=review.get("figure_id"), prior_review=review)
        payload = apply_document_edit(args.target, review)
    else:
        payload = read_edit_operation(
            resolve_project_path(args.target), args.operation_id
        )
    _print_json(payload if getattr(args, "full", False) else compact_result(payload))
    return 1 if payload.get("status") == "blocked" else 0
