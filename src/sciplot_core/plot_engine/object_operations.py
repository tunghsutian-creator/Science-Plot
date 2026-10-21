"""Object-level operation availability without changing either authority or state."""

from copy import deepcopy
from typing import Any


def _has_edits(result: dict[str, Any], document: dict[str, Any] | None) -> bool:
    if document is not None:
        from sciplot_core.plot_ir.figure_document import figure_spec, is_figure

        if is_figure(document):
            from .figure_updates import figure_property_names

            return any(figure_property_names(figure_spec(document)).values())
        return any(item.get("capabilities") for item in document["presentation"]["objects"].values())
    return (any(item.get("properties") for item in result.get("edit_targets", {}).values())
            or any(result.get("figure_edit_contract", {}).values())
            or any(result.get("object_edit_contract", {}).values())
            or any(item.get("capabilities") for item in result.get("objects", {}).values()))


def _availability(result: dict[str, Any], *, exporting: bool = False) -> dict[str, Any]:
    if result.get("changed_inputs") or result.get("status") == "stale":
        return {"available": False, "reason_code": "document_inputs_changed"}
    pending = result.get("pending")
    if pending and not (exporting and pending.get("phase") in {"committed", "exporting", "export_pending"}):
        return {"available": False, "reason_code": "document_transaction_pending"}
    if result.get("status") not in {"current", "dirty", "complete", "ready"}:
        return {"available": False, "reason_code": "object_not_current"}
    return {"available": True}


def attach_object_operations(result: dict[str, Any], document: dict[str, Any] | None = None, *,
                             revision_semantics: str = "monotonic",
                             edit_scope_supported: bool | None = None) -> dict[str, Any]:
    """Advertise supported operations separately from temporary currentness guards.

    Properties come only from the represented current object. This does not infer
    native coverage from a rule, layout name, or the existence of a VSZ file.
    """
    editable = _has_edits(result, document)
    if edit_scope_supported is None:
        edit_scope_supported = result.get("plot_type") == "ManagedPlot"
    patch = {"supported": editable, **_availability(result)}
    if not editable:
        patch.update(available=False, reason_code="object_no_editable_targets")
    return {**result, "object_operations": {
        "version": 1, "scope": "single_figure", "authority": deepcopy(result["authority"]),
        "revision_semantics": revision_semantics,
        "describe": {"supported": True, "available": True,
                     "description_optional": True,
                     "scopes": ["summary", *(["edit"] if edit_scope_supported else [])]},
        "patch": patch, "export": {"supported": True, **_availability(result, exporting=True)},
    }}


def plot_object_handle(result: dict[str, Any], *, document: dict[str, Any] | None = None,
                       authority: dict[str, Any] | None = None,
                       revision_semantics: str = "monotonic",
                       edit_scope_supported: bool | None = None) -> dict[str, Any]:
    """Project an already validated creation result without inspection or rendering.

    Creation owners supply their in-memory canonical document or creation-audited
    edit targets. A handle never obtains native coverage merely from a file path.
    """
    metadata = {**result}
    if authority is not None:
        metadata["authority"] = authority
    if document is not None:
        metadata["plot_type"] = document.get("plot_type", "LegacyPlot")
    if "object_operations" not in metadata:
        metadata = attach_object_operations(metadata, document, revision_semantics=revision_semantics,
                                            edit_scope_supported=edit_scope_supported)
    handle = {key: deepcopy(metadata[key]) for key in
              ("plot", "plot_id", "revision", "plot_type", "authority", "object_operations")}
    handle["next_step"] = {"action": "plot.describe", "plot": handle["plot"], "description": {"scope": "summary"}}
    return handle
