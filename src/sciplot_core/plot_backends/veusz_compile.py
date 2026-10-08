"""Compile exact semantic differences to the existing native transaction API."""

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_backends.veusz_semantic_compile import annotation_change, semantic_change


def compile_diff(document: dict[str, Any], binding: dict[str, Any],
                 new_document: dict[str, Any], diff: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    annotations: dict[str, dict[str, Any]] = {}
    operations: list[dict[str, Any]] = []
    targets = deepcopy(binding["targets"])
    for item in diff:
        identifier, prop = item["target"], item["property"]
        try:
            previous = document["presentation"]["objects"][identifier]["properties"][prop]
            current = new_document["presentation"]["objects"][identifier]["properties"][prop]
            target = targets[identifier]
            native = target["properties"][prop]
        except KeyError as exc:
            raise DocumentError("backend_property_unsupported", "This property has no imported native binding.") from exc
        if previous != item["before"] or current != item["after"]:
            raise DocumentError("backend_diff_mismatch", "The semantic difference does not match its document revisions.")
        if native["kind"] == "setting":
            if native["current_value"] != previous:
                raise DocumentError("backend_binding_mismatch", "The current native setting differs from the document property.")
            changes.append({"object_path": target["object_path"], "setting_path": native["setting_path"],
                            "expected_value": native["current_value"], "value": current})
            native["current_value"] = current
        elif native["kind"] == "annotation":
            annotations[identifier] = target
        else:
            semantic_change(target, native, previous, current, changes, operations)
    for identifier, target in annotations.items():
        old = document["presentation"]["objects"][identifier]["properties"]
        new = new_document["presentation"]["objects"][identifier]["properties"]
        operations.extend(annotation_change(old, new, target))
    # An invisible annotation's text/position is a document-only change. The engine may commit
    # it without a native write; callers receive that explicit distinction.
    updates = {"targets": targets}
    if operations:
        return [], [{"op": "set_style", **change} for change in changes] + operations, updates
    return changes, None, updates
