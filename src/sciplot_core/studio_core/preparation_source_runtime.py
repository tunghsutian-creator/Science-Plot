"""Bind ordinary current preparation to exact admitted source versions once."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
from typing import Any

from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.incoming_sources import SourceExpectation, selected_expectations
from sciplot_core.project_store.locators import logical_for_literal
from sciplot_core.project_store.runtime import incoming_source_runtime, project_runtime, sealed_source_runtime
from sciplot_core.studio_core.project_query_sources import current_source_files, current_source_tree


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
    with project_runtime(store, generation=generation) as resolver:
        request = json.loads(store.read_bytes("plot_request.json", generation=generation))
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
        mode = _current_external_scope(store, snapshot, expectations) if expectations else "incoming"
        existing = selected_expectations(snapshot)
        if existing is not None and expectations:
            wanted = {(item.literal, item.source_id, item.sha256) for item in expectations}
            supplied = {(item["literal"], item["source_id"], item["sha256"]) for item in existing["sources"]}
            if existing["mode"] != mode or supplied != wanted:
                raise ProjectConflict("Ordinary preparation cannot replace a different explicit source selection.")
        context = (nullcontext() if existing is not None or not expectations else
                   (sealed_source_runtime if mode == "sealed" else incoming_source_runtime)(
                       store, expectations, generation=generation))
        with context:
            def verify() -> None:
                if source is not None and files:
                    current_source_tree(source, files, identities,
                        expected=(request.get("resolved_figure_plan") or {}).get("source_sha256"))

            verify()
            yield verify
