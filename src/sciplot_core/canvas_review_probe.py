from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.persistence import read_operation_journal

CANVAS_REVIEW_PROBE_KIND = "sciplot_canvas_review_probe"
CANVAS_REVIEW_PROBE_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(
        value for value in path.rglob("*") if value.is_file()
    ):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(child.read_bytes())
    return digest.hexdigest()


def _export_hashes(exports: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item["format"]): file_sha256(Path(str(item["path"])))
        for item in exports
        if item.get("exists") is True
    }


def _pdf_visual_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with fitz.open(path) as document:
        digest.update(str(document.page_count).encode("utf-8"))
        for page in document:
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(2.0, 2.0),
                alpha=False,
            )
            digest.update(
                f"{pixmap.width}x{pixmap.height}:{pixmap.n}".encode("utf-8")
            )
            digest.update(pixmap.samples)
    return digest.hexdigest()


def _export_content_hashes(
    exports: list[dict[str, Any]],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in exports:
        if item.get("exists") is not True:
            continue
        export_format = str(item["format"])
        path = Path(str(item["path"]))
        hashes[export_format] = (
            _pdf_visual_hash(path)
            if export_format == "pdf"
            else file_sha256(path)
        )
    return hashes


def _copy_target(source: Path, run_root: Path) -> Path:
    if source.is_dir():
        target = run_root / "project"
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns(
                ".sciplot_canvas",
                "runs",
                "__pycache__",
            ),
        )
        return target
    target = run_root / source.name
    shutil.copy2(source, target)
    return target


def run_canvas_review_probe(
    target: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Exercise the full non-exported review and native-promotion lifecycle."""

    source = target.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="canvas_review_probe_", dir=resolved_output)
    )
    summary_path = run_root / "canvas_review_probe.json"
    screenshot_path = run_root / "review_overlay.png"
    promoted_screenshot_path = run_root / "review_promoted.png"
    stderr_log = run_root / "logs" / "canvas_review_stderr.log"
    progress_path = run_root / "progress.log"
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    error: dict[str, str] | None = None
    window: Any = None
    reopened: Any = None
    final_window: Any = None

    source_hash_before = _tree_hash(source)
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from sciplot_core.studio import (
            _capture_process_stderr,
            export_studio_document,
        )
        from PyQt6 import QtWidgets

        from sciplot_gui.main_window import SciPlotCanvasWindow
        from sciplot_gui.workspace import resolve_canvas_workspace

        progress_path.write_text("imports_ready\n", encoding="utf-8")
        application = QtWidgets.QApplication.instance()
        if application is None:
            application = QtWidgets.QApplication([])
        application.setApplicationName("SciPlot Canvas Review Probe")
        application.setQuitOnLastWindowClosed(False)
        copied_target = _copy_target(source, run_root)
        progress_path.write_text("target_copied\n", encoding="utf-8")
        workspace = resolve_canvas_workspace(copied_target)
        progress_path.write_text("workspace_resolved\n", encoding="utf-8")
        baseline_exports = export_studio_document(
            workspace.document_path,
            formats=["pdf", "tiff_300"],
            output_dir=run_root / "baseline_exports",
        )
        baseline_hashes = _export_hashes(
            list(baseline_exports.get("exports") or [])
        )
        baseline_content_hashes = _export_content_hashes(
            list(baseline_exports.get("exports") or [])
        )
        progress_path.write_text("baseline_exported\n", encoding="utf-8")
        document_hash_before = file_sha256(workspace.document_path)

        with _capture_process_stderr(stderr_log):
            progress_path.write_text("before_window\n", encoding="utf-8")
            window = SciPlotCanvasWindow(workspace, interactive=False)
            progress_path.write_text("window_constructed\n", encoding="utf-8")
            window.resize(1380, 860)
            window.show()
            application.processEvents()

            adapter = window.controller.adapter
            initial_render = adapter.render_fingerprint()
            initial_object_ids_by_path = {
                str(item["path"]): str(item["object_id"])
                for item in window.controller.inventory
            }
            original_staged_resolver = window._resolve_staged_fields
            window.inspector_tabs.setCurrentIndex(0)
            window.review_overlay.set_tool("select")
            window.review_panel.set_tool("select")
            window._resolve_staged_fields = lambda _action: False
            window._set_review_tool("arrow")
            cancelled_workspace_switch_safe = (
                window.inspector_tabs.currentIndex() == 0
                and window.review_overlay.tool == "select"
                and window.review_panel.current_tool == "select"
            )
            window._resolve_staged_fields = original_staged_resolver
            page_rect = adapter._page_scene_rect()
            graph_item = next(
                item
                for item in window.controller.inventory
                if item.get("object_type") == "graph"
                and str(item.get("path")).startswith(
                    f"{adapter.current_page_path}"
                )
            )
            data_item = None
            for item in window.controller.inventory:
                if item.get("object_type") not in {
                    "xy",
                    "boxplot",
                    "image",
                    "contour",
                } or not str(item.get("path")).startswith(
                    f"{adapter.current_page_path}/"
                ):
                    continue
                try:
                    adapter._data_axes_context(
                        target_object_id=str(item["object_id"]),
                        session=window.controller.session,
                    )
                except (RuntimeError, ValueError):
                    continue
                data_item = item
                break
            if data_item is None:
                raise ValueError(
                    "Canvas review probe needs one graph-bound data object."
                )
            graph_rect = adapter._widget_scene_rect(
                adapter._widget(str(graph_item["path"]))
            )

            def page_point(x: float, y: float) -> list[float]:
                return [
                    page_rect.left() + page_rect.width() * x,
                    page_rect.top() + page_rect.height() * y,
                ]

            annotations = [
                window.controller.create_review_annotation_from_scene(
                    shape="text",
                    scene_geometry={"position": page_point(0.10, 0.10)},
                    coordinate_space="normalized_page",
                    text="Check peak assignment",
                ),
                window.controller.create_review_annotation_from_scene(
                    shape="arrow",
                    scene_geometry={
                        "start": page_point(0.18, 0.27),
                        "end": page_point(0.34, 0.18),
                    },
                    coordinate_space="page",
                    text="Point to feature",
                ),
                window.controller.create_review_annotation_from_scene(
                    shape="rectangle",
                    scene_geometry={
                        "rect": [
                            graph_rect.left() + graph_rect.width() * 0.35,
                            graph_rect.top() + graph_rect.height() * 0.18,
                            graph_rect.width() * 0.18,
                            graph_rect.height() * 0.20,
                        ]
                    },
                    coordinate_space="graph",
                    target_object_id=str(graph_item["object_id"]),
                    text="Region of interest",
                ),
                window.controller.create_review_annotation_from_scene(
                    shape="ellipse",
                    scene_geometry={
                        "rect": [
                            graph_rect.left() + graph_rect.width() * 0.62,
                            graph_rect.top() + graph_rect.height() * 0.20,
                            graph_rect.width() * 0.16,
                            graph_rect.height() * 0.18,
                        ]
                    },
                    coordinate_space="object",
                    target_object_id=str(graph_item["object_id"]),
                    text="Compare this region",
                ),
                window.controller.create_review_annotation_from_scene(
                    shape="freehand",
                    scene_geometry={
                        "points": [
                            [
                                graph_rect.left() + graph_rect.width() * 0.20,
                                graph_rect.top() + graph_rect.height() * 0.68,
                            ],
                            [
                                graph_rect.left() + graph_rect.width() * 0.28,
                                graph_rect.top() + graph_rect.height() * 0.61,
                            ],
                            [
                                graph_rect.left() + graph_rect.width() * 0.36,
                                graph_rect.top() + graph_rect.height() * 0.70,
                            ],
                        ]
                    },
                    coordinate_space="data",
                    target_object_id=str(data_item["object_id"]),
                    text="Freehand review trace",
                ),
            ]
            window._refresh_review_layer(
                selected_id=annotations[0].annotation_id
            )
            application.processEvents()
            overlay_screenshot_saved = window.grab().save(
                str(screenshot_path),
                "PNG",
            )
            overlay_count = len(window.review_overlay._items)
            render_with_reviews = adapter.render_fingerprint()
            review_revision = window.controller.session.revision
            review_document_hash = file_sha256(workspace.document_path)

            scene_before_zoom = {
                annotation.annotation_id: adapter.review_geometry_to_scene(
                    annotation,
                    window.controller.session,
                )
                for annotation in annotations
            }
            window._set_zoom(adapter.zoom_factor * 1.2)
            scene_after_zoom = {
                annotation.annotation_id: adapter.review_geometry_to_scene(
                    annotation,
                    window.controller.session,
                )
                for annotation in annotations
            }
            zoom_moved_anchor_spaces = {
                annotation.coordinate_space: (
                    scene_before_zoom[annotation.annotation_id]
                    != scene_after_zoom[annotation.annotation_id]
                )
                for annotation in annotations
            }
            window._set_zoom(1.0)
            anchor_qa = window.controller.run_structural_qa()

            moved_arrow_scene = {
                "start": page_point(0.20, 0.30),
                "end": page_point(0.38, 0.20),
            }
            moved_arrow = window.controller.move_review_annotation_from_scene(
                annotations[1].annotation_id,
                moved_arrow_scene,
            )
            updated_text = window.controller.update_review_annotation(
                annotations[0].annotation_id,
                text="Confirm peak assignment",
                style={
                    **annotations[0].style.to_dict(),
                    "color": "#ff3b30",
                },
            )
            window._refresh_review_layer(
                selected_id=updated_text.annotation_id
            )
            application.processEvents()

            review_export = window.export_current()
            review_export_hashes = _export_hashes(
                list(review_export.get("exports") or [])
            )
            review_export_content_hashes = _export_content_hashes(
                list(review_export.get("exports") or [])
            )
            prepromotion_journal = read_operation_journal(
                workspace.journal_path
            )
            window.close()
            application.processEvents()
            window = None

            reopened = SciPlotCanvasWindow(workspace, interactive=False)
            reopened.resize(1380, 860)
            reopened.show()
            application.processEvents()
            reopened._refresh_review_layer()
            reopened_annotations = list(
                reopened.controller.review_annotations
            )
            reopened_active = reopened.controller.active_review_annotations()
            reopened_overlay_count = len(reopened.review_overlay._items)

            promotion_entries: list[dict[str, Any]] = []
            render_hashes = [reopened.controller.adapter.render_fingerprint()]
            for annotation in reopened_active:
                if annotation.shape == "freehand":
                    continue
                promotion_entries.append(
                    reopened.controller.promote_review_annotation(
                        annotation.annotation_id
                    )
                )
                render_hashes.append(
                    reopened.controller.adapter.render_fingerprint()
                )
            reopened._refresh_review_layer()
            application.processEvents()

            freehand = next(
                annotation
                for annotation in reopened.controller.review_annotations
                if annotation.shape == "freehand"
            )
            freehand_rejected = False
            try:
                reopened.controller.promote_review_annotation(
                    freehand.annotation_id
                )
            except ValueError:
                freehand_rejected = True

            promoted_before_undo = next(
                annotation
                for annotation in reopened.controller.review_annotations
                if annotation.shape == "ellipse"
            )
            undo_entry = reopened.undo_document()
            ellipse_after_undo = reopened.controller.review_annotation(
                promoted_before_undo.annotation_id
            )
            redo_entry = reopened.redo_document()
            ellipse_after_redo = reopened.controller.review_annotation(
                promoted_before_undo.annotation_id
            )

            reopened._refresh_review_layer()
            application.processEvents()
            promoted_screenshot_saved = reopened.grab().save(
                str(promoted_screenshot_path),
                "PNG",
            )
            reopened.save_document()
            promoted_export = reopened.export_current()
            promoted_export_hashes = _export_hashes(
                list(promoted_export.get("exports") or [])
            )
            promoted_export_content_hashes = _export_content_hashes(
                list(promoted_export.get("exports") or [])
            )
            final_revision = reopened.controller.session.revision
            final_document_hash = file_sha256(workspace.document_path)
            promoted_inventory = [
                item
                for item in reopened.controller.inventory
                if item.get("object_type")
                in {"label", "line", "rect", "ellipse"}
                and str(item.get("display_name", "")).startswith("review_")
            ]
            existing_object_ids_after_promotion = {
                str(item["path"]): str(item["object_id"])
                for item in reopened.controller.inventory
                if str(item.get("path")) in initial_object_ids_by_path
            }
            final_structural_qa = reopened.controller.run_structural_qa()
            reopened.close()
            application.processEvents()
            reopened = None

            final_window = SciPlotCanvasWindow(workspace, interactive=False)
            final_window.show()
            application.processEvents()
            final_annotations = list(
                final_window.controller.review_annotations
            )
            final_promoted = [
                annotation
                for annotation in final_annotations
                if annotation.state == "promoted"
            ]
            final_active = final_window.controller.active_review_annotations()
            final_native = [
                item
                for item in final_window.controller.inventory
                if item.get("object_type")
                in {"label", "line", "rect", "ellipse"}
                and str(item.get("display_name", "")).startswith("review_")
            ]
            journal = read_operation_journal(workspace.journal_path)

            checks.extend(
                [
                    _check(
                        "review_tools_exposed",
                        "The native Review workspace exposes all five drawing tools and every anchor mode",
                        set(final_window.review_panel.tool_buttons)
                        == {
                            "select",
                            "text",
                            "arrow",
                            "rectangle",
                            "ellipse",
                            "freehand",
                        }
                        and final_window.review_panel.anchor_combo.count() == 5
                        and final_window.review_action.shortcut().toString()
                        == "Ctrl+Shift+R",
                    ),
                    _check(
                        "cancelled_workspace_switch_does_not_arm_tool",
                        "Cancelling a protected Review workspace switch leaves drawing tools inactive",
                        cancelled_workspace_switch_safe,
                    ),
                    _check(
                        "five_review_shapes_persist",
                        "Text, arrow, rectangle, ellipse, and freehand marks persist in the sidecar",
                        len(annotations) == 5
                        and len(reopened_annotations) == 5
                        and {
                            annotation.shape
                            for annotation in reopened_annotations
                        }
                        == {
                            "text",
                            "arrow",
                            "rectangle",
                            "ellipse",
                            "freehand",
                        },
                    ),
                    _check(
                        "all_anchor_spaces_resolve",
                        "Page, normalized-page, graph, data, and object anchors survive zoom and structural QA",
                        {
                            annotation.coordinate_space
                            for annotation in annotations
                        }
                        == {
                            "page",
                            "normalized_page",
                            "graph",
                            "data",
                            "object",
                        }
                        and all(zoom_moved_anchor_spaces.values())
                        and anchor_qa.get("ready_for_artifact_qa") is True,
                        {
                            "before": scene_before_zoom,
                            "after": scene_after_zoom,
                            "moved_by_anchor": zoom_moved_anchor_spaces,
                            "qa": anchor_qa,
                        },
                    ),
                    _check(
                        "review_overlay_is_live",
                        "All active review marks render as selectable QGraphics overlays",
                        overlay_count == 5
                        and reopened_overlay_count == 5
                        and overlay_screenshot_saved,
                        {
                            "initial_count": overlay_count,
                            "reopened_count": reopened_overlay_count,
                            "screenshot": str(screenshot_path),
                        },
                    ),
                    _check(
                        "review_edits_do_not_advance_document_revision",
                        "Adding, moving, and styling review marks do not mutate the publication revision or renderer pixmap",
                        review_revision == 0
                        and render_with_reviews == initial_render
                        and moved_arrow.state == "review_only"
                        and updated_text.state == "review_only",
                        {
                            "revision": review_revision,
                            "render_before": initial_render,
                            "render_after": render_with_reviews,
                        },
                    ),
                    _check(
                        "review_marks_do_not_change_vsz",
                        "Review-only work leaves the canonical VSZ byte-identical",
                        document_hash_before == review_document_hash,
                        {
                            "before": document_hash_before,
                            "after": review_document_hash,
                        },
                    ),
                    _check(
                        "review_marks_do_not_leak_into_exports",
                        "Unpromoted review marks leave PDF page pixels and TIFF bytes unchanged",
                        baseline_content_hashes
                        == review_export_content_hashes
                        and review_export.get("ready_to_use") is True,
                        {
                            "baseline_bytes": baseline_hashes,
                            "with_reviews_bytes": review_export_hashes,
                            "baseline_content": baseline_content_hashes,
                            "with_reviews_content": review_export_content_hashes,
                        },
                    ),
                    _check(
                        "review_sidecar_reopens",
                        "Review marks survive close and reopen without recovery mode",
                        len(reopened_active) == 5
                        and all(
                            annotation.state == "review_only"
                            for annotation in reopened_active
                        ),
                    ),
                    _check(
                        "typed_native_promotion",
                        "Four promotable review shapes become typed native Veusz objects",
                        len(promotion_entries) == 4
                        and {item["object_type"] for item in promoted_inventory}
                        >= {"label", "line", "rect", "ellipse"}
                        and all(
                            (entry.get("batch") or {})
                            .get("operations", [{}])[0]
                            .get("operation_type")
                            == "add_widget"
                            for entry in promotion_entries
                        ),
                        {
                            "inventory": promoted_inventory,
                            "entries": promotion_entries,
                        },
                    ),
                    _check(
                        "promotion_preserves_existing_object_ids",
                        "Native annotation insertion does not transfer stable IDs away from existing figure objects",
                        existing_object_ids_after_promotion
                        == initial_object_ids_by_path,
                        {
                            "before": initial_object_ids_by_path,
                            "after": existing_object_ids_after_promotion,
                        },
                    ),
                    _check(
                        "freehand_promotion_is_honest",
                        "Freehand remains review-only because Veusz has no equivalent editable native object",
                        freehand_rejected
                        and final_active
                        and final_active[0].shape == "freehand",
                    ),
                    _check(
                        "promotion_redraws_live",
                        "Every native promotion changes the live figure render",
                        len(render_hashes) == 5
                        and len(set(render_hashes)) == len(render_hashes),
                        render_hashes,
                    ),
                    _check(
                        "promotion_undo_redo_restores_sidecar_state",
                        "Undo returns the promoted ellipse to review-only and redo promotes it again",
                        ellipse_after_undo.state == "review_only"
                        and ellipse_after_undo.promoted_object_id is None
                        and ellipse_after_redo.state == "promoted"
                        and undo_entry.get("review_transition", {}).get(
                            "direction"
                        )
                        == "undo"
                        and redo_entry.get("review_transition", {}).get(
                            "direction"
                        )
                        == "redo",
                    ),
                    _check(
                        "promoted_annotations_change_exact_current_exports",
                        "Promoted native annotations appear in the saved VSZ and final exports",
                        final_document_hash != document_hash_before
                        and promoted_export_content_hashes
                        != baseline_content_hashes
                        and promoted_export.get("ready_to_use") is True,
                        {
                            "baseline_bytes": baseline_hashes,
                            "promoted_bytes": promoted_export_hashes,
                            "baseline_content": baseline_content_hashes,
                            "promoted_content": promoted_export_content_hashes,
                            "document_before": document_hash_before,
                            "document_after": final_document_hash,
                        },
                    ),
                    _check(
                        "promoted_state_reopens",
                        "Promoted native annotations and the remaining freehand review mark survive reopen",
                        len(final_promoted) == 4
                        and len(final_native) >= 4
                        and len(final_active) == 1
                        and final_active[0].shape == "freehand",
                        {
                            "promoted": [
                                annotation.to_dict()
                                for annotation in final_promoted
                            ],
                            "native": final_native,
                            "active": [
                                annotation.to_dict()
                                for annotation in final_active
                            ],
                        },
                    ),
                    _check(
                        "review_structural_qa_passes",
                        "Review sidecar consistency and anchors pass structural QA after promotion",
                        final_structural_qa.get("ready_for_artifact_qa") is True
                        and not (
                            final_structural_qa.get("summary") or {}
                        ).get("failed_ids"),
                        final_structural_qa,
                    ),
                    _check(
                        "review_journal_is_auditable",
                        "Add, update, remove-independent promotion, undo, redo, save, and export events are journaled",
                        sum(
                            entry.get("event") == "review_annotation_added"
                            for entry in journal
                        )
                        == 5
                        and sum(
                            entry.get("event")
                            == "review_annotation_promoted"
                            for entry in journal
                        )
                        == 4
                        and any(
                            entry.get("event") == "review_annotation_updated"
                            for entry in prepromotion_journal
                        )
                        and any(
                            entry.get("event") == "undo"
                            and entry.get("review_transition")
                            for entry in journal
                        )
                        and any(
                            entry.get("event") == "redo"
                            and entry.get("review_transition")
                            for entry in journal
                        ),
                        [entry.get("event") for entry in journal],
                    ),
                    _check(
                        "review_visual_artifacts_exist",
                        "Review-only and promoted Canvas screenshots are available for visual QA",
                        screenshot_path.is_file()
                        and promoted_screenshot_path.is_file()
                        and promoted_screenshot_saved,
                        {
                            "review": str(screenshot_path),
                            "promoted": str(promoted_screenshot_path),
                        },
                    ),
                    _check(
                        "source_target_is_immutable",
                        "The supplied source project or VSZ is never modified by the probe",
                        source_hash_before == _tree_hash(source),
                    ),
                ]
            )
            evidence = {
                "workspace": workspace.to_dict(),
                "annotation_count": len(annotations),
                "overlay_count": overlay_count,
                "reopened_overlay_count": reopened_overlay_count,
                "baseline_export_hashes": baseline_hashes,
                "review_export_hashes": review_export_hashes,
                "promoted_export_hashes": promoted_export_hashes,
                "document_hash_before": document_hash_before,
                "document_hash_after": final_document_hash,
                "promotion_count": len(promotion_entries),
                "final_revision": final_revision,
                "final_promoted_count": len(final_promoted),
                "final_active_count": len(final_active),
                "journal_event_count": len(journal),
            }
    except Exception as exc:
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        checks.append(
            _check(
                "canvas_review_probe_exception",
                "The review lifecycle completes without an exception",
                False,
                error,
            )
        )
    finally:
        for candidate in (window, reopened, final_window):
            if candidate is not None:
                try:
                    candidate.set_close_policy_for_test("keep_recovery")
                    candidate.close()
                except Exception:
                    try:
                        candidate.controller.close()
                    except Exception:
                        pass

    failed_ids = [
        str(check["id"]) for check in checks if check["status"] == "failed"
    ]
    payload = {
        "kind": CANVAS_REVIEW_PROBE_KIND,
        "version": CANVAS_REVIEW_PROBE_VERSION,
        "generated_at": _now(),
        "status": "passed" if not failed_ids else "failed",
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(
                check["status"] == "passed" for check in checks
            ),
            "failed_ids": failed_ids,
        },
        "checks": checks,
        "evidence": json_safe(evidence),
        "artifacts": {
            "run_root": str(run_root),
            "summary": str(summary_path),
            "review_screenshot": str(screenshot_path),
            "promoted_screenshot": str(promoted_screenshot_path),
            "stderr_log": str(stderr_log),
            "progress_log": str(progress_path),
        },
        "error": error,
    }
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "CANVAS_REVIEW_PROBE_KIND",
    "CANVAS_REVIEW_PROBE_VERSION",
    "run_canvas_review_probe",
]
