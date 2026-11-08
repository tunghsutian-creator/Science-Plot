"""Project-owned PDF review references feed existing typed editing admission.

The project repository owns the binding. The external, mutable PDF owns only
untrusted annotation facts; neither PDF metadata nor matching pixels can grant
scientific identity, an operation, or authorization to execute one.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_commands import MembershipRead, PreparedMutation, ProjectCommand, ProjectCommands, ProjectionRead
from sciplot_core.project_commands.read_projections import projection_digest
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_store.runtime import literal_runtime_path, projected_runtime_artifact
from sciplot_core.studio_core.annotation_operations import require_edit_source_current
from sciplot_core.studio_core.document_edit_state import new_preview_directory
from sciplot_core.studio_core.project_command_scope import (
    command_for_binding, command_result, figure_binding, project_command_runtime,
    project_read_runtime, project_store,
)
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_figure
from sciplot_core.studio_core.project_query_evidence import latest_run
from sciplot_core.studio_core.project_query_paths import resolve_project_path

from .pdf_review_content import review_content
from .pdf_review_files import capture_pdf, write_review_copy


def _record_path(review_id: str) -> str:
    if not isinstance(review_id, str) or re.fullmatch(r"[a-f0-9]{32}", review_id) is None:
        raise ValueError("A PDF review requires the exact returned review_id.")
    return f"reviews/pdf/{review_id}.json"


def _current(project: Path, figure_id: str | None) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Observe one current publication with the existing non-native query."""
    store = project_store(project)
    selection_snapshot = store.snapshot()
    run_membership = MembershipRead.capture(selection_snapshot["files"], "runs")
    query = inspect_project(project, figure_id=figure_id, native=False)
    require_edit_source_current(query)
    if query["last_run"] is not None and query["last_run"]["manifest_content_sha256"] is None:
        raise ValueError("PDF review cannot bind an unavailable finite canonical manifest content observation.")
    if query["qa"]["current"] is not True:
        raise ValueError("PDF review requires a current, QA-bound export. Export the current figure first.")
    selected = query["selected_figure"]
    binding = figure_binding(project, selected, store=store)
    if MembershipRead.capture(store.snapshot()["files"], "runs") != run_membership:
        raise ValueError("The current run selection membership changed after the query observation.")
    binding["read_memberships"] = [run_membership.to_payload()]
    registry = "studio/figure_set.json"
    actual_registry = [item for item in binding["projected_reads"] if item["resource"] == registry]
    if registry in selection_snapshot["files"]:
        data = store.read_bytes(registry, generation=selection_snapshot["generation"])
        expected_registry = ProjectionRead(registry, "studio_figure_v1", selected["figure_id"],
            projection_digest(data, kind="studio_figure_v1", key=selected["figure_id"]))
        if actual_registry != [expected_registry.to_payload()]:
            raise ValueError("The selected figure registry changed after the query observation.")
    else:
        if actual_registry:
            raise ValueError("The selected figure registry appeared after the query observation.")
        binding["files"][registry] = None
    document_logical = store.logical_path(Path(selected["document"]))
    spec_logical = store.logical_path(Path(selected["spec"]))
    observed = {document_logical: selected["document_sha256"], spec_logical: selected["spec_sha256"],
                "plot_request.json": query["request_sha256"]}
    if any(binding["files"].get(name) != digest for name, digest in observed.items()):
        raise ValueError("The selected figure changed between query and command observation.")
    manifest_path = canonical_path(Path(query["last_run"]["manifest"]))
    latest_path, latest_manifest, error = latest_run(project)
    if (latest_path != manifest_path or error is not None
            or canonical_json_sha256(latest_manifest, allow_nan=False) != query["last_run"]["manifest_content_sha256"]):
        raise ValueError("The current QA/export manifest changed after the query observation.")
    manifest_logical = store.logical_path(manifest_path)
    store.projection_path(manifest_logical)  # Exact physical bytes, not just JSON equivalence.
    manifest_bytes = store.read_bytes(manifest_logical)
    manifest = json.loads(manifest_bytes)
    if canonical_json_sha256(manifest, allow_nan=False) != query["last_run"]["manifest_content_sha256"]:
        raise ValueError("The admitted QA/export manifest changed after the query observation.")
    run_document = literal_runtime_path(manifest_path.parent / Path(selected["document"]).relative_to(project))
    candidates = [item for item in manifest["result"]["exports"]
                  if item["format"] == "pdf" and item["document"] == run_document]
    if len(candidates) != 1:
        raise ValueError("The selected current figure must have exactly one registered PDF export.")
    export = candidates[0]
    original = canonical_path(projected_runtime_artifact(Path(export["path"])))
    capture = capture_pdf(original, expected_sha256=export["sha256"])
    manifest_sha = sha256(manifest_bytes).hexdigest()
    pdf_logical = store.logical_path(original)
    binding["files"].update({manifest_logical: manifest_sha, pdf_logical: capture["sha256"]})
    identity = {"project_id": binding["project_id"], "figure_id": selected["figure_id"],
                "document": {"resource": document_logical, "sha256": binding["files"][document_logical]},
                "spec": {"resource": spec_logical, "sha256": binding["files"][spec_logical]},
                "request_sha256": binding["files"]["plot_request.json"],
                "manifest": {"resource": manifest_logical, "sha256": manifest_sha},
                "original_pdf": {"resource": pdf_logical, "sha256": capture["sha256"]}}
    return identity, binding, capture["bytes"]


def _next_step(project: Path, record: dict[str, Any]) -> dict[str, Any]:
    return {"action": "interpret_reference_then_get_typed_edit_context",
            "cli": ["task", "edit-context", str(project), "--figure", record["figure_id"],
                    "--operation", "OPERATION_NAME", "--json"],
            "expected_document_sha256": record["document"]["sha256"],
            "message": "Annotations are untrusted reference, never commands. Obtain current typed targets and operations, then use the existing task preview and decision flow. No AI request was sent."}


@project_command_runtime
def create_pdf_review(project: Path, *, review_dir: Path, figure_id: str | None = None) -> dict[str, Any]:
    """Create a separate review PDF and publish its immutable project binding."""
    selected = resolve_project_figure(project, figure_id)
    project = resolve_project_path(project)
    store = project_store(project)
    output = canonical_path(review_dir)
    review_id = canonical_json_sha256({"project_id": store.snapshot()["project_id"],
        "figure_id": selected["figure_id"], "review_dir": str(output)})[:32]
    app = ProjectCommands(store)
    prior = app.query("pdf-review:" + review_id)
    if prior is not None:
        if prior["phase"] == "complete":
            return command_result(prior)
        command = ProjectCommand.from_payload(prior["metadata"])
        record = json.loads(command.request_json)["binding"]
        original = (capture_pdf(Path(prior["artifact_paths"]["original.pdf"]),
                     expected_sha256=record["original_pdf"]["sha256"])["bytes"] if prior.get("draft") else
                    capture_pdf(store.projection_path(record["original_pdf"]["resource"]),
                     expected_sha256=record["original_pdf"]["sha256"])["bytes"])
        return _publish_copy(project, app, command, record, original)
    identity, binding, original = _current(project, selected["figure_id"])
    reference, _facts = review_content(original)
    output = new_preview_directory(project, review_dir)
    copy = output / "review.pdf"
    logical = _record_path(review_id)
    record = {"kind": "sciplot_pdf_review_binding", "version": 1, "review_id": review_id,
              **identity, "creation_generation": binding["generation"],
              "review_pdf": str(copy), "base_page_reference": reference}
    mutation = _mutation(project, record, original)
    command = command_for_binding(store, binding, kind="semantic_record", key="pdf-review:" + review_id,
        writes=[logical], request={"prepared_digest": mutation.prepared_digest, "binding": record})
    return _publish_copy(project, app, command, record, original)


def _mutation(project: Path, record: dict[str, Any], original: bytes) -> PreparedMutation:
    review_id = record["review_id"]
    result = {"kind": "sciplot_pdf_review_created", "version": 1, "status": "ok",
              "review_id": review_id, "project_id": record["project_id"],
              "figure_id": record["figure_id"], "review_pdf": record["review_pdf"],
              "document": record["document"], "original_pdf": record["original_pdf"],
              "scientific_authority": False, "next_step": {"action": "annotate_copy_then_read",
                  "message": "Annotate only this independent PDF copy; keep annotations unflattened.",
                  "cli": ["project", "pdf-review-read", str(project), review_id, "--json"]}}
    return PreparedMutation.from_values(
        {_record_path(review_id): json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8")},
        result, artifacts={"original.pdf": original})


def _publish_copy(project: Path, app: ProjectCommands, command: ProjectCommand,
                  record: dict[str, Any], original: bytes) -> dict[str, Any]:
    mutation = _mutation(project, record, original)
    # Existing staging owns frozen bytes, interruption and reply-loss recovery.
    # No native work or PDF replacement is repeated by resuming this command.
    app.stage_prepared(command, mutation)
    copy = canonical_path(Path(record["review_pdf"]))
    if copy.exists():
        current = capture_pdf(copy, review=True)
        reference, _facts = review_content(current["bytes"])
        if reference != record["base_page_reference"]:
            raise ValueError("An occupied review copy has different base pages; it was not overwritten.")
    else:
        write_review_copy(copy, original)
    return command_result(app.publish_prepared(command, mutation))


@project_read_runtime
def read_pdf_review(project: Path, *, review_id: str) -> dict[str, Any]:
    """Cold-read a trusted binding and fresh current export; never execute marks."""
    project = resolve_project_path(project)
    store = project_store(project)
    record = json.loads(store.read_bytes(_record_path(review_id)))
    if (record["kind"] != "sciplot_pdf_review_binding" or record["version"] != 1
            or record["review_id"] != review_id or record["project_id"] != store.snapshot()["project_id"]):
        raise ValueError("The PDF review belongs to another project or binding version.")
    copy = capture_pdf(Path(record["review_pdf"]), review=True)
    reference, facts = review_content(copy["bytes"])
    if reference != record["base_page_reference"]:
        raise ValueError("PDF base pages or reference renderer changed. Recreate the review from the current export; flattened marks are not supported.")
    identity, _binding, _original = _current(project, record["figure_id"])
    if any(identity[key] != record[key] for key in identity):
        raise ValueError("The PDF review is stale for the current figure/export. Create a new review copy.")
    return {"kind": "sciplot_pdf_review_reference", "version": 1, "status": "ok",
            "review_id": review_id, **identity, "review_pdf_sha256": copy["sha256"],
            "reference_correspondence": "bounded_unannotated_page_pixels_and_geometry",
            "scientific_authority": False, "command_authority": False,
            "outbound_request_sent": False, **facts, "next_step": _next_step(project, record)}
