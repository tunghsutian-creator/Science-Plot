"""Bind ordinary current preparation to exact admitted source versions once."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
from typing import Any

from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.performance_comparison.selection import selected_performance_source_errors
from sciplot_core.project_commands.resources import SourceTreeRead
from sciplot_core.project_store.incoming_sources import SourceExpectation, selected_expectations
from sciplot_core.project_store.locators import logical_for_literal
from sciplot_core.project_store.runtime import incoming_source_runtime, project_runtime, sealed_source_runtime
from sciplot_core.project_store.sealed_source_trees import SealedSourceTree
from sciplot_core.studio_core.project_query_sources import current_source_files, current_source_tree


def _current_tree_command(store: FileProjectStore, snapshot: dict[str, Any], tree: SourceTreeRead) -> tuple[str, str, str, SourceTreeRead]:
    """Follow generation writes to the current review's actual committed author."""
    from sciplot_core.project_store import commands, state
    from sciplot_core.project_store.io import digest

    with store._locked() as (io, head):
        cursor = state.reachable(io, head, snapshot["generation"])
        entry = cursor["files"].get("source_update.json")
        if cursor["project_id"] != snapshot["project_id"] or entry is None:
            raise ProjectConflict("The current source directory has no admitted review author.")
        while True:
            parent = state.generation(io, cursor["parent"]) if cursor.get("parent") else None
            if parent is not None and (cursor["parent_sha256"] != digest(parent)
                    or cursor["project_id"] != parent["project_id"] or cursor["sequence"] != parent["sequence"] + 1):
                raise ProjectConflict("The current source review has an invalid generation parent chain.")
            previous = parent["commands"] if parent is not None else {}
            added = [value for key, value in cursor["commands"].items() if previous.get(key) != value]
            if any(value["generation"] != cursor["generation"] or value["command_id"] in previous for value in added):
                raise ProjectConflict("The current source review has changed committed command identities.")
            writers = [value for value in added if "source_update.json" in value.get("write_set", [])]
            if writers:
                if len(writers) != 1:
                    raise ProjectConflict("The current source review has multiple authors in one generation.")
                outcome = writers[0]
                record = state.command(io, outcome["command_id"], outcome["command_digest"])
                if record is None:
                    raise ProjectConflict("The current source review's admitted command receipt is missing.")
                record = commands.public(io, record)
                written = record.get("draft", {}).get("writes", {}).get("source_update.json")
                if (record.get("phase") != "complete" or record["generation"] != cursor["generation"]
                        or record["project_id"] != cursor["project_id"]
                        or record["metadata"] != outcome["metadata"]
                        or record.get("decision_id") != outcome.get("candidate_digest")
                        or outcome["metadata"].get("kind") != "source_update"
                        or tree.to_payload() not in outcome["metadata"].get("source_trees", [])
                        or written is None or any(written.get(key) != entry.get(key) for key in ("sha256", "size", "mode"))):
                    raise ProjectConflict("The current source review author lacks its exact complete tree binding.")
                return record["command_id"], record["command_digest"], record["decision_id"], tree
            if parent is None or cursor["files"].get("source_update.json") != parent["files"].get("source_update.json"):
                raise ProjectConflict("The current source review lacks a committed exact write authority.")
            cursor = parent


def _current_external_scope(store: FileProjectStore, snapshot: dict[str, Any],
                            expectations: list[SourceExpectation]) -> str:
    with store._locked() as (io, _current):
        local = io.read("local_sources.json")
    if local is None:
        return "incoming"
    versions = local.get("versions")
    if not isinstance(versions, dict) or any(
            not isinstance(versions.get(item.source_id), dict) or versions[item.source_id].get(item.sha256)
            != snapshot["sources"][item.source_id][item.sha256]["sha256"] for item in expectations):
        raise ProjectConflict("Explicit local sources do not bind this exact current canonical source version.")
    return "sealed"


@contextmanager
def current_preparation_runtime(store: FileProjectStore, snapshot: dict[str, Any]) -> Iterator[Callable[[], None]]:
    """Select current evidence, never the newest historical version or cache.

    The primary spec is part of this canonical request. Archived or independent
    figures cannot add another version to its ordinary input capability.
    """
    generation = snapshot["generation"]
    request = json.loads(store.read_bytes("plot_request.json", generation=generation))
    with selected_performance_source_errors(request, base_dir=store.root), project_runtime(store, generation=generation) as resolver:
        value = request.get("input")
        source = Path(value).expanduser() if isinstance(value, str) and value else None
        if source is not None and not source.is_absolute():
            source = store.root / source
        literal = resolver.literal_path(source) if source is not None else None
        known_external = any(isinstance(entry.get("locator"), str)
            and (entry["locator"] == literal or literal is not None and Path(entry["locator"]).is_relative_to(literal))
            and logical_for_literal(snapshot, entry["locator"]) is None
            for versions in snapshot["sources"].values() for entry in versions.values())
        figures = ([{"status": "ready", "spec": str(store.root / "studio/spec.json")}]
                   if "studio/spec.json" in snapshot["files"] else [])
        files, identities = (current_source_files(store.root, source, figures)
                             if source is not None and known_external else ({}, {}))
        expectations = [SourceExpectation(literal, identities[literal], digest) for literal, digest in files.items()
                        if literal in identities and logical_for_literal(snapshot, literal) is None]
        from sciplot_core.data_mapping.execution_directories import mapping_execution_trees, mapping_tree_sources
        from sciplot_core.data_mapping.execution_inputs import mapping_input_reads, _registered
        from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution

        mapping = request.get("data_mapping_execution")
        trees = list(mapping_execution_trees(mapping)) if isinstance(mapping, str) and mapping else []
        if trees:
            selected_files = {item.literal: item for item in expectations}
            selected_files.update({item.literal: item for item in mapping_tree_sources(mapping)})
            expectations = list(selected_files.values())
        if isinstance(mapping, str) and mapping:
            # Downstream source adapters sometimes ask for the selected table
            # without repeating its SHA. Bind only the complete canonical
            # execution that was just numerically verified, never a latest source.
            initial_mode = _current_external_scope(store, snapshot, expectations) if expectations else "incoming"
            initial_scope = (nullcontext() if selected_expectations(snapshot) is not None or not (expectations or trees) else
                             sealed_source_runtime(store, expectations, generation=generation, trees=trees)
                             if initial_mode == "sealed" or trees else incoming_source_runtime(store, expectations, generation=generation))
            with initial_scope, mapping_input_reads(mapping) as mapped_reads:
                assert mapped_reads is not None
                load_data_mapping_execution(mapped_reads.execution)
                known = {item.literal: item for item in expectations}
                for path, captured in mapped_reads.files.items():
                    identity, version, _mode = _registered(path, captured.sha256)
                    if identity is not None and version is not None and logical_for_literal(snapshot, path) is None:
                        expected_file = SourceExpectation(path, identity, version)
                        if path in known and known[path] != expected_file:
                            raise ProjectConflict("The canonical mapping and current source versions disagree.")
                        known[path] = expected_file
                expectations = list(known.values())
        mode = _current_external_scope(store, snapshot, expectations) if expectations else "incoming"
        if trees:
            mode = "sealed"
        if source is not None and files and literal not in files:
            expected = (request.get("resolved_figure_plan") or {}).get("source_sha256")
            if not isinstance(expected, str):
                raise ProjectConflict("The current source directory lacks its explicit complete composite version.")
            trees.append(SealedSourceTree(*_current_tree_command(store, snapshot, SourceTreeRead(str(literal), expected))))
        existing = selected_expectations(snapshot)
        if existing is not None and expectations:
            wanted = {(item.literal, item.source_id, item.sha256) for item in expectations}
            supplied = {(item["literal"], item["source_id"], item["sha256"]) for item in existing["sources"]}
            if (existing["mode"] != mode or supplied != wanted
                    or existing.get("trees", []) != [item.to_payload() for item in trees]):
                raise ProjectConflict("Ordinary preparation cannot replace a different explicit source selection.")
        context = (nullcontext() if existing is not None or not (expectations or trees) else
                   sealed_source_runtime(store, expectations, generation=generation, trees=trees) if mode == "sealed" else
                   incoming_source_runtime(store, expectations, generation=generation, trees=trees))
        with context:
            def verify() -> None:
                if source is not None and files:
                    current_source_tree(source, files, identities,
                        expected=(request.get("resolved_figure_plan") or {}).get("source_sha256"))

            verify()
            yield verify
