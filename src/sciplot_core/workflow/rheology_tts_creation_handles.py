"""Cheap continuation handles from an already audited prepared creation."""

from typing import Any


def created_object_handles(manifest: dict[str, Any], compiled: dict[str, Any]) -> list[dict[str, Any]]:
    from sciplot_core.plot_engine.object_operations import plot_object_handle
    from sciplot_core.workflow.native_suite_objects import native_identity, native_targets

    from sciplot_core.workflow.rheology_tts_suite import _active_receipts
    receipts = {item["id"]: item for item in _active_receipts(manifest)}
    figures = {item["id"]: item for item in compiled["figures"]}
    handles = []
    for document in manifest["documents"]:
        identifier = document["id"]
        receipt = receipts[identifier]
        from sciplot_core.workflow.native_suite_runtime import native_path
        metadata = {"status": "ready", "plot": str(native_path(manifest, document)), "plot_type": "LegacyPlot",
                    "authority": {"kind": "native_suite", "visual": "saved_vsz", "semantic_adoption": False},
                    "edit_targets": native_targets(figures[identifier]),
                    **native_identity(manifest["workspace"], identifier, manifest["sources"],
                                      receipt["spec_sha256"], document["sha256"])}
        handles.append({"figure_id": identifier, **plot_object_handle(
            metadata, revision_semantics="content_bound", edit_scope_supported=True)})
    return handles
