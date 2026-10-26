"""Complete confirmed-mapping directories and their real committed tree authors."""
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import resolve_source_path, selected_source_resolver
from sciplot_core.project_commands import SourceTreeRead, InputRead
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.sealed_source_trees import SealedSourceTree
from sciplot_core.project_store.source_resolver import ProjectSourceResolver
from sciplot_core.data_mapping.execution_inputs import (
    _READ_SET, _registered, mapping_literal, mapping_file_path, mapping_read_json,
    mapping_input_reads, mapping_execution_is_sealed,
    mapping_imported_execution, mapping_execution_path, MappingInputReadSet,
)

def _tree_authors(selected: ProjectSourceResolver, execution: str, trees: list[SourceTreeRead]) -> dict[str, SealedSourceTree]:
    """Find an actual complete tree certification in one checked history."""
    from sciplot_core.project_store import commands, state

    identity, version, _mode = _registered(execution, None)
    if identity is None or version is None:
        raise ProjectConflict("A cold mapping directory lacks its registered execution version.")
    result: dict[str, SealedSourceTree] = {}
    with selected.store._checked_locked() as (io, current, checked):
        cursor = checked.reachable(io, current, selected.generation)
        while True:
            parent = checked.reachable(io, current, cursor["parent"]) if cursor.get("parent") else None
            previous = parent["commands"] if parent is not None else {}
            for key, outcome in cursor["commands"].items():
                supplied = [tree for tree in trees if tree.to_payload() in outcome["metadata"].get("source_trees", [])]
                if key in previous or not supplied:
                    continue
                record = state.command(io, key, outcome["command_digest"])
                if record is None:
                    raise ProjectConflict("The mapping tree's committed author is missing.")
                draft = state.sealed_draft(io, record)
                entry = draft.get("sources", {}).get(identity, {}).get(version)
                if entry is None or entry.get("locator") != execution or entry["sha256"] != version:
                    continue
                public = commands.public(io, record, checked=checked)
                if public["phase"] == "complete" and public["generation"] == cursor["generation"]:
                    result.update({tree.locator: SealedSourceTree(key, outcome["command_digest"], public["decision_id"], tree)
                                   for tree in supplied})
            if parent is None:
                break
            cursor = parent
    if set(result) != {tree.locator for tree in trees}:
        raise ProjectConflict("The imported mapping lacks a complete directory witness; live reconfirmation is required.")
    return result


def mapping_directory_path(execution: dict[str, Any]) -> Path:
    """Resolve execution.data_dir using its complete verified output set."""
    from sciplot_core.project_store.source_tree_io import observe

    root = mapping_literal(Path(execution["data_dir"]))
    names = {str(mapping_literal(Path(item["path"])).relative_to(root)): item["sha256"]
             for item in execution["outputs"]}
    if not names or any("/" in name or name in {".", ".."} for name in names):
        raise ProjectConflict("A mapping directory requires its complete direct output inventory.")
    version = canonical_json_sha256({"kind": "directory", "files": [
        {"path": name, "content_sha256": value} for name, value in sorted(names.items())]}, allow_nan=False)
    tree = SourceTreeRead(str(root), version)
    active = _READ_SET.get()
    reference = str(mapping_literal(Path(execution["output_root"]) / "execution.json"))
    selected = selected_source_resolver()
    if isinstance(selected, ProjectSourceResolver) and mapping_imported_execution(reference):
        binding = active.sealed_trees.get(str(root)) if active is not None else None
        binding = binding or _tree_authors(selected, reference, [tree])[tree.locator]
        actual = binding.view(selected.store)
        if active is not None:
            active.sealed_trees[str(root)] = binding
    else:
        # A finite file cap proves these exact actual members. When they share
        # this one complete namespace, inspect it directly instead of creating
        # a source directory cache during an otherwise readonly replay.
        paths = {name: mapping_file_path(root / name, expected_sha256=expected) for name, expected in names.items()}
        parents = {path.parent for path in paths.values()}
        actual = (next(iter(parents)) if len(parents) == 1 and all(path.name == name for name, path in paths.items())
                  else canonical_path(resolve_source_path(root)))
    actual_version, _observed = observe(str(actual), allowed=set(names))
    if actual_version != version:
        raise ProjectConflict("The complete mapping directory changed members or content hashes.")
    for name, expected in names.items():
        mapping_file_path(root / name, expected_sha256=expected)
    if active is not None:
        active.trees[str(root)] = tree
        active.tree_actuals[str(root)] = actual
    return actual


def mapping_execution_trees(reference: str) -> tuple[SealedSourceTree, ...]:
    """Compose the existing sealed-tree port before downstream table IO."""
    if not mapping_execution_is_sealed(reference):
        return ()
    execution = mapping_read_json(mapping_execution_path(reference))
    if execution.get("effective_input") != execution.get("data_dir"):
        return ()
    selected = selected_source_resolver()
    assert isinstance(selected, ProjectSourceResolver)
    with mapping_input_reads(reference) as active:
        assert active is not None
        mapping_directory_path(execution)
        return tuple(active.sealed_trees.values())


def mapping_live_trees(readset: MappingInputReadSet) -> tuple[SourceTreeRead, ...]:
    """Cold inputs retain immutable certification, never claim a fresh original host observation."""
    trees = [readset.trees[name] for name in sorted(readset.trees)]
    selected = selected_source_resolver()
    if not isinstance(selected, ProjectSourceResolver) or not mapping_imported_execution(readset.execution):
        return tuple(trees)
    bindings = _tree_authors(selected, readset.execution, trees)
    for binding in bindings.values():
        binding.view(selected.store)  # Validate the exact complete imported proof, not merely the source cache.
    readset.sealed_trees.update(bindings)
    readset.require_current()
    return ()


def mapping_tree_sources(reference: str) -> list[Any]:
    """File versions within the explicit complete data_dir witness."""
    from sciplot_core.project_store.incoming_sources import SourceExpectation

    if not mapping_imported_execution(reference):
        return []
    execution = mapping_read_json(mapping_execution_path(reference))
    if execution.get("effective_input") != execution.get("data_dir"):
        return []
    result = []
    for output in execution["outputs"]:
        literal = str(mapping_literal(Path(output["path"])))
        identity, version, _mode = _registered(literal, output["sha256"])
        if identity is None or version is None:
            raise ProjectConflict("The complete mapping tree lacks an exact output source version.")
        result.append(SourceExpectation(literal, identity, version))
    return result


def mapping_tree_reads(readsets: Iterable[MappingInputReadSet], baseline: tuple[SourceTreeRead, ...]) -> tuple[SourceTreeRead, ...]:
    result = {item.locator: item for item in baseline}
    for readset in readsets:
        for item in mapping_live_trees(readset):
            if item.locator in result and result[item.locator] != item:
                raise ProjectConflict("A private preparation observed different mapping directory versions.")
            result[item.locator] = item
    return tuple(result[name] for name in sorted(result))


def mapping_immutable_reads(snapshot: dict[str, Any], readsets: Iterable[MappingInputReadSet],
                            baseline: tuple[InputRead, ...]) -> tuple[InputRead, ...]:
    result = {item.resource: item for item in baseline}
    for readset in readsets:
        for item in readset.input_reads(snapshot):
            if item.resource in result and result[item.resource] != item:
                raise ProjectConflict("A private preparation has conflicting metadata input identities.")
            result[item.resource] = item
    return tuple(result[name] for name in sorted(result))


