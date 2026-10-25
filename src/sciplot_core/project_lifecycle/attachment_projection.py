"""Reversible metadata-only runtime paths, after the original envelope was verified."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from .attachment_index import Attachment

_PROTECTED = {"request", "normalized_command", "rollback_request", "reimport_request",
              "dataset", "datasets", "parameters", "node", "scientific_audit",
              "diff", "changes", "represented_diff", "targets", "graph"}


def derived_relative(relative: Path) -> bool:
    if relative.parts and relative.parts[0] == "archive":
        return False
    return bool(relative.parts and (relative.parts[0] in {"ir", "renders"}
        or relative.as_posix() in {"export-cache.json", "render-cache.json"} or "preview-" in "/".join(relative.parts)))


def _pairs(attachment: Attachment) -> list[tuple[Path, Path]]:
    pairs = [(attachment.origin, attachment.root), (attachment.namespace_origin, attachment.root)]
    project_origin = attachment.entry["project_origin"]
    pairs.append((Path(project_origin), attachment.store.root))
    pairs.extend((Path(origin), attachment.store.locations[key])
                 for key, origin in attachment.entry.get("resource_roots", {}).items()
                 if key and key in attachment.store.locations)
    output = attachment.entry.get("managed_output")
    if output:
        actual = attachment.output
        assert actual is not None
        pairs.insert(0, (Path(output), actual))
    return pairs


def _path(value: str, attachment: Attachment, *, storing: bool) -> str:
    if not value.startswith("/"):
        return value
    path = Path(value)
    if not storing:
        relative = attachment.relative(path)
        if relative is not None and derived_relative(relative):
            return str(attachment.cache / "state" / relative)
    elif path.is_relative_to(attachment.cache / "state"):
        return str(attachment.origin / path.relative_to(attachment.cache / "state"))
    pairs = [(after, before) for before, after in _pairs(attachment)] if storing else _pairs(attachment)
    for before, after in sorted(pairs, key=lambda pair: len(str(pair[0])), reverse=True):
        if path == before or path.is_relative_to(before):
            return str(after / path.relative_to(before))
    return value


def metadata_view(value: Any, attachment: Attachment, *, storing: bool = False, binding: bool = False) -> Any:
    if isinstance(value, str):
        return _path(value, attachment, storing=storing)
    if isinstance(value, list):
        return [metadata_view(item, attachment, storing=storing, binding=binding) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    if value.get("kind") in {"sciplot_document", "sciplot_plot_ir", "sciplot_figure_ir"} or {"id", "columns", "provenance"} <= value.keys():
        return deepcopy(value)
    result = {}
    for key, item in value.items():
        if key in {"_semantic_attachment_id", "_semantic_project_generation"}:
            continue  # Invocation capabilities are never serialized as history.
        if key in _PROTECTED:
            result[key] = deepcopy(item)
        else:
            new_key = _path(key, attachment, storing=storing) if isinstance(key, str) else key
            result[new_key] = metadata_view(item, attachment, storing=storing, binding=key in {"binding", "before_binding", "_managed_binding", "_binding"})
    if binding and not storing:
        result["_semantic_attachment_id"] = attachment.entry["id"]
    return result
