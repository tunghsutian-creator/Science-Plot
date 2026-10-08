"""Saved native and scientific byte identities, without a renderer process."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plot_document import DocumentError


def fingerprint(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "files": {path: existing_file_sha256(Path(path)) for path in binding["files"]},
        "source_trees": {path: source_tree_sha256(Path(path)) for path in binding["source_trees"]},
    }


def changed_error(message: str, paths: list[str]) -> DocumentError:
    changed = sorted(set(paths))
    issues = [{"path": "/binding/fingerprint", "constraint": "current_inputs",
               "changed_paths": changed[:16], "changed_count": len(changed)}]
    error = DocumentError("backend_changed", message, issues=issues)
    error.repair = {"action": "resolve_input_conflict", "issues": issues}
    return error


def require_current(binding: dict[str, Any]) -> None:
    expected, current = binding["fingerprint"], fingerprint(binding)
    changed = [path for group in set(expected) | set(current)
               for path in set(expected.get(group, {})) | set(current.get(group, {}))
               if expected.get(group, {}).get(path) != current.get(group, {}).get(path)]
    if changed:
        raise changed_error("Saved native state or scientific sources changed; inspect the conflict before continuing.", changed)
