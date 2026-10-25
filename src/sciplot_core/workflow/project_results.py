"""Project workflow artifact locations without rewriting sealed scientific values."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

# These fields belong to local artifact/status contracts. Scientific models,
# requests, source declarations and native audit evidence retain their bytes.
_SEALED = frozenset({"request", "source_request", "study_model", "transform_ledger", "transform_steps",
    "publication_intent", "semantic", "source_artifacts", "source_binding", "data_mapping_application",
    "cleanup_application", "scientific_data_verification", "document_audit", "scientific_audit"})
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
    # Delivery's source is an exported artifact; raw_archive.source is a
    # scientific locator and is deliberately not included in this projection.
    delivery = result.get("delivery_package")
    if isinstance(delivery, dict):
        for field in ("figures", "projects", "data"):
            for item in delivery.get(field, []):
                if isinstance(item, dict) and isinstance(item.get("source"), str):
                    item["source"] = logical_path(item["source"])
    return result
