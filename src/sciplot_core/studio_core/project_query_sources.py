"""Read current source versions from admitted domain evidence, never history order."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_store.runtime import (
    ProjectSourceResolver, inspect_runtime_source_file, inspect_runtime_source_tree,
)
from sciplot_core.source_coverage.managed_documents import source_records
from sciplot_core.data_mapping.execution_inputs import mapping_effective_source


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
        fact = inspect_runtime_source_file(source, expected_sha256=files[str(source)], source_id=identities.get(str(source)))
        observed = canonical_json_sha256({"kind": "file", "content_sha256": fact.sha256}, allow_nan=False)
        if observed != canonical_json_sha256({"kind": "file", "content_sha256": files[str(source)]}, allow_nan=False):
            raise ValueError("The current file input changed from its exact admitted source version")
        return observed
    rows, roots, sealed = [], set(), []
    for literal, digest in sorted(files.items()):
        relative = Path(literal).relative_to(source).as_posix()
        fact = inspect_runtime_source_file(literal, expected_sha256=digest, source_id=identities.get(literal))
        observed = canonical_json_sha256({"kind": "file", "content_sha256": fact.sha256}, allow_nan=False)
        if observed != canonical_json_sha256({"kind": "file", "content_sha256": digest}, allow_nan=False):
            raise ValueError("A current directory input member changed from its exact admitted version")
        rows.append({"path": relative, "content_sha256": digest})
        if fact.physical is not None:
            root = fact.physical
            for _part in Path(relative).parts:
                root = root.parent
            roots.add(root)
        sealed.append(fact.physical is None)
    result = canonical_json_sha256({"kind": "directory", "files": rows}, allow_nan=False)
    if result != expected:
        raise ValueError("The current directory input lacks a complete matching source-tree version")
    if not all(sealed):
        # A live explicit input must retain its complete namespace, including no
        # newly added members. Cold views use only the exact imported file set.
        if any(sealed) or len(roots) != 1:
            raise ValueError("A current source directory has no single verified physical namespace")
        observed = inspect_runtime_source_tree(next(iter(roots)), allowed={row["path"] for row in rows})
        if observed != result:
            raise ValueError("The current input directory changed complete membership or bytes")
    return result


def current_source_digest(source: Path, files: dict[str, str], identities: dict[str, str]) -> str:
    resolver = selected_source_resolver()
    literal = resolver.literal_path(source) if isinstance(resolver, ProjectSourceResolver) else str(source)
    return inspect_runtime_source_file(literal, expected_sha256=files.get(literal), source_id=identities.get(literal)).sha256


def current_tree_digest(source: Path, files: dict[str, str], identities: dict[str, str], *,
                        mapping_application: dict[str, Any] | None = None) -> str:
    resolver = selected_source_resolver()
    literal = resolver.literal_path(source) if isinstance(resolver, ProjectSourceResolver) else str(source)
    if (mapping_application is not None and mapping_application.get("source_groups")
            and literal == mapping_application["effective_input"] and literal in files):
        composite = mapping_effective_source(mapping_application["execution"], literal)
        if composite is not None and composite[0] is None:
            if files[literal] != composite[1]:
                raise ValueError("The current composite differs from the sealed invocation observation")
            return canonical_json_sha256({"kind": "file", "content_sha256": composite[1]}, allow_nan=False)
    if literal in files:
        digest = current_source_digest(source, files, identities)
        return canonical_json_sha256({"kind": "file", "content_sha256": digest}, allow_nan=False)
    members = {path: digest for path, digest in files.items() if Path(path).is_relative_to(literal)}
    if members:
        expected = canonical_json_sha256({"kind": "directory", "files": [
            {"path": Path(path).relative_to(literal).as_posix(), "content_sha256": digest}
            for path, digest in sorted(members.items())]}, allow_nan=False)
        observed = current_source_tree(source, members, identities, expected=expected)
        if observed is None:
            raise ValueError("The verified mapping has no complete source-tree observation")
        return observed
    return inspect_runtime_source_tree(source)


def mapping_source_files(application: dict[str, Any], files: dict[str, str]) -> dict[str, str]:
    """Use the full verified loader's original and effective file inventories."""
    selected = dict(files)
    records = [(str(Path(application["source_root"]) / name), digest)
               for name, digest in application["source_hashes"].items()]
    records.extend((item["path"], item["sha256"]) for item in application["mapped_outputs"])
    for path, digest in records:
        if path in selected and selected[path] != digest:
            raise ValueError("The verified mapping and current source facts disagree")
        selected[path] = digest
    effective = application["effective_input"]
    if application.get("source_groups") and effective not in selected:
        composite = mapping_effective_source(application["execution"], effective)
        if composite is not None:
            identity, version = composite
            selected[effective] = (version if identity is None else
                inspect_runtime_source_file(effective, expected_sha256=version, source_id=identity).sha256)
    return selected


def mapping_sources_sealed(files: dict[str, str], identities: dict[str, str], figures: list[dict[str, Any]]) -> bool:
    """Only the selected exact source bindings can defer compact numeric replay."""
    selected = dict(files)
    for figure in figures:
        if figure.get("status") != "ready":
            continue
        spec = json.loads(Path(figure["spec"]).read_bytes())
        for path, digest in source_records(spec).items():
            if str(path) in selected and selected[str(path)] != digest:
                raise ValueError("Selected source facts disagree about their exact byte version")
            selected[str(path)] = digest
    facts = [inspect_runtime_source_file(path, expected_sha256=digest, source_id=identities.get(path))
             for path, digest in selected.items()]
    return any(fact.physical is None for fact in facts)
