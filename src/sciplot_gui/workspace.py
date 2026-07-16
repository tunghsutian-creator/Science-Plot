from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe
from sciplot_core.studio import (
    export_studio_document,
    prepare_studio_document,
    publish_standalone_export_receipt,
    publish_studio_export_run,
)


@dataclass(frozen=True)
class CanvasWorkspace:
    target: Path
    mode: str
    project_id: str
    document_path: Path
    session_root: Path
    session_path: Path
    annotations_path: Path
    journal_path: Path
    project_dir: Path | None = None
    request_path: Path | None = None

    @property
    def has_project_delivery(self) -> bool:
        return self.project_dir is not None and self.request_path is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "sciplot_canvas_workspace",
            "version": 1,
            "target": str(self.target),
            "mode": self.mode,
            "project_id": self.project_id,
            "document": str(self.document_path),
            "session_root": str(self.session_root),
            "session": str(self.session_path),
            "review_annotations": str(self.annotations_path),
            "journal": str(self.journal_path),
            "project_dir": str(self.project_dir) if self.project_dir else None,
            "request": str(self.request_path) if self.request_path else None,
            "has_project_delivery": self.has_project_delivery,
        }


def _standalone_session_root(document_path: Path) -> Path:
    path_key = hashlib.sha256(str(document_path).encode("utf-8")).hexdigest()[:12]
    return document_path.parent / ".sciplot_canvas" / f"{document_path.stem}_{path_key}"


def resolve_canvas_workspace(
    target: Path,
    *,
    output_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> CanvasWorkspace:
    resolved_target = target.expanduser().resolve()
    payload = prepare_studio_document(
        resolved_target,
        output_root=output_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    document_path = Path(str(payload["document"])).expanduser().resolve()
    project_value = payload.get("project_dir")
    request_value = payload.get("request")
    project_dir = (
        Path(str(project_value)).expanduser().resolve() if project_value else None
    )
    request_path = (
        Path(str(request_value)).expanduser().resolve() if request_value else None
    )
    if project_dir is not None:
        session_root = project_dir / ".sciplot_canvas"
        project_id = project_dir.name
        mode = "project"
    else:
        session_root = _standalone_session_root(document_path)
        project_id = document_path.stem
        mode = "standalone_vsz"
    session_root.mkdir(parents=True, exist_ok=True)
    return CanvasWorkspace(
        target=resolved_target,
        mode=mode,
        project_id=project_id,
        document_path=document_path,
        session_root=session_root.resolve(),
        session_path=(session_root / "canvas_session.json").resolve(),
        annotations_path=(session_root / "review_annotations.json").resolve(),
        journal_path=(session_root / "operation_journal.jsonl").resolve(),
        project_dir=project_dir,
        request_path=request_path,
    )


def export_canvas_workspace(
    workspace: CanvasWorkspace,
    *,
    formats: tuple[str, ...] = ("pdf", "tiff_300"),
) -> dict[str, Any]:
    requested_formats = [str(item) for item in formats]
    if workspace.has_project_delivery:
        export_payload = export_studio_document(
            workspace.document_path,
            formats=requested_formats,
        )
        exports = list(export_payload.get("exports") or [])
        run = publish_studio_export_run(
            project_dir=workspace.project_dir,
            request_path=workspace.request_path,
            document_path=workspace.document_path,
            exports=exports,
        )
        return {
            "kind": "sciplot_canvas_export",
            "version": 1,
            "scope": "project_delivery",
            "status": "passed" if run.get("ready_to_use") is True else "failed",
            "state": run.get("state"),
            "ready_to_use": run.get("ready_to_use") is True,
            "exports": json_safe(exports),
            "studio_run": json_safe(run),
        }

    artifact_root = workspace.session_root / "exact_current_export"
    export_payload = export_studio_document(
        workspace.document_path,
        formats=requested_formats,
        output_dir=artifact_root / "figures",
    )
    exports = list(export_payload.get("exports") or [])
    receipt = publish_standalone_export_receipt(
        document_path=workspace.document_path,
        requested_formats=requested_formats,
        exports=exports,
        artifact_root=artifact_root,
    )
    return {
        "kind": "sciplot_canvas_export",
        "version": 1,
        "scope": "standalone_exact_current_export",
        "status": receipt.get("status"),
        "state": receipt.get("state"),
        "ready_to_use": receipt.get("export_ready") is True,
        "exports": json_safe(exports),
        "standalone_export": json_safe(receipt),
    }


__all__ = [
    "CanvasWorkspace",
    "export_canvas_workspace",
    "resolve_canvas_workspace",
]
