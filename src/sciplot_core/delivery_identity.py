"""The non-executable delivery identity and its bounded v1 shell reader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.delivery_binding import DeliveryBinding, delivery_binding_from_payload
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.policy import DELIVERY_LAUNCHER

DELIVERY_IDENTITY = "SciPlot_delivery.json"
DELIVERY_IDENTITY_KIND = "sciplot_delivery_identity"
DELIVERY_IDENTITY_VERSION = 1



def make_delivery_binding(
    *,
    root: Path,
    manifest: dict[str, Any],
    documents: list[dict[str, Any]],
) -> DeliveryBinding | None:
    if not documents:
        return None
    logical_root = literal_source_path(root)
    baseline = tuple(
        (Path(str(item["path"])).name, str(item["delivery_sha256"]))
        for item in documents
    )
    request_value = manifest.get("request_path")
    request_path = (
        Path(request_value).expanduser().resolve()
        if isinstance(request_value, str)
        else None
    )
    source = None
    if request_path is not None and request_path.name == "plot_request.json":
        # A named canonical request is an observation, not an optional hint.
        # Preserve permission, missing-file and JSON failures instead of claiming
        # a successful ownerless package after losing the declared evidence.
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("The declared canonical plotting request must be an object.")
        delivery = request.get("delivery_output")
        if delivery is None:
            request_path = None  # This request does not bind a visible package.
        elif not isinstance(delivery, str) or not delivery.strip():
            raise ValueError("The declared delivery output must be a non-empty path.")
        elif literal_source_path(Path(delivery).expanduser()) != logical_root:
            request_path = None  # A package for another destination is portable.
        else:
            source_value = request.get("input")
            if not isinstance(source_value, str) or not source_value.strip():
                raise ValueError("The bound canonical plotting request has no source.")
            source_path = Path(source_value).expanduser()
            if not source_path.is_absolute():
                source_path = request_path.parent / source_path
            source = str(source_path.resolve())
    else:
        request_path = None
    plan = manifest.get("resolved_figure_plan")
    primary_id = plan.get("primary_figure_id") if isinstance(plan, dict) else None
    primary = next(
        (
            Path(str(item["path"])).name
            for item in documents
            if item.get("figure_id") == primary_id
        ),
        baseline[0][0],
    )
    return DeliveryBinding(
        root=logical_root,
        request=literal_source_path(request_path) if request_path else None,
        source=literal_source_path(Path(source)) if source is not None else None,
        primary=primary,
        documents=baseline,
    )


def delivery_identity_path(root: Path) -> Path:
    """Present new records own identity; malformed records never select v1."""
    current = root / DELIVERY_IDENTITY
    return current if current.exists() or current.is_symlink() else root / DELIVERY_LAUNCHER


def write_delivery_identity(root: Path, *, binding: DeliveryBinding | None) -> Path:
    """Write only to the caller's detached publication candidate."""
    path = root / DELIVERY_IDENTITY
    payload = {"kind": DELIVERY_IDENTITY_KIND, "version": DELIVERY_IDENTITY_VERSION,
               "binding": binding.to_payload() if binding is not None else None}
    path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def read_delivery_binding(root: Path) -> DeliveryBinding | None:
    path = delivery_identity_path(root)
    if path.name == DELIVERY_IDENTITY:
        from sciplot_core.project_store.runtime import projected_runtime_artifact

        # Immutable directory caches may contain identical JSON; they are source
        # views, not current visible delivery evidence or new host permissions.
        projected_runtime_artifact(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("The delivery identity must be a regular non-symlink file.")
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or set(value) != {"kind", "version", "binding"}
                or value["kind"] != DELIVERY_IDENTITY_KIND
                or type(value["version"]) is not int or value["version"] != DELIVERY_IDENTITY_VERSION):
            raise ValueError("The delivery identity record is malformed.")
        return delivery_binding_from_payload(value["binding"]) if value["binding"] is not None else None
    if path.is_symlink():
        raise ValueError("The legacy delivery identity is not a valid SciPlot launcher.")
    if not path.exists():
        return None
    # The only compatibility format is the complete known v1 shell. It is never
    # executed, granted capability or rewritten on read.
    from sciplot_core.launchers.delivery_inspection import inspect_delivery_launcher_contract
    from sciplot_core.launchers.delivery_binding import delivery_binding_from_content

    if inspect_delivery_launcher_contract(root).get("ready") is not True:
        raise ValueError("The legacy delivery identity is not a valid SciPlot launcher.")
    return delivery_binding_from_content(path.read_text(encoding="utf-8"))


def inspect_delivery_identity(root: Path) -> dict[str, object]:
    """Observe inert JSON bytes, without executing it or claiming source QA.

    An executable mode bit does not make JSON a product entry/capability; Store
    admission still binds registered member modes independently.
    """
    path = root / DELIVERY_IDENTITY
    binding = None
    error = None
    try:
        if not path.exists() and not path.is_symlink():
            raise ValueError("The delivery identity record is missing.")
        binding = read_delivery_binding(root)
    except (OSError, ValueError, UnicodeError) as exc:
        error = str(exc)
    return {"kind": DELIVERY_IDENTITY_KIND, "version": DELIVERY_IDENTITY_VERSION,
            "path": str(path), "name": path.name,
            "exists": path.is_file() and not path.is_symlink(),
            "content_sha256": existing_file_sha256(path) if path.is_file() and not path.is_symlink() else None,
            "ready": binding is not None and error is None,
            "error": error}
