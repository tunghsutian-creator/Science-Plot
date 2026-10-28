"""Saved native and scientific byte identities, without a renderer process."""

from pathlib import Path
from contextlib import nullcontext
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plot_document import DocumentError
from sciplot_core.project_store.errors import ProjectStoreError
from sciplot_core.project_store.runtime import project_runtime, resolve_runtime_path
from sciplot_core.project_commands.read_projections import projection_digest
from sciplot_core.source_coverage.native_file_snapshots import observed_native_document


def fingerprint(binding: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.studio_core.project_command_scope import project_store

    project = Path(binding["project"])
    context = project_runtime(project_store(project)) if (project / ".sciplot_store").exists() else nullcontext()
    with context:
        files = {}
        for path, expected in binding["files"].items():
            try:
                if path == binding["document"]:
                    with observed_native_document(["inspect-document-state", path], Path(path)):
                        files[path] = existing_file_sha256(Path(path))
                else:
                    files[path] = existing_file_sha256(resolve_runtime_path(path, expected_sha256=expected))
            except ProjectStoreError:
                files[path] = None
        projections = {read["resource"] + ":" + read["kind"] + ":" + read["key"]:
            projection_digest((project / read["resource"]).read_bytes(), kind=read["kind"], key=read["key"])
            for read in binding.get("projected_reads", [])}
        return {"files": files,
            "source_trees": {path: source_tree_sha256(Path(path)) for path in binding["source_trees"]},
            "projections": projections}


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
