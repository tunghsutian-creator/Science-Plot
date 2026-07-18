from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
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
        status.get("provenance") if isinstance(status.get("provenance"), dict) else {}
    )
    readiness = (
        status.get("readiness") if isinstance(status.get("readiness"), dict) else {}
    )
    qa_current = qa.get("status") == "passed_for_current_document"
    provenance_current = bool(
        provenance.get("current") is True or provenance.get("complete") is True
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
            payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        )
        for key in ("exports", "last_export_run"):
            studio.pop(key, None)
        studio["document"] = str((copied_project / "studio" / "document.vsz").resolve())
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
    figure_window: Any | None = None
    context_window: Any | None = None

    try:
        from sciplot_core.intake import _project_package_info
        from sciplot_core.launchers import inspect_project_launcher_contract
        from sciplot_core.studio import (
            _standalone_export_artifact_root,
            _studio_figure_set_export_scope,
            prepare_studio_document,
            publish_studio_export_run,
            run_studio_command,
        )

        legacy_launcher = copied_project / "Open_SciPlot_Project.command"
        legacy_launcher.write_text(
            "#!/bin/zsh\nsciplot workbench .\n",
            encoding="utf-8",
        )
        manifest_paths = [
            copied_project / "intake_manifest.json",
            *sorted(copied_project.glob("*.sciplot.json")),
        ]
        for manifest_path in manifest_paths:
            if not manifest_path.is_file():
                continue
            manifest = _read_json_object(manifest_path)
            manifest["launcher"] = "/foreign/stale/Open_SciPlot_Project.command"
            manifest["launcher_contract"] = {
                "kind": "sciplot_project_launcher_contract",
                "status": "blocked",
                "ready": False,
            }
            studio = (
                dict(manifest.get("studio"))
                if isinstance(manifest.get("studio"), dict)
                else {}
            )
            studio.update(
                {
                    "document": "/foreign/stale/document.vsz",
                    "launcher": "/foreign/stale/Open_SciPlot_Project.command",
                    "veusz_launcher": "/foreign/stale/Open_in_Veusz.command",
                    "export_edited_launcher": (
                        "/foreign/stale/Export_Edited_Veusz.command"
                    ),
                }
            )
            manifest["studio"] = studio
            manifest_path.write_text(
                json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        prepare_launcher_repair = prepare_studio_document(copied_project)
        launcher_contract = inspect_project_launcher_contract(copied_project)
        repaired_manifests = [
            _read_json_object(path) for path in manifest_paths if path.is_file()
        ]
        expected_primary_launcher = str(
            (copied_project / "Open_in_SciPlot_Studio.command").resolve()
        )
        expected_veusz_launcher = str(
            (copied_project / "Open_in_Veusz.command").resolve()
        )
        expected_export_launcher = str(
            (copied_project / "Export_Edited_Veusz.command").resolve()
        )
        checks.append(
            _check(
                "prepare_repairs_legacy_and_stale_launcher_registration",
                "The production prepare path removes the legacy Web launcher and rebinds both manifests without a separate pre-convergence call",
                prepare_launcher_repair.get("preserved_existing_document") is True
                and not legacy_launcher.exists()
                and launcher_contract.get("ready") is True
                and bool(repaired_manifests)
                and all(
                    manifest.get("launcher") == expected_primary_launcher
                    and manifest.get("launcher_contract", {}).get("ready") is True
                    and manifest.get("studio", {}).get("document")
                    == str(copied_document)
                    and manifest.get("studio", {}).get("launcher")
                    == expected_primary_launcher
                    and manifest.get("studio", {}).get("veusz_launcher")
                    == expected_veusz_launcher
                    and manifest.get("studio", {}).get("export_edited_launcher")
                    == expected_export_launcher
                    for manifest in repaired_manifests
                ),
                {
                    "prepare": prepare_launcher_repair,
                    "contract": launcher_contract,
                    "manifests": repaired_manifests,
                },
            )
        )
        launcher_manifest_path = _project_manifest_path(copied_project)
        launcher_manifest = _read_json_object(launcher_manifest_path)
        launcher_primary = (
            launcher_contract.get("primary")
            if isinstance(launcher_contract.get("primary"), dict)
            else {}
        )
        launcher_supporting = (
            launcher_contract.get("supporting")
            if isinstance(launcher_contract.get("supporting"), dict)
            else {}
        )
        launcher_veusz = (
            launcher_supporting.get("veusz")
            if isinstance(launcher_supporting.get("veusz"), dict)
            else {}
        )
        launcher_export = (
            launcher_supporting.get("export_exact_current")
            if isinstance(
                launcher_supporting.get("export_exact_current"),
                dict,
            )
            else {}
        )
        checks.append(
            _check(
                "veusz_first_project_launcher_contract",
                "A normal project exposes one portable Studio daily entry, keeps direct Veusz and exact-current export tools, and contains no legacy Web-workbench launcher",
                launcher_contract.get("ready") is True
                and launcher_contract.get("mode") == "veusz_first"
                and launcher_primary.get("name") == "Open_in_SciPlot_Studio.command"
                and launcher_primary.get("safe") is True
                and launcher_primary.get("opens_web_workbench") is False
                and launcher_veusz.get("safe") is True
                and launcher_export.get("safe") is True
                and launcher_contract.get(
                    "legacy_web_workbench_launcher",
                    {},
                ).get("present")
                is False
                and launcher_manifest.get("launcher") == launcher_primary.get("path")
                and launcher_manifest.get(
                    "launcher_contract",
                    {},
                ).get("ready")
                is True,
                {
                    "contract": launcher_contract,
                    "manifest": str(launcher_manifest_path),
                    "registered_launcher": launcher_manifest.get("launcher"),
                },
            )
        )
        primary_launcher_path = copied_project / "Open_in_SciPlot_Studio.command"
        canonical_primary_launcher = primary_launcher_path.read_text(
            encoding="utf-8"
        )
        primary_launcher_path.write_text(
            "\n".join(
                [
                    "#!/bin/zsh",
                    "set -euo pipefail",
                    '# PROJECT_DIR="${0:A:h}"',
                    "# find_sciplot()",
                    '# SCIPLOT_CMD="$(find_sciplot)"',
                    '# exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}"',
                    'touch "${PROJECT_DIR}/unexpected-launcher-side-effect"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        primary_launcher_path.chmod(0o755)
        forged_comment_contract = inspect_project_launcher_contract(copied_project)
        forged_primary = (
            forged_comment_contract.get("primary")
            if isinstance(forged_comment_contract.get("primary"), dict)
            else {}
        )
        checks.append(
            _check(
                "launcher_comments_cannot_forge_safe_contract",
                "Required strings in comments plus an arbitrary side-effect command cannot forge a safe launcher",
                forged_comment_contract.get("ready") is False
                and forged_primary.get("safe") is False
                and forged_primary.get("canonical_structure") is False
                and forged_primary.get("uses_portable_sciplot_resolution") is False
                and forged_primary.get("required_command_present") is False,
                forged_comment_contract,
            )
        )

        primary_launcher_path.write_text(
            canonical_primary_launcher,
            encoding="utf-8",
        )
        primary_launcher_path.chmod(0o755)
        probe_zip = copied_project.parent / f"{copied_project.name}.zip"
        probe_zip.write_bytes(b"launcher contract probe")
        canonical_package = _project_package_info(
            copied_project,
            project_slug=copied_project.name,
        )
        primary_launcher_path.write_text(
            canonical_primary_launcher
            + '# comment cannot authorize an appended command\n'
            + 'print -u2 -- "unexpected launcher side effect"\n',
            encoding="utf-8",
        )
        primary_launcher_path.chmod(0o755)
        forged_manifest = _read_json_object(launcher_manifest_path)
        forged_manifest["launcher_contract"] = {
            "kind": "sciplot_project_launcher_contract",
            "version": 3,
            "status": "ready",
            "ready": True,
        }
        launcher_manifest_path.write_text(
            json.dumps(json_safe(forged_manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        forged_package = _project_package_info(
            copied_project,
            project_slug=copied_project.name,
        )
        checks.append(
            _check(
                "launcher_side_effect_blocks_intake_completeness",
                "A persisted ready claim cannot make an intake package complete when a generated launcher has an extra command",
                canonical_package.get("complete") is True
                and forged_package.get("complete") is False
                and forged_package.get("launcher_contract", {}).get("ready") is False
                and forged_package.get("launcher_contract", {})
                .get("primary", {})
                .get("canonical_structure")
                is False,
                {
                    "canonical": canonical_package,
                    "forged": forged_package,
                },
            )
        )
        primary_launcher_path.write_text(
            canonical_primary_launcher,
            encoding="utf-8",
        )
        primary_launcher_path.chmod(0o755)
        launcher_contract = inspect_project_launcher_contract(copied_project)
        _restored_manifest = _read_json_object(launcher_manifest_path)
        _restored_manifest["launcher_contract"] = json_safe(launcher_contract)
        _restored_manifest["launcher"] = str(primary_launcher_path.resolve())
        launcher_manifest_path.write_text(
            json.dumps(
                json_safe(_restored_manifest),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtCore, QtWidgets

        from sciplot_core import studio as studio_module
        from sciplot_core.studio import _create_veusz_window, _ensure_veusz_on_path
        from sciplot_core.studio_assistant_probe import (
            DeterministicStudioAssistantProvider,
            _injected_provider_resolution,
            _wait_until,
        )
        from sciplot_gui import studio_project as studio_project_module
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
            not project_bridge.dock.isVisible() and not project_action.isChecked()
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

        figure_entries = project_bridge._figure_set_entries()
        request_path = copied_project / "plot_request.json"
        canonical_request_bytes = request_path.read_bytes()
        canonical_request = _read_json_object(request_path)
        registry_path = copied_project / "studio" / "figure_set.json"
        registry_bytes = registry_path.read_bytes() if registry_path.is_file() else None
        frequency_scope_before = _studio_figure_set_export_scope(
            copied_project,
            request=canonical_request,
        )
        frequency_blocker_before = project_bridge._figure_set_export_blocker()
        ordinary_multifigure_results: list[dict[str, Any]] = []
        explicit_registry_blocker: str | None = None
        explicit_registry_scope_status: str | None = None
        multifigure_plans = {
            "tensile_curve": [
                {
                    "id": "stress_vs_strain",
                    "x_metric": "strain",
                    "y_metric": "stress",
                },
                {
                    "id": "tensile_strength_by_sample",
                    "x_metric": "sample",
                    "y_metric": "strength_MPa",
                },
                {
                    "id": "tensile_modulus_by_sample",
                    "x_metric": "sample",
                    "y_metric": "modulus_MPa",
                },
            ],
            "rheology_temperature_sweep": [
                {
                    "id": "storage_modulus_vs_temperature",
                    "x_metric": "temperature",
                    "y_metric": "storage_modulus",
                },
                {
                    "id": "tan_delta_vs_temperature",
                    "x_metric": "temperature",
                    "y_metric": "tan_delta",
                },
            ],
        }
        try:
            registry_path.unlink(missing_ok=True)
            for rule_id, figure_queue in multifigure_plans.items():
                request = json.loads(json.dumps(canonical_request))
                request["rule_id"] = rule_id
                study_model = (
                    dict(request.get("study_model"))
                    if isinstance(request.get("study_model"), dict)
                    else {}
                )
                study_model["figure_queue"] = figure_queue
                request["study_model"] = study_model
                request_path.write_text(
                    json.dumps(json_safe(request), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                core_scope = _studio_figure_set_export_scope(
                    copied_project,
                    request=request,
                )
                resolved_scope, resolved_scope_status = (
                    studio_project_module._resolve_figure_set_export_scope(
                        project_dir=copied_project,
                        request=request,
                        latest_run={},
                    )
                )
                blocker = project_bridge._figure_set_export_blocker()
                project_bridge._update_controls(project_bridge.status_snapshot)
                ordinary_multifigure_results.append(
                    {
                        "rule_id": rule_id,
                        "figure_count": len(figure_queue),
                        "core_scope": core_scope,
                        "resolved_scope": resolved_scope,
                        "resolved_scope_status": resolved_scope_status,
                        "export_blocker": blocker,
                        "export_enabled": project_bridge.export_button.isEnabled(),
                        "menu_export_enabled": bool(
                            project_bridge.export_action is not None
                            and project_bridge.export_action.isEnabled()
                        ),
                    }
                )

            registry_path.write_text(
                "{ damaged explicit figure-set registry",
                encoding="utf-8",
            )
            explicit_registry_blocker = project_bridge._figure_set_export_blocker()
            _, explicit_registry_scope_status = (
                studio_project_module._resolve_figure_set_export_scope(
                    project_dir=copied_project,
                    request=request,
                    latest_run={},
                )
            )
        finally:
            request_path.write_bytes(canonical_request_bytes)
            if registry_bytes is None:
                registry_path.unlink(missing_ok=True)
            else:
                registry_path.write_bytes(registry_bytes)
            project_bridge._populate_figure_list()
            project_bridge._update_controls(project_bridge.status_snapshot)

        frequency_scope_after = _studio_figure_set_export_scope(
            copied_project,
            request=canonical_request,
        )
        frequency_blocker_after = project_bridge._figure_set_export_blocker()
        if registry_bytes is None:
            frequency_scope_contract_ok = bool(
                frequency_scope_before is None
                and frequency_scope_after is None
                and frequency_blocker_before is None
                and frequency_blocker_after is None
            )
        else:
            frequency_scope_contract_ok = bool(
                isinstance(frequency_scope_before, dict)
                and frequency_scope_before.get("scope")
                == "primary_figure_project_delivery"
                and frequency_scope_before.get(
                    "full_figure_set_delivery_complete"
                )
                is False
                and bool(frequency_scope_before.get("blocked_figure_ids"))
                and frequency_scope_after == frequency_scope_before
                and frequency_blocker_before is None
                and frequency_blocker_after is None
            )
        checks.append(
            _check(
                "ordinary_multifigure_plans_do_not_imply_figure_set_scope",
                "Ordinary tensile and temperature-sweep queues stay normal project exports; only an explicit registry or the bounded frequency figure-set contract activates figure-set handling",
                len(ordinary_multifigure_results) == 2
                and all(
                    item["figure_count"] > 1
                    and item["core_scope"] is None
                    and item["resolved_scope"] is None
                    and item["resolved_scope_status"] == "not_applicable"
                    and item["export_blocker"] is None
                    and item["export_enabled"] is True
                    and item["menu_export_enabled"] is True
                    for item in ordinary_multifigure_results
                )
                and explicit_registry_blocker is not None
                and explicit_registry_scope_status == "unknown_or_incomplete"
                and frequency_scope_contract_ok
                and project_bridge.export_button.isEnabled() is True,
                {
                    "ordinary_plans": ordinary_multifigure_results,
                    "explicit_registry_blocker": explicit_registry_blocker,
                    "explicit_registry_scope_status": (
                        explicit_registry_scope_status
                    ),
                    "frequency_scope_before": frequency_scope_before,
                    "frequency_scope_after": frequency_scope_after,
                    "frequency_blocker_before": frequency_blocker_before,
                    "frequency_blocker_after": frequency_blocker_after,
                    "frequency_scope_applicable": registry_bytes is not None,
                },
            )
        )
        if registry_bytes is not None:
            swapped_primary_scope: dict[str, Any] | None = None
            swapped_primary_resolved: dict[str, Any] | None = None
            swapped_primary_status: str | None = None
            swapped_primary_blocker: str | None = None
            swapped_primary_id: str | None = None
            swapped_primary_export_enabled: bool | None = None
            swapped_primary_menu_enabled: bool | None = None
            try:
                tampered_registry = json.loads(registry_bytes.decode("utf-8"))
                original_primary_id = str(
                    tampered_registry.get("primary_figure_id") or ""
                )
                swapped_primary_id = next(
                    (
                        str(item.get("figure_id"))
                        for item in tampered_registry.get("figures", [])
                        if isinstance(item, dict)
                        and item.get("status") == "ready"
                        and str(item.get("figure_id") or "")
                        != original_primary_id
                    ),
                    None,
                )
                if swapped_primary_id is not None:
                    tampered_registry["primary_figure_id"] = swapped_primary_id
                    export_contract = (
                        dict(tampered_registry.get("export_contract"))
                        if isinstance(
                            tampered_registry.get("export_contract"), dict
                        )
                        else {}
                    )
                    ready_ids = [
                        str(item.get("figure_id"))
                        for item in tampered_registry.get("figures", [])
                        if isinstance(item, dict)
                        and item.get("status") == "ready"
                    ]
                    export_contract["primary_figure_id"] = swapped_primary_id
                    export_contract["supported_figure_ids"] = [
                        swapped_primary_id
                    ]
                    export_contract["blocked_figure_ids"] = [
                        figure_id
                        for figure_id in ready_ids
                        if figure_id != swapped_primary_id
                    ]
                    tampered_registry["export_contract"] = export_contract
                    registry_path.write_text(
                        json.dumps(
                            json_safe(tampered_registry),
                            indent=2,
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    swapped_primary_scope = _studio_figure_set_export_scope(
                        copied_project,
                        request=canonical_request,
                    )
                    (
                        swapped_primary_resolved,
                        swapped_primary_status,
                    ) = studio_project_module._resolve_figure_set_export_scope(
                        project_dir=copied_project,
                        request=canonical_request,
                        latest_run={},
                    )
                    swapped_primary_blocker = (
                        project_bridge._figure_set_export_blocker()
                    )
                    project_bridge._update_controls(
                        project_bridge.status_snapshot
                    )
                    swapped_primary_export_enabled = (
                        project_bridge.export_button.isEnabled()
                    )
                    swapped_primary_menu_enabled = bool(
                        project_bridge.export_action is not None
                        and project_bridge.export_action.isEnabled()
                    )
            finally:
                registry_path.write_bytes(registry_bytes)
                project_bridge._populate_figure_list()
                project_bridge._update_controls(project_bridge.status_snapshot)
            checks.append(
                _check(
                    "swapped_frequency_primary_fails_closed",
                    "A frequency registry cannot relabel the canonical storage-modulus VSZ as a ready secondary metric or leave project export enabled",
                    swapped_primary_id is not None
                    and swapped_primary_scope is None
                    and swapped_primary_resolved is None
                    and swapped_primary_status == "unknown_or_incomplete"
                    and swapped_primary_blocker is not None
                    and swapped_primary_export_enabled is False
                    and swapped_primary_menu_enabled is False
                    and project_bridge.export_button.isEnabled() is True,
                    {
                        "swapped_primary_id": swapped_primary_id,
                        "core_scope": swapped_primary_scope,
                        "resolved_scope": swapped_primary_resolved,
                        "resolved_scope_status": swapped_primary_status,
                        "export_blocker": swapped_primary_blocker,
                        "export_enabled": swapped_primary_export_enabled,
                        "menu_export_enabled": swapped_primary_menu_enabled,
                        "restored_export_enabled": (
                            project_bridge.export_button.isEnabled()
                        ),
                    },
                )
            )
        if figure_entries:
            target_entry = next(
                (
                    item
                    for item in figure_entries
                    if Path(str(item.get("document"))).resolve() != copied_document
                    and item.get("status") == "ready"
                ),
                None,
            )
            opened = False
            if target_entry is not None:
                target_document = Path(str(target_entry["document"])).resolve()
                for index in range(project_bridge.figure_list.count()):
                    item = project_bridge.figure_list.item(index)
                    if (
                        Path(str(item.data(QtCore.Qt.ItemDataRole.UserRole))).resolve()
                        == target_document
                    ):
                        project_bridge.figure_list.setCurrentItem(item)
                        opened = project_bridge.open_selected_figure()
                        break
                _wait(application)
                from veusz.windows.mainwindow import MainWindow

                figure_window = next(
                    (
                        window
                        for window in MainWindow.windows
                        if Path(str(getattr(window, "filename", ""))).resolve()
                        == target_document
                    ),
                    None,
                )
            secondary_bridge = (
                getattr(figure_window, "_sciplot_project_bridge", None)
                if figure_window is not None
                else None
            )
            secondary_export_blocker = (
                secondary_bridge._figure_set_export_blocker()
                if secondary_bridge is not None
                else None
            )
            secondary_export: dict[str, Any] = {}
            secondary_project_export_called = False
            secondary_manifest_unchanged = False
            secondary_runs_unchanged = False
            secondary_status: dict[str, Any] = {}
            secondary_stale_status: dict[str, Any] = {}
            secondary_pdf_enabled = False
            secondary_delivery_enabled = False
            registry_missing_scope: str | None = None
            registry_damaged_scope: str | None = None
            core_project_receipt_error: str | None = None
            cli_secondary_exports: list[dict[str, Any]] = []
            cli_secondary_receipts_isolated = False
            cli_secondary_manifest_unchanged = False
            cli_secondary_runs_unchanged = False
            if secondary_bridge is not None:
                manifest_snapshots = {
                    path.resolve(): path.read_bytes()
                    for path in [
                        copied_project / "intake_manifest.json",
                        *sorted(copied_project.glob("*.sciplot.json")),
                    ]
                    if path.is_file()
                }
                runs_before_secondary = {
                    path.resolve()
                    for path in (copied_project / "runs").glob("studio_*")
                    if path.is_dir()
                }
                original_secondary_project_export = secondary_bridge._project_export

                def forbidden_secondary_project_export() -> dict[str, Any]:
                    nonlocal secondary_project_export_called
                    secondary_project_export_called = True
                    raise AssertionError(
                        "Secondary VSZ reached the project receipt path."
                    )

                secondary_bridge._project_export = forbidden_secondary_project_export
                try:
                    secondary_export = secondary_bridge.export_current_document(
                        show_dialog=False
                    )
                finally:
                    secondary_bridge._project_export = original_secondary_project_export
                secondary_status = secondary_bridge.refresh(
                    capture_render=True,
                    audit_source=True,
                )
                secondary_pdf_enabled = secondary_bridge.open_pdf_button.isEnabled()
                secondary_delivery_enabled = (
                    secondary_bridge.show_delivery_button.isEnabled()
                )
                secondary_bridge.document.setModified(True)
                secondary_stale_status = secondary_bridge.refresh(
                    capture_render=False,
                    audit_source=False,
                )
                secondary_bridge.document.setModified(False)
                secondary_manifest_unchanged = all(
                    path.read_bytes() == content
                    for path, content in manifest_snapshots.items()
                )
                runs_after_secondary = {
                    path.resolve()
                    for path in (copied_project / "runs").glob("studio_*")
                    if path.is_dir()
                }
                secondary_runs_unchanged = runs_after_secondary == runs_before_secondary
                registry_path = copied_project / "studio" / "figure_set.json"
                registry_bytes = (
                    registry_path.read_bytes() if registry_path.is_file() else None
                )
                try:
                    if registry_path.exists():
                        registry_path.unlink()
                    registry_missing_scope = secondary_bridge._figure_set_export_scope()
                    registry_path.write_text(
                        "{ damaged figure-set registry",
                        encoding="utf-8",
                    )
                    registry_damaged_scope = secondary_bridge._figure_set_export_scope()
                finally:
                    if registry_bytes is None:
                        registry_path.unlink(missing_ok=True)
                    else:
                        registry_path.write_bytes(registry_bytes)
                cli_entries = [
                    item
                    for item in figure_entries
                    if item.get("status") == "ready"
                    and Path(str(item.get("document") or "")).resolve()
                    != copied_document
                ][:2]
                if len(cli_entries) == 2:
                    prior_runtime = os.environ.get("SCIPLOT_STUDIO_QT_RUNTIME")
                    os.environ["SCIPLOT_STUDIO_QT_RUNTIME"] = "1"
                    first_receipt_path: Path | None = None
                    first_receipt_bytes: bytes | None = None
                    first_qa_path: Path | None = None
                    first_qa_bytes: bytes | None = None
                    try:
                        for entry in cli_entries:
                            cli_document = Path(str(entry["document"])).resolve()
                            expected_root = _standalone_export_artifact_root(
                                cli_document
                            )
                            stdout = io.StringIO()
                            with redirect_stdout(stdout):
                                exit_code = run_studio_command(
                                    target=cli_document,
                                    export="pdf,tiff_300",
                                    json_output=True,
                                    original_argv=[
                                        "studio",
                                        str(cli_document),
                                        "--export",
                                        "pdf,tiff_300",
                                        "--json",
                                    ],
                                )
                            cli_payload = json.loads(stdout.getvalue())
                            receipt = (
                                cli_payload.get("standalone_export")
                                if isinstance(
                                    cli_payload.get("standalone_export"),
                                    dict,
                                )
                                else {}
                            )
                            receipt_path = Path(
                                str(receipt.get("receipt_path") or "")
                            ).resolve()
                            qa_path = Path(
                                str(receipt.get("artifact_qa_path") or "")
                            ).resolve()
                            cli_secondary_exports.append(
                                {
                                    "document": str(cli_document),
                                    "expected_root": str(expected_root),
                                    "exit_code": exit_code,
                                    "payload": cli_payload,
                                    "receipt": receipt,
                                    "receipt_path": str(receipt_path),
                                    "qa_path": str(qa_path),
                                }
                            )
                            if first_receipt_path is None:
                                first_receipt_path = receipt_path
                                first_receipt_bytes = receipt_path.read_bytes()
                                first_qa_path = qa_path
                                first_qa_bytes = qa_path.read_bytes()
                    finally:
                        if prior_runtime is None:
                            os.environ.pop("SCIPLOT_STUDIO_QT_RUNTIME", None)
                        else:
                            os.environ["SCIPLOT_STUDIO_QT_RUNTIME"] = prior_runtime
                    roots = {
                        str(item["expected_root"]) for item in cli_secondary_exports
                    }
                    cli_secondary_receipts_isolated = bool(
                        len(cli_secondary_exports) == 2
                        and len(roots) == 2
                        and all(
                            item["exit_code"] == 0
                            and item["receipt"].get("export_ready") is True
                            and Path(item["receipt_path"])
                            == Path(item["expected_root"])
                            / "standalone_export_receipt.json"
                            and Path(item["qa_path"])
                            == Path(item["expected_root"]) / "qa_report.json"
                            and Path(str(item["receipt"].get("document") or ""))
                            == Path(item["document"])
                            for item in cli_secondary_exports
                        )
                        and first_receipt_path is not None
                        and first_receipt_path.read_bytes() == first_receipt_bytes
                        and first_qa_path is not None
                        and first_qa_path.read_bytes() == first_qa_bytes
                    )
                    cli_secondary_manifest_unchanged = all(
                        path.read_bytes() == content
                        for path, content in manifest_snapshots.items()
                    )
                    cli_secondary_runs_unchanged = {
                        path.resolve()
                        for path in (copied_project / "runs").glob("studio_*")
                        if path.is_dir()
                    } == runs_before_secondary
                try:
                    publish_studio_export_run(
                        project_dir=copied_project,
                        request_path=copied_project / "plot_request.json",
                        document_path=target_document,
                        exports=[],
                        export_document_sha256=file_sha256(target_document),
                    )
                except RuntimeError as exc:
                    core_project_receipt_error = str(exc)
            checks.append(
                _check(
                    "project_figure_list_opens_integrated_independent_vsz",
                    "The Project dock opens registered single-page figures and exports a secondary only through its own standalone exact-current receipt",
                    len(figure_entries) >= 2
                    and target_entry is not None
                    and opened
                    and figure_window is not None
                    and getattr(figure_window, "_sciplot_project_bridge", None)
                    is not None
                    and secondary_export_blocker is None
                    and secondary_bridge.export_button.isEnabled() is True
                    and secondary_export.get("scope")
                    == "standalone_exact_current_export"
                    and secondary_export.get("ready_to_use") is True
                    and not secondary_project_export_called
                    and secondary_manifest_unchanged
                    and secondary_runs_unchanged
                    and cli_secondary_receipts_isolated
                    and cli_secondary_manifest_unchanged
                    and cli_secondary_runs_unchanged
                    and registry_missing_scope == "standalone"
                    and registry_damaged_scope == "standalone"
                    and core_project_receipt_error is not None
                    and "canonical project/studio/document.vsz"
                    in core_project_receipt_error
                    and "SciPlot Studio" in figure_window.windowTitle(),
                    {
                        "figure_count": len(figure_entries),
                        "target": target_entry,
                        "opened": opened,
                        "secondary_export_blocker": secondary_export_blocker,
                        "secondary_export_enabled": (
                            secondary_bridge.export_button.isEnabled()
                            if secondary_bridge is not None
                            else None
                        ),
                        "secondary_export": secondary_export,
                        "secondary_status": secondary_status,
                        "secondary_stale_status": secondary_stale_status,
                        "secondary_project_export_called": (
                            secondary_project_export_called
                        ),
                        "secondary_manifest_unchanged": (secondary_manifest_unchanged),
                        "secondary_runs_unchanged": secondary_runs_unchanged,
                        "cli_secondary_exports": cli_secondary_exports,
                        "cli_secondary_receipts_isolated": (
                            cli_secondary_receipts_isolated
                        ),
                        "cli_secondary_manifest_unchanged": (
                            cli_secondary_manifest_unchanged
                        ),
                        "cli_secondary_runs_unchanged": (cli_secondary_runs_unchanged),
                        "registry_missing_scope": registry_missing_scope,
                        "registry_damaged_scope": registry_damaged_scope,
                        "core_project_receipt_error": (core_project_receipt_error),
                        "window_title": (
                            figure_window.windowTitle()
                            if figure_window is not None
                            else None
                        ),
                    },
                )
            )
            expected_secondary_receipt = (
                target_document.parent
                / "exports"
                / target_document.stem
                / "standalone_export_receipt.json"
            )
            checks.append(
                _check(
                    "project_secondary_receipt_drives_its_own_status",
                    "A project secondary shows its own current PDF/QA receipt without claiming or enabling the primary project delivery",
                    secondary_status.get("document_scope")
                    == "project_secondary_standalone_receipt"
                    and secondary_status.get("project", {}).get("path")
                    == str(copied_project)
                    and secondary_status.get("qa", {}).get("status")
                    == "passed_for_current_document"
                    and secondary_status.get("qa", {}).get("artifact_qa_current")
                    is True
                    and Path(
                        str(secondary_status.get("qa", {}).get("evidence") or "")
                    ).resolve()
                    == expected_secondary_receipt.resolve()
                    and secondary_status.get("workflow", {}).get("state") == "ready"
                    and secondary_status.get("provenance", {}).get(
                        "full_project_evidence_current"
                    )
                    is False
                    and secondary_status.get("provenance", {}).get(
                        "project_delivery_current"
                    )
                    is False
                    and secondary_status.get("results", {})
                    .get("pdf", {})
                    .get("available")
                    is True
                    and secondary_status.get("results", {})
                    .get("delivery", {})
                    .get("available")
                    is False
                    and secondary_pdf_enabled
                    and not secondary_delivery_enabled
                    and secondary_stale_status.get("workflow", {}).get("state")
                    == "editing"
                    and secondary_stale_status.get("qa", {}).get("artifact_qa_current")
                    is False,
                    {
                        "receipt": str(expected_secondary_receipt),
                        "current_status": secondary_status,
                        "stale_status": secondary_stale_status,
                        "pdf_enabled": secondary_pdf_enabled,
                        "delivery_enabled": secondary_delivery_enabled,
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

        foreign_request = run_root / "foreign_plot_request.json"
        shutil.copy2(copied_project / "plot_request.json", foreign_request)
        runs_before_foreign_request = {
            path.resolve()
            for path in (copied_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        foreign_request_error: str | None = None
        try:
            publish_studio_export_run(
                project_dir=copied_project,
                request_path=foreign_request,
                document_path=copied_document,
                exports=[],
                export_document_sha256=file_sha256(copied_document),
            )
        except RuntimeError as exc:
            foreign_request_error = str(exc)
        runs_after_foreign_request = {
            path.resolve()
            for path in (copied_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        checks.append(
            _check(
                "project_receipt_rejects_foreign_request_context",
                "The core project publisher accepts only project/plot_request.json and creates no run for a foreign request",
                foreign_request_error is not None
                and "canonical project/plot_request.json" in foreign_request_error
                and runs_after_foreign_request == runs_before_foreign_request,
                {
                    "foreign_request": str(foreign_request),
                    "error": foreign_request_error,
                    "runs_before": sorted(
                        str(path) for path in runs_before_foreign_request
                    ),
                    "runs_after": sorted(
                        str(path) for path in runs_after_foreign_request
                    ),
                },
            )
        )

        exporting_gate: dict[str, Any] = {}
        reentrant_export: dict[str, Any] = {}
        project_export_call_count = 0
        original_project_export = project_bridge._project_export

        def observed_project_export() -> dict[str, Any]:
            nonlocal project_export_call_count
            project_export_call_count += 1
            exporting_gate.update(
                {
                    "workflow": json_safe(
                        project_bridge.status_snapshot.get("workflow")
                    ),
                    "refresh_enabled": (project_bridge.refresh_button.isEnabled()),
                    "export_enabled": (project_bridge.export_button.isEnabled()),
                    "pdf_enabled": (project_bridge.open_pdf_button.isEnabled()),
                    "delivery_enabled": (
                        project_bridge.show_delivery_button.isEnabled()
                    ),
                    "vsz_enabled": (project_bridge.reveal_vsz_button.isEnabled()),
                    "figure_list_enabled": (
                        project_bridge.figure_list.isEnabled()
                    ),
                    "open_figure_enabled": (
                        project_bridge.open_figure_button.isEnabled()
                    ),
                    "menu_export_enabled": bool(
                        project_bridge.export_action is not None
                        and project_bridge.export_action.isEnabled()
                    ),
                }
            )
            reentrant_export.update(
                project_bridge.export_current_document(show_dialog=False)
            )
            return original_project_export()

        project_bridge._project_export = observed_project_export
        try:
            baseline_export = project_bridge.export_current_document(show_dialog=False)
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
                exporting_gate.get("workflow", {}).get("state") == "exporting"
                and exporting_gate.get("refresh_enabled") is False
                and exporting_gate.get("export_enabled") is False
                and exporting_gate.get("pdf_enabled") is False
                and exporting_gate.get("delivery_enabled") is False
                and exporting_gate.get("vsz_enabled") is False
                and exporting_gate.get("figure_list_enabled") is False
                and exporting_gate.get("open_figure_enabled") is False
                and exporting_gate.get("menu_export_enabled") is False
                and reentrant_export.get("state") == "export_in_progress"
                and reentrant_export.get("ready_to_use") is False
                and project_export_call_count == 1,
                {
                    **exporting_gate,
                    "reentrant_export": reentrant_export,
                    "project_export_call_count": project_export_call_count,
                },
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
        light_evidence = (
            Path(str(baseline_light_status["qa"]["evidence"])).expanduser().resolve()
        )
        checks.append(
            _check(
                "light_refresh_separates_ready_result_from_pending_audit",
                "The immediate lightweight post-export refresh keeps the result ready and labels the deep audit pending rather than stale",
                baseline_export.get("ready_to_use") is True
                and baseline_light_status.get("workflow", {}).get("state") == "ready"
                and baseline_light_status.get("workflow", {}).get("audit_state")
                == "pending"
                and baseline_light_status.get("provenance", {}).get("status")
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
        project_bridge._open_local_path = lambda path: (
            opened_results.append(str(path.expanduser().resolve())) is None
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
            str(Path(str(light_vsz["reveal_path"])).expanduser().resolve()),
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
        if figure_entries:
            baseline_scope_current = bool(
                baseline_status["provenance"]["status"]
                == "current_primary_figure_evidence"
                and baseline_status["provenance"]["complete"] is False
                and baseline_status["provenance"][
                    "primary_figure_evidence_current"
                ]
                is True
                and baseline_status["provenance"][
                    "full_project_evidence_current"
                ]
                is False
                and baseline_status["workflow"]["audit_state"]
                == "current_primary_figure"
            )
        else:
            baseline_scope_current = bool(
                baseline_status["provenance"]["status"]
                == "current_full_project_evidence"
                and baseline_status["provenance"]["complete"] is True
                and baseline_status["provenance"][
                    "primary_figure_evidence_current"
                ]
                is False
                and baseline_status["provenance"][
                    "full_project_evidence_current"
                ]
                is True
                and baseline_status["workflow"]["audit_state"] == "current"
            )
        checks.append(
            _check(
                "project_exact_current_export_and_lineage",
                "The project becomes usable after current-hash QA, lineage, and the applicable single- or multi-figure delivery scope pass",
                baseline_export.get("status") == "passed"
                and baseline_export.get("ready_to_use") is True
                and baseline_status["qa"]["status"] == "passed_for_current_document"
                and baseline_status["source"]["audit_status"]
                == "matches_last_run_lineage"
                and baseline_scope_current
                and baseline_status["workflow"]["result_ready"] is True,
                {
                    "export": baseline_export,
                    "status": baseline_status,
                    "figure_set_applicable": bool(figure_entries),
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
                and modified_status["qa"]["status"] == "stale_for_current_document"
                and modified_status.get("workflow", {}).get("state") == "editing"
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
                and saved_status["document"]["saved_sha256"] == saved_hash_after_edit
                and saved_status["qa"]["status"] == "stale_for_current_document"
                and saved_status.get("workflow", {}).get("state") == "editing"
                and not project_bridge.open_pdf_button.isEnabled()
                and not project_bridge.show_delivery_button.isEnabled(),
                saved_status,
            )
        )

        updated_export = project_bridge.export_current_document(show_dialog=False)
        updated_status = project_bridge.refresh(
            capture_render=True,
            audit_source=True,
        )
        checks.append(
            _check(
                "updated_project_export_restores_current_qa",
                "Re-exporting the saved edit binds QA and delivery to the new exact-current VSZ hash",
                updated_export.get("ready_to_use") is True
                and updated_status["qa"]["status"] == "passed_for_current_document"
                and updated_status["qa"]["evidence_document_sha256"]
                == updated_status["document"]["saved_sha256"]
                and Path(str(updated_status["qa"]["evidence"])).resolve()
                == Path(
                    str(updated_export.get("studio_run", {}).get("manifest") or "")
                ).resolve(),
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
        updated_manifest_path = (
            Path(str(updated_run["manifest"])).expanduser().resolve()
        )
        updated_manifest = _read_json_object(updated_manifest_path)
        delivery = (
            updated_manifest.get("delivery_package")
            if isinstance(
                updated_manifest.get("delivery_package"),
                dict,
            )
            else {}
        )
        if figure_entries:
            figure_registry = _read_json_object(
                copied_project / "studio" / "figure_set.json"
            )
            expected_primary_figure_id = str(
                figure_registry.get("primary_figure_id") or ""
            )
            expected_blocked_figure_ids = {
                str(item.get("figure_id") or "")
                for item in figure_registry.get("figures", [])
                if isinstance(item, dict)
                and item.get("status") == "ready"
                and str(item.get("figure_id") or "") != expected_primary_figure_id
            }
            persisted_scope = (
                updated_manifest.get("figure_set_export_scope")
                if isinstance(
                    updated_manifest.get("figure_set_export_scope"),
                    dict,
                )
                else {}
            )
            request_snapshot = _read_json_object(
                updated_manifest_path.parent / "request_snapshot.json"
            )
            canonical_request_payload = _read_json_object(
                copied_project / "plot_request.json"
            )
            scope_manifest_bytes = updated_manifest_path.read_bytes()
            original_scope_helper = (
                studio_project_module._studio_figure_set_export_scope
            )
            missing_scope_status: dict[str, Any] = {}
            malformed_scope_status: dict[str, Any] = {}
            unknown_scope_status: dict[str, Any] = {}
            try:
                missing_scope_manifest = _read_json_object(updated_manifest_path)
                missing_scope_manifest.pop("figure_set_export_scope", None)
                updated_manifest_path.write_text(
                    json.dumps(
                        json_safe(missing_scope_manifest),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                missing_scope_status = project_bridge.refresh(
                    capture_render=True,
                    audit_source=True,
                )

                malformed_scope_manifest = _read_json_object(updated_manifest_path)
                malformed_scope_manifest["figure_set_export_scope"] = {
                    "scope": "project_delivery",
                    "full_figure_set_delivery_complete": False,
                }
                updated_manifest_path.write_text(
                    json.dumps(
                        json_safe(malformed_scope_manifest),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                malformed_scope_status = project_bridge.refresh(
                    capture_render=True,
                    audit_source=True,
                )

                studio_project_module._studio_figure_set_export_scope = (
                    lambda _project_dir, *, request: None
                )
                unknown_scope_status = project_bridge.refresh(
                    capture_render=True,
                    audit_source=True,
                )
            finally:
                studio_project_module._studio_figure_set_export_scope = (
                    original_scope_helper
                )
                updated_manifest_path.write_bytes(scope_manifest_bytes)
            project_bridge.refresh(capture_render=True, audit_source=True)
            checks.append(
                _check(
                    "missing_or_malformed_figure_scope_recomputes_or_fails_closed",
                    "Missing or malformed run scope is safely recomputed from the current project, while unavailable recomputation cannot claim a full project",
                    missing_scope_status.get("provenance", {}).get(
                        "figure_set_export_scope_status"
                    )
                    == "recomputed_current_project"
                    and missing_scope_status.get("provenance", {}).get(
                        "primary_figure_evidence_current"
                    )
                    is True
                    and missing_scope_status.get("provenance", {}).get(
                        "full_project_evidence_current"
                    )
                    is False
                    and malformed_scope_status.get("provenance", {}).get(
                        "figure_set_export_scope_status"
                    )
                    == "recomputed_current_project"
                    and malformed_scope_status.get("provenance", {}).get(
                        "primary_figure_evidence_current"
                    )
                    is True
                    and malformed_scope_status.get("provenance", {}).get(
                        "full_project_evidence_current"
                    )
                    is False
                    and unknown_scope_status.get("provenance", {}).get("status")
                    == "unknown_or_incomplete_figure_set_scope"
                    and unknown_scope_status.get("provenance", {}).get(
                        "delivery_scope_known"
                    )
                    is False
                    and unknown_scope_status.get("provenance", {}).get(
                        "primary_figure_evidence_current"
                    )
                    is False
                    and unknown_scope_status.get("provenance", {}).get(
                        "full_project_evidence_current"
                    )
                    is False
                    and unknown_scope_status.get("provenance", {}).get("complete")
                    is False
                    and unknown_scope_status.get("workflow", {}).get("result_ready")
                    is False
                    and unknown_scope_status.get("workflow", {}).get("audit_state")
                    == "blocked"
                    and unknown_scope_status.get("results", {})
                    .get("delivery", {})
                    .get("available")
                    is False,
                    {
                        "missing": missing_scope_status,
                        "malformed": malformed_scope_status,
                        "unknown": unknown_scope_status,
                    },
                )
            )
            missing_registry_scope: dict[str, Any] = {}
            missing_registry_figure_id = next(
                iter(sorted(expected_blocked_figure_ids)),
                None,
            )
            if missing_registry_figure_id is not None:
                registry_path = copied_project / "studio" / "figure_set.json"
                registry_bytes = registry_path.read_bytes()
                missing_document = (
                    copied_project
                    / "studio"
                    / "figures"
                    / f"{missing_registry_figure_id}.vsz"
                )
                parked_document = missing_document.with_suffix(
                    ".vsz.scope_probe_missing"
                )
                try:
                    registry_path.unlink()
                    os.replace(missing_document, parked_document)
                    missing_registry_scope = (
                        _studio_figure_set_export_scope(
                            copied_project,
                            request=canonical_request_payload,
                        )
                        or {}
                    )
                finally:
                    if parked_document.is_file():
                        os.replace(parked_document, missing_document)
                    registry_path.write_bytes(registry_bytes)
            analysis_report_text = (
                updated_manifest_path.parent / "analysis_report.md"
            ).read_text(encoding="utf-8")
            review_html_text = (updated_manifest_path.parent / "review.html").read_text(
                encoding="utf-8"
            )
            registered_scope_manifests = [
                _read_json_object(path)
                for path in [
                    copied_project / "intake_manifest.json",
                    *sorted(copied_project.glob("*.sciplot.json")),
                ]
                if path.is_file()
            ]
            delivery_project_documents = (
                delivery.get("project_documents")
                if isinstance(delivery.get("project_documents"), list)
                else []
            )
            checks.append(
                _check(
                    "figure_set_primary_delivery_scope_is_persisted",
                    "A rheology project run, review, analysis, delivery, and registered last-run state all say that only the primary figure is included",
                    persisted_scope.get("status") == "primary_exact_current_only"
                    and updated_export.get("scope")
                    == "primary_figure_project_delivery"
                    and updated_run.get("scope")
                    == "primary_figure_project_delivery"
                    and updated_manifest.get("scope")
                    == "primary_figure_project_delivery"
                    and persisted_scope.get("scope")
                    == "primary_figure_project_delivery"
                    and persisted_scope.get("primary_figure_id")
                    == expected_primary_figure_id
                    and persisted_scope.get("supported_figure_ids")
                    == [expected_primary_figure_id]
                    and set(persisted_scope.get("blocked_figure_ids") or [])
                    == expected_blocked_figure_ids
                    and bool(str(persisted_scope.get("blocker") or "").strip())
                    and persisted_scope.get("secondary_receipt_scope")
                    == "standalone_exact_current_export"
                    and persisted_scope.get("full_figure_set_delivery_complete")
                    is False
                    and missing_registry_scope.get("planned_figure_ids")
                    == [
                        str(item.get("id"))
                        for item in canonical_request_payload.get(
                            "study_model", {}
                        ).get("figure_queue", [])
                        if isinstance(item, dict) and item.get("id")
                    ]
                    and missing_registry_figure_id
                    in missing_registry_scope.get("unavailable_figure_ids", [])
                    and missing_registry_figure_id
                    not in missing_registry_scope.get("available_figure_ids", [])
                    and request_snapshot == canonical_request_payload
                    and "figure_set_export_scope" not in request_snapshot
                    and updated_manifest.get("request") == canonical_request_payload
                    and "figure_set_export_scope"
                    not in updated_manifest.get("request", {})
                    and updated_manifest.get("result", {}).get(
                        "figure_set_export_scope"
                    )
                    == persisted_scope
                    and updated_manifest.get("studio", {}).get(
                        "figure_set_export_scope"
                    )
                    == persisted_scope
                    and updated_manifest.get("package_contract", {}).get(
                        "full_figure_set_complete"
                    )
                    is False
                    and delivery.get("scope") == "primary_figure_project_delivery"
                    and delivery.get("complete") is True
                    and delivery.get("full_figure_set_complete") is False
                    and delivery.get("figure_set_export_scope") == persisted_scope
                    and len(delivery_project_documents) == 1
                    and Path(
                        str(delivery_project_documents[0].get("source") or "")
                    ).resolve()
                    == copied_document
                    and "Figure-set delivery scope" in analysis_report_text
                    and "Figure-set delivery scope" in review_html_text
                    and expected_primary_figure_id in analysis_report_text
                    and all(
                        figure_id in analysis_report_text
                        and figure_id in review_html_text
                        for figure_id in expected_blocked_figure_ids
                    )
                    and updated_run.get("figure_set_export_scope") == persisted_scope
                    and bool(registered_scope_manifests)
                    and all(
                        manifest.get("figure_set_export_scope") == persisted_scope
                        and manifest.get("last_run", {}).get("figure_set_export_scope")
                        == persisted_scope
                        and manifest.get("studio", {})
                        .get("last_export_run", {})
                        .get("figure_set_export_scope")
                        == persisted_scope
                        for manifest in registered_scope_manifests
                    ),
                    {
                        "scope": persisted_scope,
                        "missing_registry_scope": missing_registry_scope,
                        "request_snapshot": str(
                            updated_manifest_path.parent / "request_snapshot.json"
                        ),
                        "analysis_report": str(
                            updated_manifest_path.parent / "analysis_report.md"
                        ),
                        "review_html": str(
                            updated_manifest_path.parent / "review.html"
                        ),
                        "delivery": delivery,
                        "registered_manifests": registered_scope_manifests,
                    },
                )
            )
            checks.append(
                _check(
                    "primary_scoped_delivery_is_not_full_figure_set_evidence",
                    "A ready primary result stays usable while provenance explicitly refuses to call the incomplete four-figure set complete",
                    updated_status.get("workflow", {}).get("state") == "ready"
                    and updated_status.get("workflow", {}).get("audit_state")
                    == "current_primary_figure"
                    and updated_status.get("provenance", {}).get("status")
                    == "current_primary_figure_evidence"
                    and updated_status.get("provenance", {}).get(
                        "primary_figure_evidence_current"
                    )
                    is True
                    and updated_status.get("provenance", {}).get(
                        "full_project_evidence_current"
                    )
                    is False
                    and updated_status.get("provenance", {}).get("complete") is False
                    and updated_status.get("provenance", {}).get(
                        "project_delivery_current"
                    )
                    is True
                    and updated_status.get("provenance", {}).get(
                        "full_figure_set_delivery_complete"
                    )
                    is False
                    and updated_export.get("figure_set_export_scope")
                    == persisted_scope,
                    {
                        "status": updated_status,
                        "export_scope": updated_export.get("figure_set_export_scope"),
                    },
                )
            )
        delivery_figures = (
            delivery.get("figures") if isinstance(delivery.get("figures"), list) else []
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
                and tampered_delivery_status.get("provenance", {}).get("complete")
                is False
                and tampered_delivery_status.get("workflow", {}).get("state")
                == "needs_fix"
                and project_bridge.open_pdf_button.isEnabled()
                and not project_bridge.show_delivery_button.isEnabled(),
                {
                    "delivery_pdf": (
                        str(delivery_pdf) if delivery_pdf is not None else None
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
            project_bridge._assistant_state_changed()
            active_assistant_controls = {
                "dock_export_enabled": project_bridge.export_button.isEnabled(),
                "menu_export_enabled": bool(
                    project_bridge.export_action is not None
                    and project_bridge.export_action.isEnabled()
                ),
                "dock_export_tooltip": project_bridge.export_button.toolTip(),
                "menu_export_tooltip": (
                    project_bridge.export_action.toolTip()
                    if project_bridge.export_action is not None
                    else None
                ),
            }
            active_assistant_export = project_bridge.export_current_document(
                show_dialog=False,
            )
        finally:
            assistant_bridge.runner = original_runner
            project_bridge._assistant_state_changed()
        runs_after_active_export = {
            path.resolve()
            for path in (copied_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        checks.append(
            _check(
                "active_assistant_blocks_bridge_export",
                "The Project bridge rejects export while an Assistant request is active and publishes no run",
                active_assistant_export.get("status") in {"failed", "rejected"}
                and active_assistant_export.get("ready_to_use") is not True
                and not isinstance(
                    active_assistant_export.get("studio_run"),
                    dict,
                )
                and active_assistant_controls.get("dock_export_enabled") is False
                and active_assistant_controls.get("menu_export_enabled") is False
                and "active sciplot ai request"
                in str(
                    active_assistant_controls.get("dock_export_tooltip") or ""
                ).casefold()
                and "active sciplot ai request"
                in str(
                    active_assistant_controls.get("menu_export_tooltip") or ""
                ).casefold()
                and runs_after_active_export == runs_before_active_export,
                {
                    "export": active_assistant_export,
                    "controls": active_assistant_controls,
                    "runs_before": sorted(
                        str(path) for path in runs_before_active_export
                    ),
                    "runs_after": sorted(
                        str(path) for path in runs_after_active_export
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
        internal_run_manifest = (
            Path(str(current_run["manifest"])).expanduser().resolve()
        )
        external_run_root = run_root / "external_registered_run"
        external_run_root.mkdir(parents=True, exist_ok=True)
        external_run_manifest = external_run_root / "manifest.json"
        shutil.copy2(internal_run_manifest, external_run_manifest)
        registered_manifest = json.loads(project_manifest_before.decode("utf-8"))
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
        escaped_evidence_value = escaped_run_status["qa"].get("evidence")
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
                    "external_manifest": str(external_run_manifest),
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
        changed_request_flags = _full_readiness_flags(changed_request_status)
        checks.append(
            _check(
                "changed_request_invalidates_full_readiness",
                "Changing plot_request.json prevents the prior run from remaining fully current",
                not changed_request_flags["qa_and_provenance_current"]
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
                handle.write(b"\n# SciPlot Studio source readiness probe\n")
            try:
                changed_source_status = project_bridge.refresh(
                    capture_render=True,
                    audit_source=True,
                )
            finally:
                with source_mutation_target.open("r+b") as handle:
                    handle.truncate(source_size_before)
        changed_source_flags = _full_readiness_flags(changed_source_status)
        checks.append(
            _check(
                "changed_source_invalidates_full_readiness",
                "Changing the bound project source prevents the prior run from remaining fully current",
                source_mutation_target is not None
                and changed_source_status["source"]["audit_status"]
                != "matches_last_run_lineage"
                and not changed_source_flags["qa_and_provenance_current"]
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

        save_as_fixture_root = run_root / "save_as_context"
        context_project = _copy_project_fixture(
            source_project,
            save_as_fixture_root,
        )
        context_document = _project_document(context_project)
        context_original_hash = file_sha256(context_document)
        context_provider = DeterministicStudioAssistantProvider()
        with _injected_provider_resolution(context_provider):
            context_window = _create_veusz_window(context_document)
        context_window.resize(1200, 820)
        context_window.show()
        _wait(application)
        context_project_bridge = context_window._sciplot_project_bridge
        context_assistant_bridge = context_window._sciplot_assistant_bridge
        context_registry_path = context_project / "studio" / "figure_set.json"
        context_registry = (
            _read_json_object(context_registry_path)
            if context_registry_path.is_file()
            else {}
        )
        context_registry_documents = [
            str(item.get("document") or "")
            for item in context_registry.get("figures", [])
            if isinstance(item, dict)
        ]
        context_figure_entries = context_project_bridge._figure_set_entries()
        context_figure_paths_relocated = bool(
            not context_registry
            and not context_figure_entries
            or (
                context_figure_entries
                and any(
                    value and not _is_within(Path(value), context_project)
                    for value in context_registry_documents
                )
                and all(
                    _is_within(
                        Path(str(item["document"])),
                        context_project / "studio",
                    )
                    and Path(str(item["document"])).is_file()
                    for item in context_figure_entries
                )
            )
        )
        context_axis, context_label = _axis_label_setting(context_window.document)
        context_window.document.applyOperation(
            OperationSettingSet(
                context_label,
                f"{context_label.get()} · atomic save probe",
            )
        )
        _wait(application)
        atomic_original_window_filename = str(context_window.filename)
        atomic_original_document_filename = str(context_window.document.filename)
        atomic_original_modified = bool(context_window.document.isModified())
        atomic_existing_hash = file_sha256(context_document)
        atomic_save_as_target = context_project / "studio" / "failed_atomic_save_as.vsz"
        atomic_save_errors: list[dict[str, Any]] = []
        original_context_document_save = context_window.document.save
        original_save_error_handler = getattr(
            context_window,
            "_sciplot_save_error_handler",
            None,
        )
        original_atomic_file_save_dialog = context_window.fileSaveDialog
        context_window.fileSaveDialog = lambda _filters, _title: None
        native_save_as_cancelled = bool(context_window.slotFileSaveAs())
        context_window.fileSaveDialog = original_atomic_file_save_dialog
        cancel_preserved_context = bool(
            str(context_window.filename) == atomic_original_window_filename
            and str(context_window.document.filename)
            == atomic_original_document_filename
            and bool(context_window.document.isModified()) == atomic_original_modified
        )

        def staged_partial_save(filename: str, mode: str = "vsz") -> None:
            Path(filename).write_bytes(
                b"# SciPlot staged partial write; this must never replace a target.\\n"
            )
            raise OSError(f"synthetic staged {mode} write failure")

        context_window.document.save = staged_partial_save
        context_window._sciplot_save_error_handler = atomic_save_errors.append
        atomic_bridge_export: dict[str, Any] = {}
        native_atomic_save = True
        native_atomic_save_as = True
        try:
            atomic_bridge_export = context_project_bridge.export_current_document(
                show_dialog=False
            )
            native_atomic_save = bool(context_window.slotFileSave())
            context_window.fileSaveDialog = lambda _filters, _title: str(
                atomic_save_as_target
            )
            native_atomic_save_as = bool(context_window.slotFileSaveAs())
        finally:
            context_window.document.save = original_context_document_save
            context_window.fileSaveDialog = original_atomic_file_save_dialog
            if original_save_error_handler is None:
                try:
                    delattr(context_window, "_sciplot_save_error_handler")
                except AttributeError:
                    pass
            else:
                context_window._sciplot_save_error_handler = original_save_error_handler
        atomic_staged_leftovers = sorted(
            str(path) for path in context_document.parent.glob(".*.sciplot-save-*")
        )
        checks.append(
            _check(
                "atomic_native_and_project_saves_preserve_last_good_vsz",
                "Native Save, native Save As, and Project export serialize beside the target and preserve the last good VSZ and live context when staged writing fails",
                atomic_original_modified
                and native_save_as_cancelled is False
                and cancel_preserved_context
                and atomic_bridge_export.get("state") == "export_exception"
                and atomic_bridge_export.get("ready_to_use") is False
                and native_atomic_save is False
                and native_atomic_save_as is False
                and file_sha256(context_document) == atomic_existing_hash
                and not atomic_save_as_target.exists()
                and str(context_window.filename) == atomic_original_window_filename
                and str(context_window.document.filename)
                == atomic_original_document_filename
                and bool(context_window.document.isModified())
                == atomic_original_modified
                and not atomic_staged_leftovers
                and len(atomic_save_errors) == 2,
                {
                    "project_export": atomic_bridge_export,
                    "native_save_as_cancelled": native_save_as_cancelled,
                    "cancel_preserved_context": cancel_preserved_context,
                    "native_save": native_atomic_save,
                    "native_save_as": native_atomic_save_as,
                    "existing_hash_before": atomic_existing_hash,
                    "existing_hash_after": file_sha256(context_document),
                    "save_as_target_exists": atomic_save_as_target.exists(),
                    "window_filename": str(context_window.filename),
                    "document_filename": str(context_window.document.filename),
                    "modified": bool(context_window.document.isModified()),
                    "staged_leftovers": atomic_staged_leftovers,
                    "native_save_errors": atomic_save_errors,
                },
            )
        )
        unvalidated_target = run_root / "unvalidated_atomic_save.vsz"
        unvalidated_target.write_text(
            "# previous validated document\n",
            encoding="utf-8",
        )

        class _UnvalidatedSaveBase:
            children: list[Any] = []

        class _UnvalidatedSaveDocument:
            def __init__(self, filename: Path) -> None:
                self.filename = str(filename)
                self.modified = True
                self.changeset = 7
                self.data: dict[str, Any] = {}
                self.basewidget = _UnvalidatedSaveBase()
                self._signals_blocked = False

            def isModified(self) -> bool:
                return bool(self.modified)

            def setModified(self, value: bool) -> None:
                self.modified = bool(value)

            def signalsBlocked(self) -> bool:
                return bool(self._signals_blocked)

            def blockSignals(self, value: bool) -> None:
                self._signals_blocked = bool(value)

            def save(self, filename: str, mode: str = "vsz") -> None:
                Path(filename).write_text(
                    "# staged owner-approved unsafe-command document\n",
                    encoding="utf-8",
                )
                self.filename = filename
                self.modified = False
                self.changeset += 1

        unvalidated_document = _UnvalidatedSaveDocument(unvalidated_target)
        original_staged_validator = (
            studio_module._validate_staged_veusz_document
        )
        studio_module._validate_staged_veusz_document = (
            lambda *_args, **_kwargs: False
        )
        try:
            unvalidated_receipt = studio_module.atomic_save_veusz_document(
                unvalidated_document,
                unvalidated_target,
            )
        finally:
            studio_module._validate_staged_veusz_document = (
                original_staged_validator
            )

        unvalidated_runs_before = {
            path.resolve()
            for path in (context_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        original_bridge_atomic_save = (
            studio_project_module.atomic_save_veusz_document
        )
        original_unvalidated_project_export = (
            context_project_bridge._project_export
        )
        unvalidated_project_export_called = False

        def forbidden_unvalidated_project_export() -> dict[str, Any]:
            nonlocal unvalidated_project_export_called
            unvalidated_project_export_called = True
            raise AssertionError(
                "An unvalidated atomic save reached project publication."
            )

        studio_project_module.atomic_save_veusz_document = (
            lambda *_args, **_kwargs: dict(unvalidated_receipt)
        )
        context_project_bridge._project_export = (
            forbidden_unvalidated_project_export
        )
        try:
            unvalidated_export = (
                context_project_bridge.export_current_document(
                    show_dialog=False,
                )
            )
        finally:
            studio_project_module.atomic_save_veusz_document = (
                original_bridge_atomic_save
            )
            context_project_bridge._project_export = (
                original_unvalidated_project_export
            )
        unvalidated_runs_after = {
            path.resolve()
            for path in (context_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        checks.append(
            _check(
                "unvalidated_atomic_save_is_preserved_but_never_published",
                "A secure-mode reopen rejection produces a truthful saved-unvalidated receipt, while Project export fails closed without publishing a run",
                unvalidated_receipt.get("status") == "saved_unvalidated"
                and unvalidated_receipt.get("reopen_validated") is False
                and unvalidated_receipt.get("ready_for_export") is False
                and unvalidated_target.read_text(encoding="utf-8")
                == "# staged owner-approved unsafe-command document\n"
                and unvalidated_document.isModified() is False
                and unvalidated_export.get("status") == "failed"
                and unvalidated_export.get("state") == "export_exception"
                and unvalidated_export.get("ready_to_use") is False
                and "secure-mode structural reopen"
                in str(
                    unvalidated_export.get("error", {}).get("message") or ""
                )
                and not unvalidated_project_export_called
                and unvalidated_runs_after == unvalidated_runs_before,
                {
                    "save_receipt": unvalidated_receipt,
                    "export": unvalidated_export,
                    "project_export_called": unvalidated_project_export_called,
                    "runs_unchanged": (
                        unvalidated_runs_after == unvalidated_runs_before
                    ),
                },
            )
        )
        context_assistant_bridge.set_selected_widget(context_axis)
        context_provider.configure(
            next_value=f"{context_label.get()} · stale after Save As"
        )
        context_request = context_assistant_bridge.submit_intent(
            "Prepare a proposal that Save As must invalidate."
        )
        context_proposal_ready = _wait_until(
            application,
            lambda: (
                context_assistant_bridge.pending_batch is not None
                and not context_assistant_bridge.runner.active
            ),
            timeout_ms=8000,
        )
        context_manifest_paths = [
            context_project / "intake_manifest.json",
            *sorted(context_project.glob("*.sciplot.json")),
        ]
        context_manifest_before = {
            path.resolve(): path.read_bytes()
            for path in context_manifest_paths
            if path.is_file()
        }
        context_runs_before = {
            path.resolve()
            for path in (context_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        save_as_path = context_project / "studio" / "save_as_copy.vsz"
        original_file_save_dialog = context_window.fileSaveDialog
        context_window.fileSaveDialog = lambda _filters, _title: str(save_as_path)
        try:
            context_window.slotFileSaveAs()
        finally:
            context_window.fileSaveDialog = original_file_save_dialog
        _wait(application)
        from veusz import document as veusz_document

        save_as_reopened = veusz_document.Document()
        save_as_reopened.load(str(save_as_path))
        save_as_reopen_matches = bool(
            sorted(str(name) for name in save_as_reopened.data)
            == sorted(str(name) for name in context_window.document.data)
            and [
                (str(child.name), str(getattr(child, "typename", "")))
                for child in save_as_reopened.basewidget.children
            ]
            == [
                (str(child.name), str(getattr(child, "typename", "")))
                for child in context_window.document.basewidget.children
            ]
        )
        provider_requests_before_blocked_ask = len(context_provider.requests)
        blocked_ask_error: str | None = None
        try:
            context_assistant_bridge.submit_intent(
                "This request must be rejected after Save As."
            )
        except RuntimeError as exc:
            blocked_ask_error = str(exc)
        context_project_export_called = False
        original_context_project_export = context_project_bridge._project_export

        def forbidden_context_project_export() -> dict[str, Any]:
            nonlocal context_project_export_called
            context_project_export_called = True
            raise AssertionError("A Save As context mismatch reached project export.")

        context_project_bridge._project_export = forbidden_context_project_export
        try:
            save_as_export = context_project_bridge.export_current_document(
                show_dialog=False
            )
        finally:
            context_project_bridge._project_export = original_context_project_export
        context_runs_after = {
            path.resolve()
            for path in (context_project / "runs").glob("studio_*")
            if path.is_dir()
        }
        context_manifest_after_unchanged = all(
            path.read_bytes() == content
            for path, content in context_manifest_before.items()
        )
        context_message = context_assistant_bridge.status_label.text()
        context_changed_status = context_project_bridge.status_snapshot
        context_changed_workflow = (
            context_changed_status.get("workflow")
            if isinstance(context_changed_status.get("workflow"), dict)
            else {}
        )
        context_changed_qa = (
            context_changed_status.get("qa")
            if isinstance(context_changed_status.get("qa"), dict)
            else {}
        )
        context_changed_provenance = (
            context_changed_status.get("provenance")
            if isinstance(context_changed_status.get("provenance"), dict)
            else {}
        )
        context_changed_results = (
            context_changed_status.get("results")
            if isinstance(context_changed_status.get("results"), dict)
            else {}
        )
        checks.append(
            _check(
                "native_save_as_rebinds_title_and_fail_closes_old_context",
                "A real offscreen native Save As updates the title but blocks old-path Project export and AI context until the new VSZ is reopened",
                context_proposal_ready
                and context_request is not None
                and save_as_path.is_file()
                and Path(str(context_window.filename)).resolve()
                == save_as_path.resolve()
                and context_window.windowTitle() == "save_as_copy — SciPlot Studio"
                and save_as_reopen_matches
                and context_figure_paths_relocated
                and file_sha256(context_document) == context_original_hash
                and save_as_export.get("state") == "document_context_changed"
                and save_as_export.get("ready_to_use") is False
                and not context_project_export_called
                and context_runs_after == context_runs_before
                and context_manifest_after_unchanged
                and context_project_bridge.export_button.isEnabled() is False
                and context_project_bridge.status_snapshot.get("workflow", {}).get(
                    "state"
                )
                == "document_context_changed"
                and context_changed_workflow.get("result_ready") is False
                and "ready"
                not in str(context_changed_workflow.get("message") or "").casefold()
                and context_changed_qa.get("ready_to_use") is False
                and context_changed_qa.get("current_document") is False
                and context_changed_qa.get("document_hash_current") is False
                and context_changed_qa.get("artifact_qa_current") is False
                and context_changed_qa.get("exports_current") is False
                and context_changed_provenance.get("complete") is False
                and context_changed_provenance.get(
                    "full_project_evidence_current"
                )
                is False
                and context_changed_provenance.get(
                    "primary_figure_evidence_current"
                )
                is False
                and context_changed_provenance.get("project_delivery_current")
                is False
                and all(
                    value is not True
                    for key, value in context_changed_provenance.items()
                    if key == "current"
                    or key == "complete"
                    or key.endswith("_current")
                    or key.endswith("_complete")
                )
                and bool(context_changed_results)
                and all(
                    isinstance(target, dict)
                    and target.get("current") is False
                    and target.get("available") is False
                    for target in context_changed_results.values()
                )
                and context_assistant_bridge.pending_batch is None
                and context_assistant_bridge._pending_request is None
                and context_assistant_bridge.ask_button.isEnabled() is False
                and blocked_ask_error is not None
                and "close this window and reopen" in blocked_ask_error.casefold()
                and "close this window and reopen" in context_message.casefold()
                and len(context_provider.requests)
                == provider_requests_before_blocked_ask,
                {
                    "old_document": str(context_document),
                    "new_document": str(save_as_path),
                    "window_filename": str(context_window.filename),
                    "window_title": context_window.windowTitle(),
                    "save_as_reopen_matches": save_as_reopen_matches,
                    "registry_documents": context_registry_documents,
                    "derived_figure_entries": context_figure_entries,
                    "figure_paths_relocated": context_figure_paths_relocated,
                    "old_document_hash": file_sha256(context_document),
                    "save_as_export": save_as_export,
                    "context_changed_status": context_changed_status,
                    "project_export_called": context_project_export_called,
                    "runs_unchanged": context_runs_after == context_runs_before,
                    "manifests_unchanged": context_manifest_after_unchanged,
                    "assistant_pending": (
                        context_assistant_bridge.pending_batch is not None
                    ),
                    "assistant_ask_enabled": (
                        context_assistant_bridge.ask_button.isEnabled()
                    ),
                    "assistant_status": context_message,
                    "blocked_ask_error": blocked_ask_error,
                    "provider_requests": len(context_provider.requests),
                },
            )
        )
        _close_window(context_window)
        context_window = None

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
        standalone_export = standalone_bridge.export_current_document(show_dialog=False)
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
                and standalone_export.get("scope") == "standalone_exact_current_export"
                and receipt.get("provenance_complete") is False
                and receipt.get("project_delivery_complete") is False
                and standalone_status["source"]["status"] == "not_established"
                and standalone_status["mapping"]["status"] == "unavailable"
                and standalone_status["qa"]["status"] == "passed_for_current_document",
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
                and tampered_standalone_status.get("qa", {}).get("status")
                != "passed_for_current_document"
                and tampered_standalone_status.get("qa", {}).get("current_document")
                is not True
                and deleted_standalone_status.get("qa", {}).get("status")
                != "passed_for_current_document"
                and deleted_standalone_status.get("qa", {}).get("current_document")
                is not True
                and tampered_standalone_status.get("workflow", {}).get("state")
                == "needs_fix"
                and deleted_standalone_status.get("workflow", {}).get("state")
                == "needs_fix",
                {
                    "tiff": (
                        str(standalone_tiff) if standalone_tiff is not None else None
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
                    mapping_light_status["mapping"]["status"] == "audit_pending"
                    and mapping_light_status["source"]["audit_status"] == "not_computed"
                    and mapping_light_status["qa"]["status"]
                    == "passed_for_current_document"
                    and mapping_light_status.get("workflow", {}).get("state") == "ready"
                    and mapping_light_status.get("workflow", {}).get("audit_state")
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
                    and mapping_status["qa"]["status"] == "passed_for_current_document",
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
            "launcher_contract": launcher_contract,
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
            "tampered_standalone_status": (tampered_standalone_status),
            "deleted_standalone_status": (deleted_standalone_status),
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
        _close_window(figure_window)
        _close_window(project_window)
        _close_window(context_window)
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
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
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
