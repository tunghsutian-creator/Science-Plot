"""Read current source versions from admitted domain evidence, never history order."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_store.runtime import ProjectSourceResolver, resolve_runtime_path
from sciplot_core.project_store.source_trees import observe
from sciplot_core.source_coverage.managed_documents import source_records


def current_source_files(project: Path, source: Path, figures: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """Return only exact input members declared by this pinned canonical revision."""
    resolver = selected_source_resolver()
    if not isinstance(resolver, ProjectSourceResolver) or resolver.store.root != project:
        return {}, {}
    store, snapshot = resolver.store, resolver.snapshot
    request = json.loads(store.read_bytes("plot_request.json", generation=resolver.generation))
    literal = resolver.literal_path(source)
    values: dict[str, set[str]] = {}
    def add(path: str, digest: str) -> None:
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ValueError("Current source evidence needs an exact literal and SHA256")
        if path == literal or Path(path).is_relative_to(literal):
            values.setdefault(path, set()).add(digest)
    if "source_update.json" in snapshot["files"]:
        review = json.loads(store.read_bytes("source_update.json", generation=resolver.generation))
        if review.get("source") == literal:
            kind, files = review.get("source_kind"), review.get("source_files")
            if kind not in {"file", "directory"} or not isinstance(files, dict):
                raise ValueError("The current source revision has no closed input kind and member inventory")
            for name, digest in files.items():
                relative = PurePosixPath(name)
                if relative.is_absolute() or str(relative) != name or any(part in {"", ".", ".."} for part in relative.parts):
                    raise ValueError("The current source revision has an invalid relative member")
                add(str(Path(literal) / name) if kind == "directory" else literal, digest)
    for step in request.get("transform_ledger", {}).get("steps", []):
        for artifact in step.get("input_artifacts", []):
            if artifact.get("kind") == "file" and artifact.get("sha256"):
                add(artifact["path"], artifact["sha256"])
    if request.get("categorical_binding", {}).get("source_sha256"):
        add(literal, request["categorical_binding"]["source_sha256"])
    for figure in figures:
        if figure.get("status") != "ready":
            continue
        actual = Path(figure["spec"])
        name = actual.relative_to(project).as_posix()
        spec = json.loads(store.read_bytes(name, generation=resolver.generation))
        for path, digest in source_records(spec).items():
            add(str(path), digest)
    if any(len(digests) != 1 for digests in values.values()):
        raise ValueError("The current canonical request and selected native source versions disagree")
    files = {path: next(iter(digests)) for path, digests in values.items()}
    identities = {}
    for path, digest in files.items():
        owners = [identity for identity, versions in snapshot["sources"].items()
                  if versions.get(digest, {}).get("locator") == path]
        if len(owners) > 1:
            raise ValueError("The current source literal/version has ambiguous registered identities")
        if owners:
            identities[path] = owners[0]
    return files, identities


def current_source_tree(source: Path, files: dict[str, str], identities: dict[str, str], *, expected: str | None) -> str | None:
    """Verify live exact versions or the cold import's explicit immutable bindings."""
    if not files:
        return None
    resolver = selected_source_resolver()
    source = Path(resolver.literal_path(source)) if isinstance(resolver, ProjectSourceResolver) else source
    if str(source) in files:
        if len(files) != 1:
            raise ValueError("A current file input cannot also declare directory members")
        actual = resolve_runtime_path(source, expected_sha256=files[str(source)], source_id=identities.get(str(source)))
        observed, _proof = observe(str(actual))
        if observed != canonical_json_sha256({"kind": "file", "content_sha256": files[str(source)]}, allow_nan=False):
            raise ValueError("The current file input changed from its exact admitted source version")
        return observed
    rows, roots, caches = [], set(), []
    for literal, digest in sorted(files.items()):
        relative = Path(literal).relative_to(source).as_posix()
        actual = resolve_runtime_path(literal, expected_sha256=digest, source_id=identities.get(literal))
        observed, _proof = observe(str(actual))
        if observed != canonical_json_sha256({"kind": "file", "content_sha256": digest}, allow_nan=False):
            raise ValueError("A current directory input member changed from its exact admitted version")
        rows.append({"path": relative, "content_sha256": digest})
        root = actual
        for _part in Path(relative).parts:
            root = root.parent
        roots.add(root)
        caches.append(isinstance(resolver, ProjectSourceResolver)
                      and actual.is_relative_to(resolver.store.root / ".sciplot_store/sources"))
    result = canonical_json_sha256({"kind": "directory", "files": rows}, allow_nan=False)
    if result != expected:
        raise ValueError("The current directory input lacks a complete matching source-tree version")
    if not all(caches):
        # A live explicit input must retain its complete namespace, including no
        # newly added members. Cold views use only the exact imported file set.
        if len(roots) != 1:
            raise ValueError("A current source directory has no single verified physical namespace")
        observed, _proof = observe(str(next(iter(roots))))
        if observed != result:
            raise ValueError("The current input directory changed complete membership or bytes")
    return result


def resolve_current_file(source: Path, files: dict[str, str], identities: dict[str, str]) -> Path:
    resolver = selected_source_resolver()
    literal = resolver.literal_path(source) if isinstance(resolver, ProjectSourceResolver) else str(source)
    return resolve_runtime_path(literal, expected_sha256=files.get(literal), source_id=identities.get(literal))
