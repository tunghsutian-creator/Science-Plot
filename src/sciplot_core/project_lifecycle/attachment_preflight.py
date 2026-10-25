"""Validate the original native baseline before moving any disposable products."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_locations import source_location_scope
from sciplot_core.project_store.locators import logical_for_literal
from .attachment_index import Attachment
from .attachment_projection import metadata_view
from .attachment_sources import AttachmentSourceResolver
from .context import repository_scope
from .frozen_namespace import FrozenNamespaceRepository
from .namespace_capture import namespace_bytes
from .errors import EngineError


@dataclass(frozen=True)
class ArtifactSnapshot:
    root: Path | None
    members: dict[str, bytes]
    modes: dict[str, int]


def preflight(backend: Any, capabilities: dict[str, Any], namespace: FrozenNamespaceRepository,
              envelope: dict[str, Any], attachment: Attachment) -> ArtifactSnapshot:
    from sciplot_core.plot_engine.current import require_current

    # Project/resource mapping is allowed, while a new disposable output owner
    # must not make an existing externally edited native document disappear.
    entry = {**attachment.entry, "managed_output": None}
    binding = metadata_view(envelope["binding"], Attachment(attachment.store, entry), binding=True)
    original = envelope["binding"]
    if original.get("kind") == "sciplot_managed_binding":
        binding["root"] = str(namespace.physical)
        for field in ("canonical_document", "ir_path"):
            binding[field] = str(namespace.physical / Path(original[field]).relative_to(namespace.origin))
        binding["scientific_content_files"] = {
            str(namespace.physical / Path(path).relative_to(namespace.origin)): sha
            for path, sha in original.get("scientific_content_files", {}).items()}
    output = Path(binding["output"]) if "output" in binding else None
    modes: dict[str, int] = {}
    artifacts = namespace_bytes(output, modes=modes) if output is not None and output.is_dir() else {}
    captured = FrozenNamespaceRepository(namespace.origin, namespace.physical, namespace.members,
        artifacts={output / name: data for name, data in artifacts.items()} if output else {},
        artifact_roots=(output,) if output else ())
    snapshot = attachment.store.snapshot()
    pending = []
    for source in envelope["document"]["scientific"]["data_sources"]:
        value = deepcopy(source)
        known = (logical_for_literal(snapshot, source["path"]) is not None
                 or any(entry.get("locator") == source["path"] for versions in snapshot["sources"].values() for entry in versions.values()))
        if known:
            value["actual"] = str(attachment.store.resolve_path(source["path"], expected_sha256=source["sha256"]))
        pending.append(value)
    with repository_scope(captured, capabilities=capabilities), source_location_scope(AttachmentSourceResolver(attachment.store, pending)):
        try:
            require_current(backend, binding)
        except ValueError:
            from .attachment_pending import applied_binding

            acknowledged = applied_binding(backend, namespace, envelope, attachment, binding)
            if acknowledged is None:
                raise
            binding = acknowledged
            require_current(backend, binding)
        if original.get("kind") == "sciplot_managed_binding" and Path(binding["document"]).exists():
            owner = backend._owner(binding) if callable(getattr(backend, "_owner", None)) else backend
            compiler = getattr(owner, "compiler", None)
            if compiler is not None:
                from sciplot_core.plot_engine.managed_state import resolved_ir

                ir = resolved_ir(namespace.physical, envelope["document"])
                inspected = compiler.inspect_ir(ir, Path(binding["document"]))
                if inspected.get("status") != "unchanged" or inspected.get("scientific_audit", {}).get("status") != "passed":
                    raise EngineError("managed_external_mutation", "The original native artifact does not exactly reproduce its sealed canonical state; preserve it before ownership transfer.")
        require_current(backend, binding)
    return ArtifactSnapshot(output, artifacts, modes)
