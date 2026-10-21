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
    membership = False
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
        if native["kind"] in {"series_display_label", "series_visibility"}:
            if native["current_value"] != previous:
                raise DocumentError("backend_binding_mismatch", "The current source series binding differs from its document property.")
            if native["kind"] == "series_display_label":
                operations.append({"op": "set_series_display_label", "sample": target["source_label"], "expected_label": previous, "label": current})
            else:
                membership = True
            native["current_value"] = current
        elif native["kind"] == "setting":
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
    if membership:
        import json
        from pathlib import Path
        from sciplot_core.studio_core.series_presentation import selected_series_order, spec_source_series_order

        spec = json.loads(Path(binding["spec"]).read_bytes())
        visible = {target["source_label"] for target in targets.values() if target.get("properties", {}).get("series.visible", {}).get("current_value") is True}
        before = selected_series_order(spec)
        after = [label for label in before if label in visible]
        after.extend(label for label in spec_source_series_order(spec) if label in visible and label not in after)
        if not after:
            raise DocumentError("invalid_series_selection", "At least one source curve must remain visible.")
        operations.append({"op": "set_series_selection", "expected_order": before, "active_order": after})
    # An invisible annotation's text/position is a document-only change. The engine may commit
    # it without a native write; callers receive that explicit distinction.
    updates = {"targets": targets}
    if operations:
        return [], [{"op": "set_style", **change} for change in changes] + operations, updates
    return changes, None, updates
