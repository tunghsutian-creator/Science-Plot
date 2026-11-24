"""Freeze existing source authority without importing it into the layout model."""

from __future__ import annotations

import io
from importlib import import_module
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.managed_state import input_files, require_inputs
from sciplot_core.plot_engine.storage import digest, read
from sciplot_core.project_lifecycle.figure_observation import (
    observe_legacy_project, observe_plot_head, observe_project_figure_heads,
)
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.task_paper_sources import assert_selection_current, capture_selection

from .errors import AssemblyError


def _project_reference(project: Path, figure_id: str, authority: tuple[Path, dict[str, Any]] | None) -> dict[str, Any]:
    if authority is not None:
        root, head = authority
        document = head["document"]
        if document.get("plot_type") == "ManagedPlot":
            return {"kind": "managed", "project": str(root), "plot_id": document["plot_id"]}
    return {"kind": "project", "project": str(project), "figure_id": figure_id}


def project_reference(project: str | Path, figure_id: str) -> dict[str, Any]:
    """Select existing canonical authority without creating or adopting a plot."""
    project = canonical_path(Path(project))
    return _project_reference(project, figure_id, observe_project_figure_heads(project, (figure_id,)).get(figure_id))


def project_references(project: str | Path) -> list[tuple[str, dict[str, Any]]]:
    """Read catalogue titles with authority-correct references for selection UIs."""
    observation = observe_legacy_project(Path(project))
    root = observation.project
    heads = observe_project_figure_heads(root, [item["figure_id"] for item in observation.figures])
    rows = [(f"{root.name} / {item['title']} ({item['figure_id']})",
             _project_reference(root, item["figure_id"], heads.get(item["figure_id"]))) for item in observation.figures]
    observation.require_current()
    return rows

def _require_legacy_authority(project: Path, figure_id: str) -> None:
    reference = project_reference(project, figure_id)
    if reference["kind"] == "managed":
        raise AssemblyError("assembly_managed_reference_required",
                            "This figure has ManagedPlot authority. Explicitly select its managed document reference.",
                            issues=[{"code": "use_managed_reference", "reference": reference}])


def file_binding(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    snapshot = stable_file_snapshot(path, label="assembly source", expected_sha256=expected_sha256)
    return {"path": str(snapshot["path"]), "sha256": snapshot["sha256"],
            "identity": {key: value for key, value in snapshot["identity"].items() if key != "ctime_ns"}}


def _snapshot_binding(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {"path": str(snapshot["path"]), "sha256": snapshot["sha256"],
            "identity": {key: value for key, value in snapshot["identity"].items() if key != "ctime_ns"}}


def bound_image_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    """Read exact frozen bytes without re-opening the decoded PDF or image."""
    bound = source["binding"]["snapshot"]
    try:
        snapshot = stable_file_snapshot(Path(source["path"]), label="assembly image", expected_sha256=bound["sha256"])
    except (ValueError, OSError) as exc:
        raise AssemblyError("assembly_source_stale", "Selected source is stale or unverifiable: the image bytes changed or could not be read.") from exc
    if _snapshot_binding(snapshot) != bound:
        raise AssemblyError("assembly_source_stale", "Selected source is stale or unverifiable: the image identity changed.")
    return snapshot


def pdf_diagram_size(pdf: Any) -> tuple[float, float]:
    if pdf.is_encrypted or len(pdf) != 1 or pdf[0].rect.is_empty:
        raise AssemblyError("assembly_image_unsupported", "A diagram PDF must contain one unencrypted page.")
    bounds = pdf[0].rect
    return bounds.width, bounds.height


def image_media_type(image: Any) -> str:
    media = {"PNG": "image/png", "JPEG": "image/jpeg", "TIFF": "image/tiff"}.get(image.format)
    if media is None or getattr(image, "n_frames", 1) != 1:
        raise AssemblyError("assembly_image_unsupported", "Use a single PNG, JPEG, TIFF or one-page PDF diagram.")
    return media


def _image(path: Path, *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    if snapshot is None:
        snapshot = stable_file_snapshot(path, label="assembly image")
    if path.suffix.lower() == ".pdf":
        pymupdf: Any = import_module("pymupdf")

        with pymupdf.open(stream=snapshot["bytes"], filetype="pdf") as pdf:
            width, height = pdf_diagram_size(pdf)
        media = "application/pdf"
    else:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(snapshot["bytes"])) as image:
            media = image_media_type(image)
            image.load()
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
    _assert_snapshot_current(snapshot, label="assembly image", expected_sha256=snapshot["sha256"])
    return {"snapshot": _snapshot_binding(snapshot), "media_type": media, "width": width, "height": height}


def managed_head(root: Path, plot_id: str) -> dict[str, Any]:
    head = observe_plot_head(root)
    assert head is not None
    document, binding = head["document"], head["binding"]
    if document.get("plot_type") != "ManagedPlot" or document["plot_id"] != plot_id:
        raise AssemblyError("assembly_managed_authority", "Select the current ManagedPlot document root and its exact plot ID.")
    require_inputs(document)
    # A cache may be absent and can be rebuilt. An existing externally saved
    # artifact must never acquire canonical authority through assembly.
    native = Path(binding["document"])
    if native.exists():
        marker = native.parent / "build.json"
        if (not marker.is_file() or read(marker).get("ir_hash") != binding["ir_hash"]
                or read(marker).get("document_sha256") != file_sha256(native)):
            raise AssemblyError("assembly_source_stale", "The managed native artifact changed outside its semantic document.")
    return head


def _managed(root: Path, plot_id: str, *, expected_files: dict[str, str] | None = None) -> dict[str, Any]:
    head = managed_head(root, plot_id)
    document = head["document"]
    paths = {root / "head.json", root / "revisions" / f"{document['revision']:08d}.json",
             Path(head["binding"]["canonical_document"])}
    paths.update(Path(name) for name in input_files(document))
    paths.update(Path(name) for name in head["binding"].get("scientific_content_files", {}))
    known = {**input_files(document), **head["binding"].get("scientific_content_files", {}), **(expected_files or {})}
    return {"revision": document["revision"], "scientific_hash": document["scientific_hash"],
            "presentation_hash": document["presentation_hash"], "envelope_sha256": digest(head),
            "files": [file_binding(path, expected_sha256=known.get(str(path))) for path in sorted(paths)]}


def capture_source(reference: dict[str, Any]) -> dict[str, Any]:
    """Capture an explicitly selected current version; refresh is a new capture."""
    try:
        kind = reference.get("kind") if isinstance(reference, dict) else None
        keys = {"project": {"kind", "project", "figure_id"},
                "managed": {"kind", "project", "plot_id"}, "image": {"kind", "path"}}
        if kind not in keys or set(reference) != keys[kind]:
            raise AssemblyError("assembly_source_invalid", "Use an explicit project, managed plot or image reference.")
        result = dict(reference)
        path_key = "path" if kind == "image" else "project"
        result[path_key] = str(canonical_path(Path(reference[path_key])))
        path = Path(result[path_key])
        if kind == "project":
            _require_legacy_authority(path, reference["figure_id"])
            selection = capture_selection(path, reference["figure_id"])
            files = [Path(selection[key]) for key in ("document", "spec")]
            files.append(path / "plot_request.json")
            if (path / "studio/figure_set.json").exists():
                files.append(path / "studio/figure_set.json")
            result["binding"] = {"selection": selection, "files": [file_binding(item) for item in sorted(files)]}
        elif kind == "managed":
            result["binding"] = _managed(path, reference["plot_id"])
        else:
            # _image already decodes and checks the exact captured snapshot.
            result["binding"] = _image(path)
            return result
        assert_source_current(result)
        return result
    except AssemblyError:
        raise
    except Exception as exc:
        raise AssemblyError("assembly_source_unavailable", f"Cannot capture selected source: {exc}") from exc


def assert_source_current(source: dict[str, Any]) -> None:
    """Refuse drift; never silently update a frozen layout binding."""
    try:
        kind, binding = source["kind"], source["binding"]
        expected = {"project": {"kind", "project", "figure_id", "binding"},
                    "managed": {"kind", "project", "plot_id", "binding"},
                    "image": {"kind", "path", "binding"}}
        if kind not in expected or set(source) != expected[kind]:
            raise ValueError("Invalid frozen source fields.")
        if kind == "project":
            _require_legacy_authority(Path(source["project"]), source["figure_id"])
            if set(binding) != {"selection", "files"}:
                raise ValueError("Invalid project binding.")
            selection = binding["selection"]
            if (selection["project"], selection["figure_id"]) != (source["project"], source["figure_id"]):
                raise ValueError("Project selection and binding disagree.")
            assert_selection_current(selection)
            paths = [Path(selection[key]) for key in ("document", "spec")]
            paths.append(Path(selection["project"]) / "plot_request.json")
            registry = Path(selection["project"]) / "studio/figure_set.json"
            if registry.exists():
                paths.append(registry)
            expected_files = {item["path"]: item["sha256"] for item in binding["files"]}
            if [file_binding(item, expected_sha256=expected_files.get(str(item))) for item in sorted(paths)] != binding["files"]:
                raise ValueError("The native authority file identity or bytes changed.")
        elif kind == "managed":
            if _managed(canonical_path(Path(source["project"])), source["plot_id"],
                        expected_files={item["path"]: item["sha256"] for item in binding["files"]}) != binding:
                raise ValueError("The managed document version or scientific sources changed.")
        elif _image(canonical_path(Path(source["path"])), snapshot=bound_image_snapshot(source)) != binding:
            raise ValueError("The selected image version changed.")
    except Exception as exc:
        if isinstance(exc, AssemblyError) and exc.code in {"assembly_source_stale", "assembly_managed_reference_required"}:
            raise
        raise AssemblyError("assembly_source_stale", f"Selected source is stale or unverifiable: {exc}") from exc
