from __future__ import annotations

import html
import json
import os
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.composition import (
    CompositionLayout,
    composite_layout_ids,
    composition_layout,
)
from sciplot_core.canvas.persistence import atomic_write_json
from sciplot_core.composition_delivery import export_composition_delivery
from sciplot_core.composition_workspace import (
    composition_variant_authority_status,
    create_composition_workspace,
    verify_composition_sources,
)

COMPOSITION_PROBE_KIND = "sciplot_composition_probe"
COMPOSITION_PROBE_VERSION = 1


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


def _write_report(path: Path, payload: dict[str, Any]) -> Path:
    rows = []
    for check in payload.get("checks") or []:
        color = "#147d45" if check["status"] == "passed" else "#b42318"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(check['id']))}</code></td>"
            f"<td>{html.escape(str(check['label']))}</td>"
            f"<td style='color:{color};font-weight:700'>{check['status']}</td>"
            f"<td><pre>{html.escape(json.dumps(check.get('detail'), ensure_ascii=False, indent=2))}</pre></td>"
            "</tr>"
        )
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>SciPlot Composition Probe</title>
<style>
body{{font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:28px;color:#17212b}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d8dee4;padding:8px;vertical-align:top}}
th{{background:#f6f8fa;text-align:left}}pre{{white-space:pre-wrap;margin:0;font-size:11px;max-width:700px}}
</style></head><body>
<h1>SciPlot Composition Probe</h1>
<p>Status: <strong>{html.escape(str(payload.get("status")))}</strong></p>
<table><thead><tr><th>ID</th><th>Gate</th><th>Status</th><th>Evidence</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></body></html>"""
    path.write_text(body, encoding="utf-8")
    return path


def run_composition_probe(
    documents: list[Path] | tuple[Path, ...],
    *,
    output_root: Path,
) -> dict[str, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6 import QtCore, QtTest, QtWidgets

    from sciplot_gui.composition_compiler import (
        audit_native_composition_document,
    )
    from sciplot_gui.composition_controller import (
        CompositionAuthorityConflict,
        CompositionController,
    )
    from sciplot_gui.composition_window import SciPlotCompositionWindow

    resolved = [path.expanduser().resolve() for path in documents]
    if not resolved:
        raise ValueError("Composition probe requires at least one VSZ document.")
    for document in resolved:
        if not document.is_file() or document.suffix.casefold() != ".vsz":
            raise FileNotFoundError(f"Composition probe VSZ not found: {document}")
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="composition_probe_", dir=output_root)
    ).resolve()
    summary_path = run_root / "composition_probe_summary.json"
    report_path = run_root / "composition_probe_report.html"
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    application = application or QtWidgets.QApplication([])
    window: SciPlotCompositionWindow | None = None
    try:
        layout_evidence: list[dict[str, Any]] = []
        layout_roundtrip = True
        for layout_id in composite_layout_ids():
            layout = composition_layout(layout_id)
            restored = CompositionLayout.from_dict(layout.to_dict())
            total = (
                layout.outer_left_mm
                + sum(layout.panel_widths_mm)
                + sum(layout.gaps_mm)
                + layout.outer_right_mm
            )
            roundtrip = restored.to_dict() == layout.to_dict()
            layout_roundtrip = layout_roundtrip and roundtrip
            layout_evidence.append(
                {
                    "layout_id": layout_id,
                    "geometry_total_mm": total,
                    "slot_count": len(layout.slots),
                    "roundtrip": roundtrip,
                }
            )
        checks.append(
            _check(
                "exact_layout_contracts",
                "All five layouts close exactly to 183 mm and round-trip",
                len(layout_evidence) == 5
                and layout_roundtrip
                and all(
                    abs(item["geometry_total_mm"] - 183.0) <= 1e-9
                    for item in layout_evidence
                ),
                layout_evidence,
            )
        )
        tampered = composition_layout("double_equal_90").to_dict()
        tampered["slots"][0]["width_mm"] = 89.0
        tamper_blocked = False
        try:
            CompositionLayout.from_dict(tampered)
        except ValueError:
            tamper_blocked = True
        checks.append(
            _check(
                "layout_tamper_rejected",
                "Persisted physical geometry cannot drift from the contract",
                tamper_blocked,
            )
        )

        input_root = run_root / "probe_inputs"
        input_root.mkdir(parents=True, exist_ok=True)
        probe_sources: list[Path] = []
        for index in range(3):
            source = resolved[index % len(resolved)]
            destination = input_root / f"source_{index + 1}.vsz"
            shutil.copy2(source, destination)
            probe_sources.append(destination)
        input_hashes = {str(path): file_sha256(path) for path in probe_sources}
        workspace, _project = create_composition_workspace(
            probe_sources,
            root=run_root / "project",
            name="M4 Composition Probe",
            layout_id="triple_equal_60",
        )
        controller = CompositionController(workspace)

        preview_batch = controller.placement_batch("module_a", "panel_b")
        composition_hash_before = file_sha256(workspace.composition_path)
        preview = controller.preview_batch(preview_batch)
        composition_hash_after = file_sha256(workspace.composition_path)
        checks.append(
            _check(
                "typed_zero_write_preview",
                "Composition operation preview is typed and zero-write",
                composition_hash_before == composition_hash_after
                and preview.get("publication_document_changed") is False
                and preview.get("changes", [{}])[0].get("operation_type")
                == "composition_place_module",
                preview,
            )
        )

        compiled_layouts: list[dict[str, Any]] = []
        for layout_id in composite_layout_ids():
            controller.reload()
            if controller.variant.layout.layout_id != layout_id:
                transaction = controller.apply_batch(controller.layout_batch(layout_id))
                compile_result = transaction.compile_result
            else:
                compile_result = controller.ensure_compiled()
            audit = audit_native_composition_document(workspace)
            compiled_layouts.append(
                {
                    "layout_id": layout_id,
                    "document": (
                        compile_result.get("document")
                        if isinstance(compile_result, dict)
                        else None
                    ),
                    "page_size_mm": audit["page_size_mm"],
                    "maximum_geometry_error_mm": audit["maximum_geometry_error_mm"],
                    "native_module_root_types": audit["native_module_root_types"],
                    "panel_labels_aligned": audit["panel_labels_aligned"],
                    "style_alignment": audit["style_alignment"],
                    "raster_panel_composition_detected": audit[
                        "raster_panel_composition_detected"
                    ],
                }
            )
        checks.append(
            _check(
                "all_layouts_native_compile",
                "Every supported layout compiles to exact native Veusz graphs",
                len(compiled_layouts) == 5
                and all(
                    item["maximum_geometry_error_mm"] <= 0.02
                    and item["raster_panel_composition_detected"] is False
                    and item["panel_labels_aligned"] is True
                    and item["style_alignment"]["axes_aligned"] is True
                    and item["style_alignment"]["series_strokes_aligned"] is True
                    for item in compiled_layouts
                ),
                compiled_layouts,
            )
        )

        controller.reload()
        if controller.variant.layout.layout_id != "double_equal_90":
            controller.apply_batch(controller.layout_batch("double_equal_90"))
        document_before_drag = workspace.variant_document_path(
            controller.variant.variant_id
        )
        drag_hash_before = file_sha256(document_before_drag)
        window = SciPlotCompositionWindow(workspace, interactive=False)
        window.show()
        QtTest.QTest.qWait(160)
        module_id = "module_a"
        before_slot = window.controller.variant.placement(module_id).slot_ref
        target_slot = next(
            slot
            for slot in window.controller.variant.layout.slot_ids
            if slot != before_slot
        )
        item = window.board.module_items[module_id]
        start = window.board.mapFromScene(item.sceneBoundingRect().center())
        end = window.board.mapFromScene(window.board.slot_rects[target_slot].center())
        QtTest.QTest.mousePress(
            window.board.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            start,
        )
        QtTest.QTest.mouseMove(window.board.viewport(), end, 120)
        QtTest.QTest.mouseRelease(
            window.board.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            end,
        )
        QtTest.QTest.qWait(900)
        application.processEvents()
        after_slot = window.controller.variant.placement(module_id).slot_ref
        receipt = window.last_transaction.receipt if window.last_transaction else {}
        drag_hash_after = file_sha256(
            workspace.variant_document_path(window.controller.variant.variant_id)
        )
        screenshot = run_root / "composition_board.png"
        window.grab().save(str(screenshot))
        window._undo()
        QtTest.QTest.qWait(450)
        undo_slot = window.controller.variant.placement(module_id).slot_ref
        window._redo()
        QtTest.QTest.qWait(450)
        redo_slot = window.controller.variant.placement(module_id).slot_ref
        checks.append(
            _check(
                "real_drag_typed_recompile",
                "A real mouse drag applies a typed operation and refreshes native preview",
                after_slot == target_slot
                and receipt.get("changes", [{}])[0].get("operation_type")
                == "composition_place_module"
                and drag_hash_after != drag_hash_before
                and window.preview_adapter is not None
                and screenshot.is_file(),
                {
                    "before_slot": before_slot,
                    "target_slot": target_slot,
                    "after_slot": after_slot,
                    "receipt": receipt,
                    "screenshot": str(screenshot),
                },
            )
        )
        checks.append(
            _check(
                "composition_undo_redo",
                "Drag operations are reversible through the same typed gateway",
                undo_slot == before_slot and redo_slot == target_slot,
                {"undo_slot": undo_slot, "redo_slot": redo_slot},
            )
        )
        window.close()
        window = None
        application.processEvents()

        controller = CompositionController(workspace)
        document = workspace.variant_document_path(controller.variant.variant_id)
        with document.open("a", encoding="utf-8") as handle:
            handle.write("\n# SciPlot composition probe manual edit\n")
        edited_hash = file_sha256(document)
        authority = composition_variant_authority_status(
            workspace,
            controller.project,
            controller.variant.variant_id,
        )
        blocked_batch = controller.height_batch(
            controller.variant.layout.canvas_height_mm + 1.0
        )
        model_hash_before_block = file_sha256(workspace.composition_path)
        blocked = False
        try:
            controller.apply_batch(blocked_batch)
        except CompositionAuthorityConflict:
            blocked = True
        model_hash_after_block = file_sha256(workspace.composition_path)
        document_hash_after_block = file_sha256(document)
        checks.append(
            _check(
                "manual_edit_protected",
                "A layout mutation cannot silently overwrite an edited composite",
                blocked
                and authority["manual_edit_detected"] is True
                and model_hash_before_block == model_hash_after_block
                and document_hash_after_block == edited_hash,
                authority,
            )
        )
        regenerated = controller.apply_batch(
            blocked_batch,
            regenerate_edited=True,
        )
        archived_hashes = {
            file_sha256(path)
            for path in workspace.variant_root(controller.variant.variant_id).glob(
                "archive/*.vsz"
            )
        }
        checks.append(
            _check(
                "explicit_archive_regeneration",
                "Explicit regeneration archives manual edits before rebuilding",
                edited_hash in archived_hashes
                and regenerated.compile_result is not None
                and controller.variant.layout.canvas_height_mm == 56.0,
                {
                    "edited_sha256": edited_hash,
                    "archive_hashes": sorted(archived_hashes),
                    "compile": regenerated.compile_result,
                },
            )
        )

        original_variant = controller.variant.variant_id
        original_slot = controller.variant.placement("module_a").slot_ref
        original_document = workspace.variant_document_path(original_variant)
        original_hash = file_sha256(original_document)
        controller.create_variant("Alternative")
        alternative_variant = controller.variant.variant_id
        controller.ensure_compiled()
        alternative_target = next(
            slot
            for slot in controller.variant.layout.slot_ids
            if slot != controller.variant.placement("module_a").slot_ref
        )
        controller.apply_batch(
            controller.placement_batch("module_a", alternative_target)
        )
        alternative_hash = file_sha256(
            workspace.variant_document_path(alternative_variant)
        )
        controller.activate_variant(original_variant)
        checks.append(
            _check(
                "independent_variants",
                "Composition variants compile independently without changing the source variant",
                controller.variant.placement("module_a").slot_ref == original_slot
                and file_sha256(original_document) == original_hash
                and alternative_hash != original_hash,
                {
                    "original_variant": original_variant,
                    "alternative_variant": alternative_variant,
                    "original_sha256": original_hash,
                    "alternative_sha256": alternative_hash,
                },
            )
        )

        delivery = export_composition_delivery(workspace)
        checks.append(
            _check(
                "exact_current_delivery",
                "PDF/TIFF, physical QA, native structure, hashes, and delivery pass",
                delivery.get("ready_to_use") is True
                and delivery.get("delivery_hash_parity") is True
                and delivery.get("claims", {}).get("exact_current_artifact_qa_passed")
                is True
                and delivery.get("claims", {}).get(
                    "broader_journal_compliance_established"
                )
                is False,
                delivery,
            )
        )

        source_verification = verify_composition_sources(
            workspace,
            workspace.load(),
        )
        input_unchanged = all(
            file_sha256(path) == digest
            for path, digest in (
                (Path(path_value), digest_value)
                for path_value, digest_value in input_hashes.items()
            )
        )
        checks.append(
            _check(
                "source_vsz_immutable",
                "Original and snapshotted source VSZ files remain byte-identical",
                input_unchanged
                and all(item["verified"] is True for item in source_verification),
                source_verification,
            )
        )
        evidence = {
            "workspace": str(workspace.root),
            "composition": str(workspace.composition_path),
            "compiled_layouts": compiled_layouts,
            "board_screenshot": str(screenshot),
            "delivery": delivery,
        }
    except Exception as exc:
        checks.append(
            _check(
                "probe_runtime",
                "Composition probe completed without an unhandled exception",
                False,
                {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
        )
    finally:
        if window is not None:
            window.close()
        application.processEvents()
        if owns_application:
            application.quit()

    passed = all(check["status"] == "passed" for check in checks)
    payload = {
        "kind": COMPOSITION_PROBE_KIND,
        "version": COMPOSITION_PROBE_VERSION,
        "status": "passed" if passed else "failed",
        "check_count": len(checks),
        "passed_count": sum(check["status"] == "passed" for check in checks),
        "checks": checks,
        "evidence": evidence,
        "artifacts": {
            "root": str(run_root),
            "summary": str(summary_path),
            "report": str(report_path),
        },
    }
    atomic_write_json(summary_path, payload)
    _write_report(report_path, payload)
    return payload


__all__ = [
    "COMPOSITION_PROBE_KIND",
    "COMPOSITION_PROBE_VERSION",
    "run_composition_probe",
]
