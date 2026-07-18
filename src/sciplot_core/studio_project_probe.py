from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe


STUDIO_PROJECT_PROBE_KIND = "sciplot_studio_project_probe"
STUDIO_PROJECT_PROBE_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check(
    check_id: str,
    description: str,
    passed: bool,
    detail: object,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "description": description,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _wait(application: Any, *, cycles: int = 8) -> None:
    for _ in range(max(int(cycles), 1)):
        application.processEvents()


def _project_document(project_dir: Path) -> Path:
    document = project_dir / "studio" / "document.vsz"
    if not document.is_file():
        raise FileNotFoundError(
            f"SciPlot project has no studio/document.vsz: {project_dir}"
        )
    if not (project_dir / "plot_request.json").is_file():
        raise FileNotFoundError(
            f"SciPlot project has no plot_request.json: {project_dir}"
        )
    return document.resolve()


def _project_manifest_path(project_dir: Path) -> Path:
    candidates = [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"SciPlot project has no intake/project manifest: {project_dir}"
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
    except ValueError:
        return False
    return True


def _source_mutation_target(
    source_path: object,
    *,
    project_dir: Path,
) -> Path | None:
    if not isinstance(source_path, str) or not source_path.strip():
        return None
    source = Path(source_path).expanduser().resolve()
    candidates = [source] if source.is_file() else sorted(source.rglob("*"))
    for candidate in candidates:
        if candidate.is_file() and _is_within(candidate, project_dir):
            return candidate.resolve()
    return None


def _full_readiness_flags(status: dict[str, Any]) -> dict[str, bool]:
    qa = status.get("qa") if isinstance(status.get("qa"), dict) else {}
    provenance = (
        status.get("provenance")
        if isinstance(status.get("provenance"), dict)
        else {}
    )
    readiness = (
        status.get("readiness")
        if isinstance(status.get("readiness"), dict)
        else {}
    )
    qa_current = qa.get("status") == "passed_for_current_document"
    provenance_current = bool(
        provenance.get("current") is True
        or provenance.get("complete") is True
    )
    readiness_current = bool(
        readiness.get("current") is True
        or readiness.get("ready_to_use") is True
        or status.get("ready_to_use") is True
    )
    return {
        "qa_current": qa_current,
        "provenance_current": provenance_current,
        "qa_and_provenance_current": qa_current and provenance_current,
        "readiness_current": readiness_current,
    }


def _rebase_path_value(
    value: object,
    *,
    source_project: Path,
    copied_project: Path,
) -> object:
    if not isinstance(value, str) or not value.strip():
        return value
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return value
    try:
        relative = candidate.resolve().relative_to(source_project)
    except ValueError:
        return value
    return str((copied_project / relative).resolve())


def _rebase_project_paths(
    value: object,
    *,
    source_project: Path,
    copied_project: Path,
) -> object:
    if isinstance(value, dict):
        return {
            key: _rebase_project_paths(
                item,
                source_project=source_project,
                copied_project=copied_project,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rebase_project_paths(
                item,
                source_project=source_project,
                copied_project=copied_project,
            )
            for item in value
        ]
    return _rebase_path_value(
        value,
        source_project=source_project,
        copied_project=copied_project,
    )


def _copy_project_fixture(source_project: Path, run_root: Path) -> Path:
    copied_project = run_root / "project"
    shutil.copytree(
        source_project,
        copied_project,
        ignore=shutil.ignore_patterns(
            "runs",
            "delivery",
            "exports",
            "*.zip",
            ".sciplot_canvas",
        ),
    )
    request_path = copied_project / "plot_request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Copied plot_request.json must contain an object.")
    request = _rebase_project_paths(
        request,
        source_project=source_project,
        copied_project=copied_project,
    )
    request_path.write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    for manifest_path in [
        copied_project / "intake_manifest.json",
        *sorted(copied_project.glob("*.sciplot.json")),
    ]:
        if not manifest_path.is_file():
            continue
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        payload = _rebase_project_paths(
            payload,
            source_project=source_project,
            copied_project=copied_project,
        )
        for key in (
            "last_run",
            "package_contract",
            "delivery_package",
            "layout_quality",
        ):
            payload.pop(key, None)
        studio = (
            payload.get("studio")
            if isinstance(payload.get("studio"), dict)
            else {}
        )
        for key in ("exports", "last_export_run"):
            studio.pop(key, None)
        studio["document"] = str(
            (copied_project / "studio" / "document.vsz").resolve()
        )
        studio["generated_from"] = str(request_path.resolve())
        payload["studio"] = studio
        manifest_path.write_text(
            json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return copied_project.resolve()


def _native_identity(window: Any) -> dict[str, object]:
    return {
        "document": id(window.document),
        "plot": id(window.plot),
        "treeedit": id(window.treeedit),
        "propdock": id(window.propdock),
        "formatdock": id(window.formatdock),
        "datadock": id(window.datadock),
        "undo_action": id(window.vzactions["edit.undo"]),
        "redo_action": id(window.vzactions["edit.redo"]),
        "undo_shortcut": window.vzactions["edit.undo"].shortcut().toString(),
        "redo_shortcut": window.vzactions["edit.redo"].shortcut().toString(),
    }


def _axis_label_setting(document: Any) -> tuple[Any, Any]:
    stack = [document.basewidget]
    while stack:
        widget = stack.pop()
        stack.extend(reversed(list(getattr(widget, "children", ()))))
        if str(getattr(widget, "typename", "")) != "axis":
            continue
        label = document.resolveSettingPath(None, f"{widget.path}/label")
        return widget, label
    raise RuntimeError("The project document has no editable axis.")


def _close_window(window: Any | None) -> None:
    if window is None:
        return
    try:
        assistant = getattr(window, "_sciplot_assistant_bridge", None)
        if assistant is not None:
            assistant.runner.shutdown(wait_ms=3000)
    except Exception:
        pass
    try:
        window.document.setModified(False)
    except Exception:
        pass
    try:
        window.close()
    except Exception:
        pass


class _SavedDocument:
    changeset = 0

    def isModified(self) -> bool:
        return False


class _ActiveAssistantRunner:
    @property
    def active(self) -> bool:
        return True


def _mapping_project_status(
    mapped_document: Path,
    *,
    audit_source: bool = True,
) -> dict[str, Any]:
    from sciplot_gui.studio_project import build_studio_project_status

    document = mapped_document.expanduser().resolve()
    project_dir = document.parent.parent
    return build_studio_project_status(
        document_path=document,
        document=_SavedDocument(),
        project_dir=project_dir,
        request_path=project_dir / "plot_request.json",
        audit_source=audit_source,
    )


def run_studio_project_probe(
    project_dir: Path,
    *,
    output_root: Path,
    mapped_document: Path | None = None,
) -> dict[str, Any]:
    source_project = project_dir.expanduser().resolve()
    source_document = _project_document(source_project)
    source_sha256 = file_sha256(source_document)
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="studio_project_probe_", dir=resolved_output)
    )
    copied_project = _copy_project_fixture(source_project, run_root)
    copied_document = _project_document(copied_project)
    copied_initial_sha256 = file_sha256(copied_document)

    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    error: dict[str, str] | None = None
    project_window: Any | None = None
    standalone_window: Any | None = None

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        from sciplot_core.studio import _create_veusz_window, _ensure_veusz_on_path
        from sciplot_core.studio_assistant_probe import (
            _injected_provider_resolution,
        )
        from sciplot_gui.studio_project import export_result_message

        _ensure_veusz_on_path()
        application = QtWidgets.QApplication.instance()
        if application is None:
            application = QtWidgets.QApplication([])
        application.setApplicationName("SciPlot Studio Project Probe")
        application.setQuitOnLastWindowClosed(False)

        with _injected_provider_resolution(None):
            project_window = _create_veusz_window(copied_document)
        from veusz.document.operations import OperationSettingSet

        project_window.resize(1200, 820)
        project_window.show()
        _wait(application)
        project_bridge = project_window._sciplot_project_bridge
        assistant_bridge = project_window._sciplot_assistant_bridge
        project_action = project_bridge.dock.toggleViewAction()
        assistant_action = assistant_bridge.dock.toggleViewAction()
        sciplot_menu = next(
            (
                action.menu()
                for action in project_window.menuBar().actions()
                if action.menu() is not None
                and action.text().replace("&", "") == "SciPlot"
            ),
            None,
        )
        identity_before = _native_identity(project_window)
        geometry_before = project_window.plot.geometry().getRect()
        default_hidden = bool(
            not project_bridge.dock.isVisible()
            and not assistant_bridge.dock.isVisible()
            and not project_action.isChecked()
            and not assistant_action.isChecked()
        )
        project_action.trigger()
        _wait(application)
        shown = project_bridge.dock.isVisible() and project_action.isChecked()
        identity_shown = _native_identity(project_window)
        project_action.trigger()
        _wait(application)
        hidden_again = (
            not project_bridge.dock.isVisible()
            and not project_action.isChecked()
        )
        identity_after = _native_identity(project_window)
        geometry_after = project_window.plot.geometry().getRect()
        menu_actions = sciplot_menu.actions() if sciplot_menu is not None else []
        checks.append(
            _check(
                "one_veusz_mainwindow_with_opt_in_sciplot_docks",
                "Project and AI are two default-hidden native docks on one Veusz MainWindow",
                project_bridge.window is project_window
                and project_bridge.document is project_window.document
                and project_bridge.plot is project_window.plot
                and assistant_bridge.document is project_window.document
                and default_hidden
                and project_action in menu_actions
                and assistant_action in menu_actions
                and shown
                and hidden_again
                and identity_before == identity_shown == identity_after
                and geometry_before == geometry_after,
                {
                    "default_hidden": default_hidden,
                    "shown": shown,
                    "hidden_again": hidden_again,
                    "project_dock": project_bridge.dock.objectName(),
                    "assistant_dock": assistant_bridge.dock.objectName(),
                    "identity_before": identity_before,
                    "identity_shown": identity_shown,
                    "identity_after": identity_after,
                    "geometry_before": geometry_before,
                    "geometry_after": geometry_after,
                },
            )
        )

        initial_status = project_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )
        checks.append(
            _check(
                "project_source_mapping_status_before_export",
                "The dock reads the project request and current source without inventing a mapping or QA result",
                initial_status["mode"] == "project"
                and initial_status["project"]["request_status"] == "loaded"
                and initial_status["source"]["exists"] is True
                and initial_status["source"]["sha256"]
                and initial_status["mapping"]["status"] == "not_applied"
                and initial_status["qa"]["status"] == "not_run"
                and initial_status["document"]["live_render_sha256"],
                initial_status,
            )
        )

        exporting_gate: dict[str, Any] = {}
        original_project_export = project_bridge._project_export

        def observed_project_export() -> dict[str, Any]:
            exporting_gate.update(
                {
                    "workflow": json_safe(
                        project_bridge.status_snapshot.get("workflow")
                    ),
                    "refresh_enabled": (
                        project_bridge.refresh_button.isEnabled()
                    ),
                    "export_enabled": (
                        project_bridge.export_button.isEnabled()
                    ),
                    "pdf_enabled": (
                        project_bridge.open_pdf_button.isEnabled()
                    ),
                    "delivery_enabled": (
                        project_bridge.show_delivery_button.isEnabled()
                    ),
                    "vsz_enabled": (
                        project_bridge.reveal_vsz_button.isEnabled()
                    ),
                }
            )
            return original_project_export()

        project_bridge._project_export = observed_project_export
        try:
            baseline_export = project_bridge.export_current_document(
                show_dialog=False
            )
        finally:
            project_bridge._project_export = original_project_export
        baseline_light_status = json.loads(
            json.dumps(
                json_safe(project_bridge.status_snapshot),
                ensure_ascii=False,
            )
        )
        checks.append(
            _check(
                "project_exporting_state_gates_all_actions",
                "Export publishes an observable exporting state and disables every mutating or result action",
                exporting_gate.get("workflow", {}).get("state")
                == "exporting"
                and exporting_gate.get("refresh_enabled") is False
                and exporting_gate.get("export_enabled") is False
                and exporting_gate.get("pdf_enabled") is False
                and exporting_gate.get("delivery_enabled") is False
                and exporting_gate.get("vsz_enabled") is False,
                exporting_gate,
            )
        )
        light_results = (
            baseline_light_status.get("results")
            if isinstance(
                baseline_light_status.get("results"),
                dict,
            )
            else {}
        )
        light_pdf = (
            light_results.get("pdf")
            if isinstance(light_results.get("pdf"), dict)
            else {}
        )
        light_delivery = (
            light_results.get("delivery")
            if isinstance(light_results.get("delivery"), dict)
            else {}
        )
        light_vsz = (
            light_results.get("vsz")
            if isinstance(light_results.get("vsz"), dict)
            else {}
        )
        light_evidence = Path(
            str(baseline_light_status["qa"]["evidence"])
        ).expanduser().resolve()
        checks.append(
            _check(
                "light_refresh_separates_ready_result_from_pending_audit",
                "The immediate lightweight post-export refresh keeps the result ready and labels the deep audit pending rather than stale",
                baseline_export.get("ready_to_use") is True
                and baseline_light_status.get("workflow", {}).get("state")
                == "ready"
                and baseline_light_status.get("workflow", {}).get(
                    "audit_state"
                )
                == "pending"
                and baseline_light_status.get("provenance", {}).get(
                    "status"
                )
                == "audit_pending_for_current_project"
                and baseline_light_status.get("qa", {}).get("status")
                == "passed_for_current_document"
                and baseline_light_status.get("provenance", {}).get(
                    "project_delivery_current"
                )
                is True
                and light_pdf.get("available") is True
                and light_delivery.get("available") is True
                and light_vsz.get("available") is True
                and _is_within(
                    Path(str(light_pdf["path"])),
                    light_evidence.parent,
                )
                and _is_within(
                    Path(str(light_delivery["path"])),
                    light_evidence.parent,
                ),
                baseline_light_status,
            )
        )
        opened_results: list[str] = []
        original_open_local_path = project_bridge._open_local_path
        project_bridge._open_local_path = (
            lambda path: opened_results.append(
                str(path.expanduser().resolve())
            )
            is None
        )
        try:
            project_bridge.open_pdf_button.click()
            project_bridge.show_delivery_button.click()
            project_bridge.reveal_vsz_button.click()
            _wait(application)
        finally:
            project_bridge._open_local_path = original_open_local_path
        expected_opened_results = [
            str(Path(str(light_pdf["path"])).expanduser().resolve()),
            str(Path(str(light_delivery["path"])).expanduser().resolve()),
            str(
                Path(str(light_vsz["reveal_path"]))
                .expanduser()
                .resolve()
            ),
        ]
        checks.append(
            _check(
                "current_result_actions_use_validated_local_targets",
                "PDF, delivery, and VSZ reveal actions use only current validated paths without launching a real external application",
                opened_results == expected_opened_results,
                {
                    "opened": opened_results,
                    "expected": expected_opened_results,
                },
            )
        )
        baseline_status = project_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )
        checks.append(
            _check(
                "project_exact_current_export_and_lineage",
                "The project export is ready only after current-hash QA, lineage, and delivery pass",
                baseline_export.get("status") == "passed"
                and baseline_export.get("ready_to_use") is True
                and baseline_status["qa"]["status"]
                == "passed_for_current_document"
                and baseline_status["source"]["audit_status"]
                == "matches_last_run_lineage"
                and baseline_status["provenance"]["complete"] is True,
                {
                    "export": baseline_export,
                    "status": baseline_status,
                },
            )
        )

        axis, label_setting = _axis_label_setting(project_window.document)
        original_label = str(label_setting.get())
        manual_label = f"{original_label} · project probe"
        saved_hash_before_edit = file_sha256(copied_document)
        project_window.document.applyOperation(
            OperationSettingSet(
                f"{axis.path}/label",
                label_setting.normalize(manual_label),
            )
        )
        _wait(application)
        modified_status = project_bridge.refresh()
        checks.append(
            _check(
                "unsaved_native_edit_invalidates_qa",
                "A native Veusz edit changes the live revision, keeps the saved hash, and makes prior QA stale",
                project_window.document.isModified()
                and modified_status["document"]["modified"] is True
                and modified_status["document"]["saved_sha256"]
                == saved_hash_before_edit
                and modified_status["document"]["live_render_sha256"] is None
                and modified_status["qa"]["status"]
                == "stale_for_current_document"
                and modified_status.get("workflow", {}).get("state")
                == "editing"
                and not project_bridge.open_pdf_button.isEnabled()
                and not project_bridge.show_delivery_button.isEnabled(),
                modified_status,
            )
        )

        project_window.document.save(str(copied_document))
        _wait(application)
        saved_status = project_bridge.refresh(
            capture_render=True,
            audit_source=False,
        )
        saved_hash_after_edit = file_sha256(copied_document)
        checks.append(
            _check(
                "saved_edit_hash_is_live_not_manifest_cached",
                "Saving updates the live VSZ hash but does not revive QA for an older export",
                not project_window.document.isModified()
                and saved_hash_after_edit != saved_hash_before_edit
                and saved_status["document"]["saved_sha256"]
                == saved_hash_after_edit
                and saved_status["qa"]["status"]
                == "stale_for_current_document"
                and saved_status.get("workflow", {}).get("state")
                == "editing"
                and not project_bridge.open_pdf_button.isEnabled()
                and not project_bridge.show_delivery_button.isEnabled(),
                saved_status,
            )
        )

        updated_export = project_bridge.export_current_document(
            show_dialog=False
        )
        updated_status = project_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )
        checks.append(
            _check(
                "updated_project_export_restores_current_qa",
                "Re-exporting the saved edit binds QA and delivery to the new exact-current VSZ hash",
                updated_export.get("ready_to_use") is True
                and updated_status["qa"]["status"]
                == "passed_for_current_document"
                and updated_status["qa"]["evidence_document_sha256"]
                == updated_status["document"]["saved_sha256"],
                {
                    "export": updated_export,
                    "status": updated_status,
                },
            )
        )

        updated_run = (
            updated_export.get("studio_run")
            if isinstance(updated_export.get("studio_run"), dict)
            else {}
        )
        updated_manifest = _read_json_object(
            Path(str(updated_run["manifest"])).expanduser().resolve()
        )
        delivery = (
            updated_manifest.get("delivery_package")
            if isinstance(
                updated_manifest.get("delivery_package"),
                dict,
            )
            else {}
        )
        delivery_figures = (
            delivery.get("figures")
            if isinstance(delivery.get("figures"), list)
            else []
        )
        delivery_pdf = next(
            (
                Path(str(record["path"])).expanduser().resolve()
                for record in delivery_figures
                if isinstance(record, dict)
                and record.get("export_format") == "pdf"
                and isinstance(record.get("path"), str)
            ),
            None,
        )
        tampered_delivery_status: dict[str, Any] = {}
        if delivery_pdf is not None and delivery_pdf.is_file():
            delivery_pdf_bytes = delivery_pdf.read_bytes()
            with delivery_pdf.open("ab") as handle:
                handle.write(b"\nSciPlot delivery tamper probe\n")
            try:
                tampered_delivery_status = project_bridge.refresh(
                    capture_render=True,
                    audit_source=True,
                )
            finally:
                delivery_pdf.write_bytes(delivery_pdf_bytes)
        checks.append(
            _check(
                "delivery_tamper_invalidates_full_project_evidence",
                "Changing a delivery copy cannot invalidate artifact QA silently or leave full project evidence current",
                delivery_pdf is not None
                and tampered_delivery_status.get("qa", {}).get("status")
                == "passed_for_current_document"
                and tampered_delivery_status.get("provenance", {}).get(
                    "project_delivery_current"
                )
                is False
                and tampered_delivery_status.get("provenance", {}).get(
                    "complete"
                )
                is False
                and tampered_delivery_status.get("workflow", {}).get(
                    "state"
                )
                == "needs_fix"
                and project_bridge.open_pdf_button.isEnabled()
                and not project_bridge.show_delivery_button.isEnabled(),
                {
                    "delivery_pdf": (
                        str(delivery_pdf)
                        if delivery_pdf is not None
                        else None
                    ),
                    "status": tampered_delivery_status,
                },
            )
        )
        project_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )

        runs_before_active_export = {
            path.resolve()
            for path in (copied_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        original_runner = assistant_bridge.runner
        assistant_bridge.runner = _ActiveAssistantRunner()
        try:
            active_assistant_export = (
                project_bridge.export_current_document(
                    show_dialog=False,
                )
            )
        finally:
            assistant_bridge.runner = original_runner
        runs_after_active_export = {
            path.resolve()
            for path in (copied_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        checks.append(
            _check(
                "active_assistant_blocks_bridge_export",
                "The Project bridge rejects export while an Assistant request is active and publishes no run",
                active_assistant_export.get("status")
                in {"failed", "rejected"}
                and active_assistant_export.get("ready_to_use") is not True
                and not isinstance(
                    active_assistant_export.get("studio_run"),
                    dict,
                )
                and runs_after_active_export
                == runs_before_active_export,
                {
                    "export": active_assistant_export,
                    "runs_before": sorted(
                        str(path)
                        for path in runs_before_active_export
                    ),
                    "runs_after": sorted(
                        str(path)
                        for path in runs_after_active_export
                    ),
                },
            )
        )

        project_manifest_path = _project_manifest_path(copied_project)
        project_manifest_before = project_manifest_path.read_bytes()
        current_run = (
            updated_export.get("studio_run")
            if isinstance(updated_export.get("studio_run"), dict)
            else {}
        )
        internal_run_manifest = Path(
            str(current_run["manifest"])
        ).expanduser().resolve()
        external_run_root = run_root / "external_registered_run"
        external_run_root.mkdir(parents=True, exist_ok=True)
        external_run_manifest = external_run_root / "manifest.json"
        shutil.copy2(internal_run_manifest, external_run_manifest)
        registered_manifest = json.loads(
            project_manifest_before.decode("utf-8")
        )
        studio_registration = (
            registered_manifest.get("studio")
            if isinstance(registered_manifest.get("studio"), dict)
            else {}
        )
        last_export_registration = (
            studio_registration.get("last_export_run")
            if isinstance(
                studio_registration.get("last_export_run"),
                dict,
            )
            else {}
        )
        studio_registration["last_export_run"] = {
            **last_export_registration,
            "output": "../external_registered_run",
            "manifest": str(external_run_manifest),
        }
        registered_manifest["studio"] = studio_registration
        last_run_registration = (
            registered_manifest.get("last_run")
            if isinstance(registered_manifest.get("last_run"), dict)
            else {}
        )
        registered_manifest["last_run"] = {
            **last_run_registration,
            "output": "../external_registered_run",
        }
        project_manifest_path.write_text(
            json.dumps(
                json_safe(registered_manifest),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            escaped_run_status = project_bridge.refresh(
                capture_render=True,
                audit_source=True,
            )
        finally:
            project_manifest_path.write_bytes(project_manifest_before)
        escaped_evidence_value = escaped_run_status["qa"].get(
            "evidence"
        )
        escaped_evidence_path = (
            Path(str(escaped_evidence_value)).expanduser().resolve()
            if escaped_evidence_value
            else None
        )
        checks.append(
            _check(
                "external_registered_run_is_not_adopted",
                "Absolute and traversal-style run registrations outside the project cannot become current evidence",
                escaped_evidence_path is not None
                and _is_within(
                    escaped_evidence_path,
                    copied_project / "runs",
                )
                and not _is_within(
                    escaped_evidence_path,
                    external_run_root,
                ),
                {
                    "project_manifest": str(project_manifest_path),
                    "external_manifest": str(
                        external_run_manifest
                    ),
                    "selected_evidence": (
                        str(escaped_evidence_path)
                        if escaped_evidence_path is not None
                        else None
                    ),
                    "status": escaped_run_status,
                },
            )
        )

        request_before = project_bridge.request_path.read_bytes()
        request_payload = json.loads(request_before.decode("utf-8"))
        request_payload["_studio_project_probe_mutation"] = (
            "request_hash_must_invalidate_full_readiness"
        )
        project_bridge.request_path.write_text(
            json.dumps(
                json_safe(request_payload),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            changed_request_status = project_bridge.refresh(
                capture_render=True,
                audit_source=True,
            )
        finally:
            project_bridge.request_path.write_bytes(request_before)
        changed_request_flags = _full_readiness_flags(
            changed_request_status
        )
        checks.append(
            _check(
                "changed_request_invalidates_full_readiness",
                "Changing plot_request.json prevents the prior run from remaining fully current",
                not changed_request_flags[
                    "qa_and_provenance_current"
                ]
                and not changed_request_flags["readiness_current"],
                {
                    "flags": changed_request_flags,
                    "status": changed_request_status,
                },
            )
        )

        restored_request_status = project_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )
        source_mutation_target = _source_mutation_target(
            restored_request_status["source"].get("path"),
            project_dir=copied_project,
        )
        changed_source_status: dict[str, Any] = {}
        if source_mutation_target is not None:
            source_size_before = source_mutation_target.stat().st_size
            with source_mutation_target.open("ab") as handle:
                handle.write(
                    b"\n# SciPlot Studio source readiness probe\n"
                )
            try:
                changed_source_status = project_bridge.refresh(
                    capture_render=True,
                    audit_source=True,
                )
            finally:
                with source_mutation_target.open("r+b") as handle:
                    handle.truncate(source_size_before)
        changed_source_flags = _full_readiness_flags(
            changed_source_status
        )
        checks.append(
            _check(
                "changed_source_invalidates_full_readiness",
                "Changing the bound project source prevents the prior run from remaining fully current",
                source_mutation_target is not None
                and changed_source_status["source"][
                    "audit_status"
                ]
                != "matches_last_run_lineage"
                and not changed_source_flags[
                    "qa_and_provenance_current"
                ]
                and not changed_source_flags["readiness_current"],
                {
                    "mutation_target": (
                        str(source_mutation_target)
                        if source_mutation_target is not None
                        else None
                    ),
                    "flags": changed_source_flags,
                    "status": changed_source_status,
                },
            )
        )
        restored_project_status = project_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )

        failure_payload = {
            "scope": "project_delivery",
            "status": "failed",
            "state": "needs_rule_repair",
            "ready_to_use": False,
            "studio_run": {
                "state": "needs_rule_repair",
                "qa": {"status": "failed"},
                "output": "/probe/failed",
            },
        }
        level, _title, failure_message = export_result_message(failure_payload)
        checks.append(
            _check(
                "failed_export_never_reports_success",
                "A failed project run maps to a warning and never to a success message",
                level == "warning"
                and "did not mark this export ready" in failure_message
                and "passed" not in failure_message.casefold(),
                {
                    "level": level,
                    "message": failure_message,
                },
            )
        )

        standalone_root = run_root / "standalone"
        standalone_root.mkdir(parents=True, exist_ok=True)
        standalone_document = standalone_root / "document.vsz"
        shutil.copy2(copied_document, standalone_document)
        _close_window(project_window)
        project_window = None
        with _injected_provider_resolution(None):
            standalone_window = _create_veusz_window(standalone_document)
        standalone_window.resize(1200, 820)
        standalone_window.show()
        _wait(application)
        standalone_bridge = standalone_window._sciplot_project_bridge
        standalone_assistant = standalone_window._sciplot_assistant_bridge
        standalone_export = standalone_bridge.export_current_document(
            show_dialog=False
        )
        standalone_status = standalone_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )
        receipt = (
            standalone_export.get("standalone_export")
            if isinstance(
                standalone_export.get("standalone_export"),
                dict,
            )
            else {}
        )
        checks.append(
            _check(
                "standalone_vsz_exact_current_receipt",
                "Standalone VSZ export is enabled but does not claim project provenance",
                standalone_bridge.mode == "standalone_vsz"
                and not standalone_bridge.dock.isVisible()
                and not standalone_assistant.dock.isVisible()
                and standalone_export.get("ready_to_use") is True
                and standalone_export.get("scope")
                == "standalone_exact_current_export"
                and receipt.get("provenance_complete") is False
                and receipt.get("project_delivery_complete") is False
                and standalone_status["source"]["status"]
                == "not_established"
                and standalone_status["mapping"]["status"] == "unavailable"
                and standalone_status["qa"]["status"]
                == "passed_for_current_document",
                {
                    "export": standalone_export,
                    "status": standalone_status,
                },
            )
        )

        standalone_exports = (
            standalone_export.get("exports")
            if isinstance(standalone_export.get("exports"), list)
            else []
        )
        standalone_tiff = next(
            (
                Path(str(item["path"])).expanduser().resolve()
                for item in standalone_exports
                if isinstance(item, dict)
                and item.get("format") == "tiff_300"
                and isinstance(item.get("path"), str)
            ),
            None,
        )
        tampered_standalone_status: dict[str, Any] = {}
        deleted_standalone_status: dict[str, Any] = {}
        if standalone_tiff is not None and standalone_tiff.is_file():
            standalone_tiff_size = standalone_tiff.stat().st_size
            with standalone_tiff.open("ab") as handle:
                handle.write(b"\nSciPlot standalone TIFF tamper probe\n")
            tampered_standalone_status = standalone_bridge.refresh(
                capture_render=True,
                audit_source=True,
            )
            with standalone_tiff.open("r+b") as handle:
                handle.truncate(standalone_tiff_size)
            standalone_tiff.unlink()
            deleted_standalone_status = standalone_bridge.refresh(
                capture_render=True,
                audit_source=True,
            )
        checks.append(
            _check(
                "standalone_artifact_change_invalidates_current_qa",
                "Tampering with or deleting the receipt-bound standalone TIFF makes prior QA non-current",
                standalone_tiff is not None
                and tampered_standalone_status.get("qa", {}).get(
                    "status"
                )
                != "passed_for_current_document"
                and tampered_standalone_status.get("qa", {}).get(
                    "current_document"
                )
                is not True
                and deleted_standalone_status.get("qa", {}).get(
                    "status"
                )
                != "passed_for_current_document"
                and deleted_standalone_status.get("qa", {}).get(
                    "current_document"
                )
                is not True
                and tampered_standalone_status.get("workflow", {}).get(
                    "state"
                )
                == "needs_fix"
                and deleted_standalone_status.get("workflow", {}).get(
                    "state"
                )
                == "needs_fix",
                {
                    "tiff": (
                        str(standalone_tiff)
                        if standalone_tiff is not None
                        else None
                    ),
                    "tampered_status": tampered_standalone_status,
                    "deleted_status": deleted_standalone_status,
                },
            )
        )

        mapping_status: dict[str, Any] | None = None
        mapping_light_status: dict[str, Any] | None = None
        if mapped_document is not None:
            mapping_light_status = _mapping_project_status(
                mapped_document,
                audit_source=False,
            )
            mapping_status = _mapping_project_status(mapped_document)
            checks.append(
                _check(
                    "mapped_light_refresh_is_ready_with_pending_audit",
                    "A mapped current result remains ready while lightweight mapping and source audit are explicitly pending",
                    mapping_light_status["mapping"]["status"]
                    == "audit_pending"
                    and mapping_light_status["source"]["audit_status"]
                    == "not_computed"
                    and mapping_light_status["qa"]["status"]
                    == "passed_for_current_document"
                    and mapping_light_status.get("workflow", {}).get(
                        "state"
                    )
                    == "ready"
                    and mapping_light_status.get("workflow", {}).get(
                        "audit_state"
                    )
                    == "pending"
                    and mapping_light_status["provenance"]["status"]
                    == "audit_pending_for_current_project",
                    mapping_light_status,
                )
            )
            checks.append(
                _check(
                    "confirmed_mapping_status_is_reverified",
                    "The dock status revalidates the mapping execution and rendered-source coverage",
                    mapping_status["mapping"]["status"] == "verified"
                    and mapping_status["mapping"]["coverage_status"] == "passed"
                    and mapping_status["source"]["exists"] is True
                    and mapping_status["source"]["audit_status"]
                    == "matches_last_run_lineage"
                    and mapping_status["qa"]["status"]
                    == "passed_for_current_document",
                    mapping_status,
                )
            )

        checks.append(
            _check(
                "source_project_immutable",
                "The probe edits and exports only isolated project and standalone copies",
                file_sha256(source_document) == source_sha256
                and copied_initial_sha256 == source_sha256
                and source_document != copied_document,
                {
                    "source_document": str(source_document),
                    "source_sha256": source_sha256,
                    "copied_document": str(copied_document),
                },
            )
        )
        evidence = {
            "initial_status": initial_status,
            "baseline_status": baseline_status,
            "modified_status": modified_status,
            "saved_status": saved_status,
            "updated_status": updated_status,
            "active_assistant_export": active_assistant_export,
            "escaped_run_status": escaped_run_status,
            "changed_request_status": changed_request_status,
            "changed_source_status": changed_source_status,
            "restored_project_status": restored_project_status,
            "standalone_status": standalone_status,
            "tampered_standalone_status": (
                tampered_standalone_status
            ),
            "deleted_standalone_status": (
                deleted_standalone_status
            ),
            "mapping_status": mapping_status,
            "mapping_light_status": mapping_light_status,
            "baseline_light_status": baseline_light_status,
            "exporting_gate": exporting_gate,
            "opened_results": opened_results,
            "baseline_export": baseline_export,
            "updated_export": updated_export,
            "standalone_export": standalone_export,
            "saved_hash_before_edit": saved_hash_before_edit,
            "saved_hash_after_edit": saved_hash_after_edit,
        }
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "studio_project_probe_exception",
                "The Studio project integration lifecycle completes without an exception",
                False,
                error,
            )
        )
    finally:
        _close_window(project_window)
        _close_window(standalone_window)

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    summary_path = run_root / "studio_project_probe.json"
    payload = {
        "kind": STUDIO_PROJECT_PROBE_KIND,
        "version": STUDIO_PROJECT_PROBE_VERSION,
        "generated_at": _now(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(
                item["status"] == "passed" for item in checks
            ),
            "failed_ids": [
                item["id"]
                for item in checks
                if item["status"] != "passed"
            ],
        },
        "evidence": evidence,
        "artifacts": {
            "run_root": str(run_root),
            "source_project": str(source_project),
            "copied_project": str(copied_project),
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "The GUI lifecycle uses isolated copies and synthetic smoke inputs; "
            "it proves host behavior, not real-data evidence.",
            "A current QA result applies only to the saved VSZ hash recorded by "
            "that export run.",
            "Standalone receipts intentionally do not establish source, "
            "mapping, transform, or portable-project provenance.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise the SciPlot Project dock and exact-current exports inside "
            "one native Veusz MainWindow."
        )
    )
    parser.add_argument(
        "--project",
        type=Path,
        required=True,
        help="SciPlot project containing plot_request.json and studio/document.vsz.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for the isolated probe.",
    )
    parser.add_argument(
        "--mapped-document",
        type=Path,
        help="Optional mapped project studio/document.vsz to revalidate.",
    )
    return parser


def _maybe_reexec_with_qt_runtime(argv: list[str]) -> None:
    if (
        sys.platform != "darwin"
        or os.environ.get("SCIPLOT_STUDIO_PROJECT_PROBE_QT_RUNTIME") == "1"
    ):
        return
    from sciplot_core.studio import _qt_framework_paths

    framework_paths = _qt_framework_paths()
    if not framework_paths:
        return
    env = os.environ.copy()
    joined = ":".join(str(path) for path in framework_paths)
    for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
        current = env.get(key)
        env[key] = f"{joined}:{current}" if current else joined
    env["SCIPLOT_STUDIO_PROJECT_PROBE_QT_RUNTIME"] = "1"
    os.execvpe(
        sys.executable,
        [
            sys.executable,
            "-m",
            "sciplot_core.studio_project_probe",
            *argv,
        ],
        env,
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        _maybe_reexec_with_qt_runtime(sys.argv[1:])
    args = _build_parser().parse_args(argv)
    payload = run_studio_project_probe(
        args.project,
        output_root=args.out,
        mapped_document=args.mapped_document,
    )
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "STUDIO_PROJECT_PROBE_KIND",
    "STUDIO_PROJECT_PROBE_VERSION",
    "run_studio_project_probe",
]
