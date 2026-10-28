"""A standalone output aggregate reads a native project without changing its head."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import MembershipRead, ProjectCommand, ProjectCommands, ProjectMutation, MissingGeneratedOutput
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.project_command_scope import figure_read_state, project_store
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.export_projection import export_projection


def _dedicated_output(root: Path, document: Path) -> None:
    if not root.exists():
        return
    allowed = {"figures", "qa_inputs", "qa_report.json", "standalone_export_receipt.json", ".sciplot_store"}
    if any(path.name not in allowed for path in root.iterdir()):
        raise ValueError("Standalone export requires a dedicated output directory; existing files were preserved")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Standalone export cannot follow an output symlink")
    receipt = root / "standalone_export_receipt.json"
    if not receipt.exists() and any(path.is_file() for path in root.rglob("*")
                                    if ".sciplot_store" not in path.relative_to(root).parts):
        raise ValueError("Existing standalone files have no owning receipt; all files were preserved")
    if receipt.exists():
        import json

        value = json.loads(receipt.read_text())
        if value.get("kind") != "sciplot_standalone_vsz_export" or value.get("document") != str(document):
            raise ValueError("This output aggregate belongs to another native document")


def _current_output(root: Path, record: dict[str, Any]) -> None:
    expected = {name: entry for name, entry in record["draft"]["writes"].items() if entry is not None}
    actual = {path.relative_to(root).as_posix(): file_sha256(path) for path in root.rglob("*")
              if path.is_file() and ".sciplot_store" not in path.relative_to(root).parts}
    if set(actual) != set(expected) or any(actual[name] != entry["sha256"] for name, entry in expected.items()):
        raise ValueError("The standalone output file set changed; its historical receipt is not current")


def export_external_native(document: Path, *, formats: list[str], output_root: Path) -> dict[str, Any]:
    """Publish PDF/TIFF/QA together; source bytes and native history stay read-only."""
    from sciplot_core.studio_core.native_export_adapter import export_studio_document
    from sciplot_core.studio_core.publication_candidates import _stage_tree, relocate_candidate
    from sciplot_core.studio_core.standalone_receipt import publish_standalone_export_receipt
    from sciplot_core.policy import normalize_export_formats

    formats = list(normalize_export_formats(formats, default=()))
    selected = resolve_project_figure(document)
    project = Path(selected["project"])
    root = canonical_path(output_root)
    if root.is_relative_to(project):
        raise ValueError("Choose a standalone output outside the read-only source project")
    _dedicated_output(root, document)
    root.mkdir(parents=True, exist_ok=True)
    output_store = FileProjectStore(root)
    before = output_store.snapshot(import_legacy=True)
    # Opening a saved native file solely to export elsewhere does not create a
    # source-project store or history. Existing cold projects use their locator.
    context = project_runtime(project_store(project)) if (project / ".sciplot_store").exists() else nullcontext()
    with context:
        witness = figure_read_state(project, selected)
        request = {"document": str(document), "figure_id": selected["figure_id"], "formats": formats,
                   "source_read_witness": witness, "authority": "standalone_output_artifacts"}
        from sciplot_core.studio_core.export_replay import current_export
        app = ProjectCommands(output_store)
        prior, automatic = current_export(app, output_store, request, kind="export", whole_output=True)
        if prior is not None:
            _current_output(root, prior)
            if figure_read_state(project, selected) != witness:
                raise ValueError("The source native revision changed during standalone replay")
            return export_projection(prior, output_store, document=document, spec=Path(selected["spec"]),
                                     receipt_key="output_command")
        before = output_store.snapshot()
        request.update(automatic)
        key = canonical_json_sha256({"project_id": before["project_id"], "request": request})
        with TemporaryDirectory(prefix="sciplot-standalone-export-") as temporary:
            private = Path(temporary).resolve() / "artifacts"
            exported = export_studio_document(document, formats=formats, output_dir=private / "figures",
                                               audit_spec_path=Path(selected["spec"]))
            receipt = publish_standalone_export_receipt(document_path=document, requested_formats=formats,
                exports=exported["exports"], artifact_root=private,
                export_document_sha256=exported["document_sha256"])
            if figure_read_state(project, selected) != witness:
                raise ValueError("The source native revision changed during standalone export")
            roots = {private: root}
            payload = relocate_candidate({**exported, "standalone_export": receipt}, roots)
            payload.pop("stderr_log", None)
            writes: dict[str, bytes | Path | PreparedFile | None] = {name: None for name in before["files"]}
            _stage_tree(private, "", writes, roots)
            reads = {name: before["files"].get(name, {}).get("sha256") for name in writes}
            command = ProjectCommand.create("export", key, project_id=before["project_id"],
                expected_generation=before["generation"], read_set=reads, write_set=list(writes), request=request,
                read_memberships=[MembershipRead.capture(before["files"])],
                missing_outputs=tuple(MissingGeneratedOutput.from_payload(item) for item in automatic.get("missing_outputs", [])))
            record = app.execute(command, lambda: ProjectMutation(writes, payload))
            _current_output(root, record)
            if figure_read_state(project, selected) != witness:
                raise ValueError("The source native revision changed during standalone publication; inspect its recorded version")
            return export_projection(record, output_store, document=document, spec=Path(selected["spec"]),
                                     receipt_key="output_command")
