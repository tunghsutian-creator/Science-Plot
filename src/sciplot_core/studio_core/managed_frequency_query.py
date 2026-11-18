"""Read public Managed frequency group and delivery evidence without a compiler."""

from pathlib import Path
from typing import Any

from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.delivery_identity import DELIVERY_IDENTITY, read_delivery_binding
from sciplot_core.policy.render_options import DELIVERY_PROJECT_DIR
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY, UserOutputLayout
from sciplot_core.project_store import FileProjectStore

AUTHORITY = ".sciplot-frequency"
_RECORD = "frequency-creation.json"


def frequency_roots(layout: UserOutputLayout) -> tuple[Path, Path, Path]:
    workspace = layout.workspace_root
    return workspace / _RECORD, workspace / "runs" / "run_001", workspace / AUTHORITY


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
    return request.name == "plot_request.json" and (request.parent / _RECORD).is_file()


def inspect_frequency_creation(project: Path) -> dict[str, Any] | None:
    """Revalidate read-only project/delivery status without native work."""
    project = project.expanduser().resolve()
    workspace = project.parent.parent if project.parent.name == AUTHORITY else None
    visible = None
    if workspace is None:
        if project.name == "plot_request.json":
            workspace = project.parent
        elif project.is_dir() and (project / _RECORD).is_file():
            workspace = project
        else:
            visible = (project.parent.parent if project.suffix.casefold() == ".vsz" and project.parent.name == DELIVERY_PROJECT_DIR
                       else project.parent if project.name == DELIVERY_IDENTITY else project)
            if not visible.is_dir() or not (visible / DELIVERY_IDENTITY).is_file():
                return None
            binding = read_delivery_binding(visible)
            if binding is None or not binding.request:
                return None
            workspace = Path(binding.request).parent
    creation = read_json_object(workspace / _RECORD)
    if creation is None:
        return None
    request = creation["request"]
    canonical_request = workspace / "plot_request.json"
    if read_json_object(canonical_request) != request:
        raise ValueError("The saved Managed frequency plotting request changed.")
    authority = workspace / AUTHORITY / canonical_json_sha256(request)
    if ((visible is not None and visible != Path(request[REQUEST_DELIVERY_ROOT_KEY]))
            or (project.parent.name == AUTHORITY and project != authority)):
        raise ValueError("The selected frequency location does not match its exact saved project.")
    project = authority
    output = Path(request["output"])
    manifest = read_json_object(output / "manifest.json")
    if manifest is None or manifest.get("result", {}).get("managed_frequency", {}).get("project") != str(project):
        raise ValueError("The Managed frequency project is not yet delivered. Repeat the exact creation.")
    receipt = frequency_receipt(canonical_request, output, manifest)
    current = FileProjectStore(project).snapshot()
    original = manifest["result"]["managed_frequency"]["generation"]
    source_current = source_tree_sha256(Path(request["input"])) == creation["source_sha256"]
    qa_current = (current["generation"] == original and current["projection_status"] == "current"
                  and manifest["publication_qa"]["status"] == "passed")
    delivery = verify_delivery_package(manifest["delivery_package"], expected_root=Path(request[REQUEST_DELIVERY_ROOT_KEY]),
                                       expected_manifest=manifest)
    return {**receipt, "kind": "sciplot_project_inspection", "status": "ok", "project": str(project),
            "source": {"current": source_current}, "qa": {"current": qa_current},
            "delivery": {"current": delivery["passed"] is True},
            "readiness_evaluated": True, "ready_to_use": source_current and qa_current and delivery["passed"] is True,
            "live_gui_state_evaluated": False}
