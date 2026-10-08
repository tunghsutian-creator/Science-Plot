"""Backend-neutral negotiated capability checks, never renderer imports."""
from typing import Any

from sciplot_core.plot_document.errors import fail


def require_capabilities(spec: dict[str, Any], capabilities: dict[str, Any]) -> None:
    marks = {mark["type"] for view in spec["views"] for layer in view["layers"] for mark in layer["marks"]}
    unsupported = sorted(marks - set(capabilities.get("marks", [])))
    unsupported += ["scale:" + name for name in sorted({scale["transform"] for scale in spec["scales"]}
                   - set(capabilities.get("scale_transforms", [])))]
    if len(spec["views"]) > 1 and not capabilities.get("multi_view", False):
        unsupported.append("multi_view")
    if any(any(len({layer[axis + "_scale"] for layer in view["layers"]}) > 1 for axis in ("x", "y")) for view in spec["views"]):
        if not capabilities.get("multiple_scales", False):
            unsupported.append("multiple_scales")
    if unsupported:
        fail("figure_backend_unsupported", "The selected backend cannot lower all requested grammar features.",
            "/figure_spec", "backend_capability", unsupported=unsupported)
