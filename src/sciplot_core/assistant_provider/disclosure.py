"""Project a validated local request into its explicit outbound scope."""

from __future__ import annotations

import copy
from typing import Any

from sciplot_core.assistant_provider.descriptor import AssistantProviderDescriptor
from sciplot_core.assistant_provider.request import AssistantRequest


def require_disclosure_support(request: AssistantRequest, descriptor: AssistantProviderDescriptor) -> None:
    if request.disclosure == "properties" and "properties_disclosure" not in descriptor.capabilities:
        raise ValueError("The Assistant provider does not support properties-only disclosure.")


def outbound_context(context: dict[str, Any], disclosure: str) -> dict[str, Any]:
    if disclosure == "visual":
        return copy.deepcopy(context)
    if disclosure != "properties":
        raise ValueError("Unsupported Assistant disclosure mode.")
    selection = context["selection"]
    return {
        "revision": context["revision"],
        "selected_object": copy.deepcopy(context["selected_object"]),
        "selection": {key: copy.deepcopy(selection[key]) for key in
                      ("object_ids", "primary_object_id") if key in selection},
        "editing_capabilities": copy.deepcopy(context["editing_capabilities"]),
        "raw_dataset_arrays_included": False,
        "explicit_selected_point_included": False,
    }
