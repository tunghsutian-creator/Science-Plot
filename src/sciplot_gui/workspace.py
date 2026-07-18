from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe
from sciplot_core.canvas.assistant_contract import DataMappingProposal
from sciplot_core.data_mapping import verify_data_mapping_sources
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


def _request_path_candidate(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _mapping_source_candidates(workspace: CanvasWorkspace) -> list[Path]:
    if workspace.request_path is None or workspace.project_dir is None:
        return []
    request_path = workspace.request_path.resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Canvas plot_request.json must contain a JSON object.")
    candidates: list[Path] = []

    input_path = _request_path_candidate(
        request.get("input"), base_dir=request_path.parent
    )
    if input_path is not None:
        candidates.append(input_path if input_path.is_dir() else input_path.parent)
    candidates.extend(
        (
            workspace.project_dir / "source",
            workspace.project_dir / "raw",
            request_path.parent,
        )
    )

    study_model = request.get("study_model")
    samples = (
        study_model.get("samples")
        if isinstance(study_model, dict)
        and isinstance(study_model.get("samples"), list)
        else []
    )
    for sample in samples:
        replicates = (
            sample.get("replicates")
            if isinstance(sample, dict)
            and isinstance(sample.get("replicates"), list)
            else []
        )
        for replicate in replicates:
            source_file = (
                replicate.get("source_file")
                if isinstance(replicate, dict)
                and isinstance(replicate.get("source_file"), dict)
                else {}
            )
            for key in ("raw_path", "source_path"):
                candidate = _request_path_candidate(
                    source_file.get(key), base_dir=request_path.parent
                )
                if candidate is not None:
                    candidates.append(
                        candidate if candidate.is_dir() else candidate.parent
                    )

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def resolve_data_mapping_source_root(
    workspace: CanvasWorkspace,
    proposal: DataMappingProposal,
    *,
    selected_root: Path | None = None,
) -> Path:
    """Resolve one hash-valid source root without guessing between copies."""

    if not workspace.has_project_delivery:
        raise ValueError(
            "Data mapping requires a SciPlot project with plot_request.json; "
            "a standalone VSZ has no raw-data authority to confirm."
        )
    if selected_root is not None:
        selected = selected_root.expanduser().resolve()
        verify_data_mapping_sources(proposal, source_root=selected)
        return selected

    matches: list[tuple[Path, tuple[str, ...]]] = []
    for candidate in _mapping_source_candidates(workspace):
        try:
            resolved = verify_data_mapping_sources(
                proposal, source_root=candidate
            )
        except (FileNotFoundError, ValueError):
            continue
        matches.append(
            (
                candidate,
                tuple(
                    str(resolved[source.source_id].resolve())
                    for source in proposal.sources
                ),
            )
        )
    if not matches:
        raise FileNotFoundError(
            "SciPlot could not locate every hash-matched source from the current "
            "project. Choose the folder that contains the proposal's relative paths."
        )
    source_sets = {paths for _root, paths in matches}
    if len(source_sets) != 1:
        raise ValueError(
            "More than one different source tree matches this proposal. Choose "
            "the intended source folder explicitly."
        )
    return matches[0][0]


def default_data_mapping_output_root(workspace: CanvasWorkspace) -> Path:
    if workspace.project_dir is None:
        raise ValueError("Standalone VSZ workspaces cannot create mapped projects.")
    return (workspace.project_dir.parent / "mapped_projects").resolve()


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
    "default_data_mapping_output_root",
    "export_canvas_workspace",
    "resolve_data_mapping_source_root",
    "resolve_canvas_workspace",
]
