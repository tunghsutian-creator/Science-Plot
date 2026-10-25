"""Route bound native figures through the public plot spine, without importing them."""

from pathlib import Path
from typing import Any

from .errors import EngineError
from .object_operations import attach_object_operations


def native_dispatch(operation: str, target: Path, *, figure_id: str | None = None,
                    description: dict[str, Any] | None = None,
                    request: dict[str, Any] | None = None) -> dict[str, Any] | None:
    # Existing canonical stores keep their semantic or legacy revision authority.
    if (target / "head.json").is_file():
        return None
    from sciplot_core.workflow import native_suite_operations as owner

    resolved = owner.resolve_native_object(target, figure_id, repair=operation != "describe")
    if resolved is None:
        return None
    if not isinstance(resolved.get("plot"), str):
        raise EngineError("native_object_resolution_invalid", "The native owner did not return a bound figure target.")
    plot = Path(resolved["plot"])
    if operation == "describe":
        result = owner.describe_native_object(plot, description=description)
        return attach_object_operations(result, revision_semantics="content_bound", edit_scope_supported=True)
    if operation == "export":
        return dict(owner.export_native_object(plot))
    if request is None:
        raise EngineError("native_object_request_missing", "This native operation requires its existing plot request.")
    if operation == "patch":
        return dict(owner.patch_native_object(plot, request))
    if operation == "decide":
        return dict(owner.decide_native_object(plot, request))
    if operation == "resume":
        return dict(owner.resume_native_object(plot, request))
    raise EngineError("native_object_operation_unsupported", "This native object does not advertise that operation.")
