"""Route the public Studio command to prepare, launch, export, or publish actions."""

from __future__ import annotations

import json
from pathlib import Path
from sciplot_core.foundation.json_values import json_safe

from sciplot_core.studio_core.runtime import (
    upstream_status,
    maybe_reexec_with_qt_runtime,
    _split_formats,
)

from sciplot_core.studio_core.launchers import (
    _prefer_offscreen_export_platform,
)

from sciplot_core.studio_core.persistence import (
    _is_project_secondary_document,
    _standalone_export_artifact_root,
)

from sciplot_core.studio_core.qt_launch import (
    qt_smoke_payload,
    launch_veusz_gui,
    launch_sciplot_studio,
)

from sciplot_core.studio_core.export_execution import (
    export_studio_document,
)

from sciplot_core.studio_core.standalone_receipt import (
    publish_standalone_export_receipt,
)

from sciplot_core.studio_core.publish_run import (
    publish_studio_export_run,
)

from sciplot_core.studio_core.registry_writes import (
    _register_studio_exports,
)

from sciplot_core.studio_core.studio_prepare import (
    prepare_studio_document,
)


def run_studio_command(
    *,
    target: Path | None = None,
    output_root: Path | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    new: bool = False,
    export: str | None = None,
    json_output: bool = False,
    prepare_only: bool = False,
    qt_smoke: bool = False,
    original_argv: list[str] | None = None,
) -> int:
    if qt_smoke:
        # GUI smoke runs inside CI/Codex processes which may not own an Aqua
        # application session.  Exercise the real MainWindow offscreen so the
        # check cannot crash in macOS application registration.
        _prefer_offscreen_export_platform()
        maybe_reexec_with_qt_runtime(original_argv or ["studio", "--qt-smoke"])
        payload = qt_smoke_payload(target.expanduser() if target is not None else None)
        print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
        return 0

    if new:
        payload = {
            "kind": "sciplot_studio_session",
            "mode": "new",
            "upstreams": upstream_status(),
        }
        if json_output or prepare_only:
            print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
            return 0
        maybe_reexec_with_qt_runtime(original_argv or ["studio", "--new"])
        return launch_veusz_gui(None)

    if target is None:
        raise ValueError("studio needs PATH or --new.")

    if not (json_output or prepare_only or export):
        maybe_reexec_with_qt_runtime(original_argv or ["studio", str(target)])
        return launch_sciplot_studio(
            target,
            output_root=output_root,
            delivery_root=delivery_root,
            rule_id=rule_id,
            template=template,
            project_name=project_name,
        )

    if json_output or prepare_only or export:
        command = ["studio", str(target)]
        if rule_id:
            command.extend(["--rule", rule_id])
        if template:
            command.extend(["--template", template])
        if project_name:
            command.extend(["--name", project_name])
        if export:
            command.extend(["--export", export])
        if json_output:
            command.append("--json")
        if prepare_only:
            command.append("--prepare-only")
        maybe_reexec_with_qt_runtime(original_argv or command)

    payload = prepare_studio_document(
        target,
        output_root=output_root,
        delivery_root=delivery_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    document_path = Path(payload["document"])
    if export:
        requested_formats = _split_formats(export)
        standalone_export = payload.get("mode") == "vsz"
        standalone_root = (
            output_root.expanduser().resolve()
            if standalone_export and output_root is not None
            else _standalone_export_artifact_root(document_path)
        )
        export_dir = (
            standalone_root / "figures"
            if standalone_export
            and (
                output_root is not None or _is_project_secondary_document(document_path)
            )
            else None
        )
        export_payload = export_studio_document(
            document_path,
            formats=requested_formats,
            output_dir=export_dir,
        )
        payload["exports"] = export_payload["exports"]
        if payload.get("project_dir"):
            studio_run = publish_studio_export_run(
                project_dir=Path(payload["project_dir"]),
                request_path=Path(payload["request"]),
                document_path=document_path,
                exports=payload["exports"],
                export_document_sha256=str(export_payload["document_sha256"]),
            )
            payload["studio_run"] = studio_run
            if isinstance(studio_run.get("exports"), list):
                payload["exports"] = json_safe(studio_run["exports"])
            _register_studio_exports(
                Path(payload["project_dir"]), payload["exports"], studio_run=studio_run
            )
            figure_set_export_scope = studio_run.get("figure_set_export_scope")
            if isinstance(figure_set_export_scope, dict):
                payload["figure_set_export_scope"] = json_safe(figure_set_export_scope)
            payload["scope"] = str(studio_run.get("scope") or "project_delivery")
        elif standalone_export:
            receipt = publish_standalone_export_receipt(
                document_path=document_path,
                requested_formats=requested_formats,
                exports=payload["exports"],
                artifact_root=standalone_root,
                export_document_sha256=str(export_payload["document_sha256"]),
            )
            payload["standalone_export"] = receipt
            payload["status"] = receipt["status"]
            payload["state"] = receipt["state"]
            payload["export_ready"] = receipt["export_ready"]

    if json_output or prepare_only or export:
        print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
        if export:
            studio_run = payload.get("studio_run")
            standalone_receipt = payload.get("standalone_export")
            if isinstance(studio_run, dict):
                if studio_run.get("ready_to_use") is not True:
                    return 1
            elif (
                not isinstance(standalone_receipt, dict)
                or standalone_receipt.get("export_ready") is not True
            ):
                return 1
        return 0

    return launch_veusz_gui(document_path)
