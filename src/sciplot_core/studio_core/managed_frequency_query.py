"""Read public Managed frequency group and delivery evidence without a compiler."""

from pathlib import Path
from typing import Any

from sciplot_core.project_store.io import observe_existing_store
from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY, UserOutputLayout

from sciplot_core.project_lifecycle.figure_observation import (
    FREQUENCY_AUTHORITY, FREQUENCY_RECORD, locate_frequency_project, observe_frequency_figures,
)


def frequency_roots(layout: UserOutputLayout) -> tuple[Path, Path, Path]:
    workspace = layout.workspace_root
    return workspace / FREQUENCY_RECORD, workspace / "runs" / "run_001", workspace / FREQUENCY_AUTHORITY


def is_frequency_creation_owner(layout: UserOutputLayout, owner: str) -> bool:
    creation = read_json_object(frequency_roots(layout)[0])
    return creation is not None and creation.get("owner") == owner


def frequency_receipt(record: Path, output: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    managed = manifest["result"]["managed_frequency"]
    by_id = {item["figure_id"]: item for item in managed["figures"]}
    delivery = manifest["delivery_package"]
    package = delivery["figures"]
    docs = {item["figure_id"]: item for item in delivery["project_documents"]}
    ready = manifest["ready_to_use"] is True
    figures = [{"figure_id": item["figure_id"], "plot": by_id[item["figure_id"]]["plot"],
                "title": item["title"], "status": "ready",
                "document": docs[item["figure_id"]]["path"], "document_sha256": docs[item["figure_id"]]["delivery_sha256"],
                "exports": [{key: entry[key] for key in ("format", "path")}
                            for entry in package if entry["figure_id"] == item["figure_id"]]}
               for item in manifest["resolved_figure_plan"]["tasks"]]
    return {"kind": "sciplot_project_creation_result", "version": 1, "status": "created" if ready else "blocked",
            "project_dir": managed["project"], "request": str(record), "document": docs[managed["primary_figure_id"]]["path"],
            "primary_figure_id": managed["primary_figure_id"], "figures": figures,
            "document_authority": "managed_figure_group",
            "studio_run": {"ready_to_use": ready, "state": manifest["state"], "manifest": str(output / "manifest.json"),
                           "delivery_package": {"path": delivery["path"], "complete": delivery["complete"]},
                           "failure_stage": None if ready else "publication", "failure_reason": None if ready else
                               ", ".join(manifest["publish_gates"]["failed_gates"]) }}


def is_frequency_project_request(request: Path) -> bool:
    return request.name == "plot_request.json" and (request.parent / FREQUENCY_RECORD).is_file()


@observe_existing_store()
def inspect_frequency_creation(project: Path) -> dict[str, Any] | None:
    """Project the original publication's readiness, not the current figure catalogue."""
    observed = locate_frequency_project(project)
    if observed is None:
        return None
    project, canonical_request, creation, document = observed
    request = creation["request"]
    output = Path(request["output"])
    manifest = read_json_object(output / "manifest.json")
    if manifest is None or manifest.get("result", {}).get("managed_frequency", {}).get("project") != str(project):
        raise ValueError("The Managed frequency project is not yet delivered. Repeat the exact creation.")
    receipt = frequency_receipt(canonical_request, output, manifest)
    if document is not None:
        selected = next((item for item in receipt["figures"] if item["document"] == str(document)), None)
        if selected is None:
            raise ValueError(f"The selected VSZ is not bound to a saved figure: {document}")
        receipt["selected_figure"] = selected
    current = observe_frequency_figures(project, projection=True)
    if [(item["figure_id"], item["plot"]) for item in receipt["figures"]] != [
            (item["figure_id"], item["plot"]) for item in current.figures]:
        raise ValueError("The published figures no longer identify this Managed frequency project.")
    original = manifest["result"]["managed_frequency"]["generation"]
    source_current = source_tree_sha256(Path(request["input"])) == creation["source_sha256"]
    qa_current = (current.generation == original and current.projection_status == "current"
                  and manifest["publication_qa"]["status"] == "passed")
    delivery = verify_delivery_package(manifest["delivery_package"], expected_root=Path(request[REQUEST_DELIVERY_ROOT_KEY]),
                                       expected_manifest=manifest)
    return {**receipt, "kind": "sciplot_project_inspection", "status": "ok", "project": str(project),
            "source": {"current": source_current}, "qa": {"current": qa_current},
            "delivery": {"current": delivery["passed"] is True},
            "readiness_evaluated": True, "ready_to_use": source_current and qa_current and delivery["passed"] is True,
            "live_gui_state_evaluated": False}
