"""Read public Managed frequency group and delivery evidence without a compiler."""

from pathlib import Path
from typing import Any

from sciplot_core.project_store.io import observe_existing_store
from sciplot_core.delivery.package_validation import verify_delivery_package
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY, UserOutputLayout

from sciplot_core.project_lifecycle.managed_figure_observation import observe_frequency_figures
from sciplot_core.studio_core.project_query_evidence import verified_figure_exports
from sciplot_core.workflow.frequency_locations import FREQUENCY_RECORD, frequency_roots, locate_frequency_project


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
                "exports": [{"format": entry["format"], "path": entry["path"],
                             **({"sha256": entry["delivery_sha256"]} if entry.get("delivery_sha256") else {})}
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


def _recorded_group(manifest: dict[str, Any] | None, project: Path) -> dict[str, Any] | None:
    result = manifest.get("result") if manifest is not None else None
    group = result.get("managed_frequency") if isinstance(result, dict) else None
    return group if isinstance(group, dict) and group.get("project") == str(project) else None


def _inspect_selected_figure(project: Path, request_path: Path, *, figure_id: str | None,
                             document: Path | None, manifest: dict[str, Any] | None,
                             output: Path) -> dict[str, Any]:
    from sciplot_core.task_semantic_owner import inspect_managed_publication

    initial = _recorded_group(manifest, project)
    if document is not None:
        delivery = manifest.get("delivery_package") if initial is not None and manifest is not None else None
        documents = delivery.get("project_documents", []) if isinstance(delivery, dict) else []
        registered = [item["figure_id"] for item in documents
                      if isinstance(item, dict) and item.get("path") == str(document)]
        if len(registered) != 1:
            raise ValueError(f"The selected VSZ is not bound to a saved figure: {document}")
        if figure_id is not None and registered[0] != figure_id:
            raise ValueError("The requested figure ID does not match the selected delivery VSZ.")
        figure_id = registered[0]
    observed = observe_frequency_figures(project)
    member = next((item for item in observed.figures if item["figure_id"] == figure_id), None)
    if member is None:
        raise ValueError(f"Unknown figure_id: {figure_id}")

    # Membership gives the stable identity, not the current revision's export.
    # Ask only this plot's existing publication owner, even if the group is cold,
    # a sibling is damaged, or the visible group package is no longer current.
    current = inspect_managed_publication(Path(member["plot"]), plot_id=member["plot_id"])
    after = observe_frequency_figures(project)
    if (after.primary_figure_id, after.figures) != (observed.primary_figure_id, observed.figures):
        raise ValueError("The Managed frequency membership changed during inspection; query again.")
    evidence = current["export_current"]
    publication = evidence.get("publication") or {}
    ready = evidence["current"] is True and publication.get("ready_to_use") is True
    selected = {**member, **{key: current[key] for key in ("revision", "scientific_hash", "presentation_hash")},
                "document": current["artifact"], "document_sha256": publication.get("document_sha256"),
                "document_authority": "managed_model", "status": "ready" if ready else current["status"],
                "exports": publication.get("exports", []), "export_current": evidence}
    return {"kind": "sciplot_project_inspection", "version": 1, "status": "ok",
            "project": str(project), "request": str(request_path),
            "primary_figure_id": observed.primary_figure_id, "figures": observed.figures,
            "selected_figure": selected, "document_authority": "managed_figure_group",
            "publication_scope": "selected_managed_revision",
            "source": {"current": current["status"] == "current", "scope": "selected_managed_binding"},
            "qa": {"current": ready, "status": publication.get("publication_qa", {}).get("status")},
            "delivery": {"current": ready, "scope": "selected_managed_export_files", "package_included": False},
            "initial_group_publication": {"manifest": str(output / "manifest.json"),
                "recorded": initial is not None,
                "generation": initial.get("generation") if initial is not None else None,
                "recorded_ready_to_use": manifest.get("ready_to_use") if initial is not None and manifest is not None else None,
                "currentness_evaluated": False},
            "readiness_evaluated": True, "ready_to_use": ready, "live_gui_state_evaluated": False}


@observe_existing_store()
def inspect_frequency_creation(project: Path, *, figure_id: str | None = None) -> dict[str, Any] | None:
    """Keep the selected member's current publication separate from the original group."""
    observed = locate_frequency_project(project)
    if observed is None:
        return None
    project, canonical_request, creation, document = observed
    request = creation["request"]
    output = Path(request["output"])
    manifest = read_json_object(output / "manifest.json")
    if figure_id is not None or document is not None:
        return _inspect_selected_figure(project, canonical_request, figure_id=figure_id,
                                        document=document, manifest=manifest, output=output)

    initial = _recorded_group(manifest, project)
    if manifest is None or initial is None:
        raise ValueError("The Managed frequency project is not yet delivered. Repeat the exact creation.")
    receipt = frequency_receipt(canonical_request, output, manifest)
    current = observe_frequency_figures(project, projection=True)
    if [(item["figure_id"], item["plot"]) for item in receipt["figures"]] != [
            (item["figure_id"], item["plot"]) for item in current.figures]:
        raise ValueError("The published figures no longer identify this Managed frequency project.")
    source_current = source_tree_sha256(Path(request["input"])) == creation["source_sha256"]
    qa_current = (current.generation == initial["generation"] and current.projection_status == "current"
                  and manifest["publication_qa"]["status"] == "passed")
    delivery = verify_delivery_package(manifest["delivery_package"], expected_root=Path(request[REQUEST_DELIVERY_ROOT_KEY]),
                                       expected_manifest=manifest)
    delivery_current = delivery["passed"] is True
    publication = {"manifest": receipt["studio_run"]["manifest"],
                   "figures": verified_figure_exports(receipt["figures"], manifest["delivery_package"])}
    return {**receipt, "kind": "sciplot_project_inspection", "status": "ok", "project": str(project),
            "publication_scope": "initial_managed_group_delivery",
            "source": {"current": source_current}, "qa": {"current": qa_current},
            "delivery": {"current": delivery_current,
                         **({"publication": publication} if source_current and qa_current and delivery_current else {})},
            "readiness_evaluated": True, "ready_to_use": source_current and qa_current and delivery["passed"] is True,
            "live_gui_state_evaluated": False}
