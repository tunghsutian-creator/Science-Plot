"""Project workflow artifact locations without rewriting sealed scientific values."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

# These fields belong to local artifact/status contracts. Scientific models,
# requests, source declarations and native audit evidence retain their bytes.
_SEALED = frozenset({"request", "source_request", "study_model", "transform_ledger", "transform_steps",
    "publication_intent", "semantic", "source_artifacts", "source_binding", "data_mapping_application",
    "cleanup_application", "scientific_data_verification", "document_audit", "scientific_audit",
    "qa", "publication_qa"})
_PATHS = frozenset({"path", "output", "output_dir", "request_path", "document", "spec", "project_dir",
    "launcher", "veusz_launcher", "export_edited_launcher", "registry_path", "figure_set_registry",
    "generated_from", "primary_document", "preview_path", "pdf_path", "tiff_path"})
_LISTS = frozenset({"figures", "outputs", "veusz_documents", "veusz_specs", "artifacts"})


def project_workflow_result(payload: dict[str, Any], logical_path: Callable[[str], str]) -> dict[str, Any]:
    result = deepcopy(payload)

    def project(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _SEALED:
                    continue
                if key in _PATHS and isinstance(item, str):
                    value[key] = logical_path(item)
                elif key in _LISTS and isinstance(item, list):
                    value[key] = [logical_path(entry) if isinstance(entry, str) else entry for entry in item]
                    project(value[key])
                else:
                    project(item)
        elif isinstance(value, list):
            for item in value:
                project(item)

    project(result)
    # These are exported table/native/media records, not original scientific
    # source declarations. JSON round trips must not rely on shared dict aliases.
    delivery = result.get("delivery_package")
    if isinstance(delivery, dict):
        for field in ("open_in_veusz", "open_in_sciplot", "identity", "data_dir", "pdf_dir", "tiff_dir", "project_file", "editable"):
            if isinstance(delivery.get(field), str):
                delivery[field] = logical_path(delivery[field])

        def sources(rows: Any) -> None:
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and isinstance(row.get("source"), str):
                        row["source"] = logical_path(row["source"])

        for field in ("figures", "project_documents", "editable_vsz_projects", "data_csvs"):
            sources(delivery.get(field))
        for artifact in delivery.get("artifacts", []):
            if isinstance(artifact, dict) and artifact.get("id") in {
                    "plot_data_csv", "project_files", "qa_artifact_hashes_match_delivery", "editable_vsz_hash_match"}:
                sources(artifact.get("details"))

        def observation(value: Any) -> Any:
            # This subtree is produced by verify_delivery_package: file-set,
            # pairing and artifact-source match observations, not original QA,
            # scientific requests, source bindings or FigurePlan definitions.
            if isinstance(value, dict):
                return {key: observation(item) for key, item in value.items()}
            if isinstance(value, list):
                return [observation(item) for item in value]
            return logical_path(value) if isinstance(value, str) else value

        if "verification" in delivery:
            delivery["verification"] = observation(delivery["verification"])
    return result
