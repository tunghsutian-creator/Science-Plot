"""Select exact incoming and reviewed source versions for separate native reads."""
from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any

from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.incoming_sources import SourceExpectation
from sciplot_core.project_store.runtime import incoming_source_runtime, sealed_source_runtime
from sciplot_core.source_coverage.managed_documents import source_records


def _expectations(snapshot: dict[str, Any], observations: dict[str, str]) -> list[SourceExpectation]:
    result = []
    for literal, digest in sorted(observations.items()):
        owners = [identity for identity, versions in snapshot["sources"].items()
                  if any(entry.get("locator") == literal for entry in versions.values())]
        if len(owners) > 1:
            raise ValueError("The selected source literal has ambiguous registered identities")
        if owners:
            result.append(SourceExpectation(literal, owners[0], digest))
    return result


def incoming_scope(store: FileProjectStore, snapshot: dict[str, Any], source: Path,
                   inventory: dict[str, str]) -> AbstractContextManager[Any]:
    observations = {str(source / name if source.is_dir() else source): digest for name, digest in inventory.items()}
    selected = _expectations(snapshot, observations)
    return incoming_source_runtime(store, selected, generation=snapshot["generation"]) if selected else nullcontext()


def baseline_scope(store: FileProjectStore, snapshot: dict[str, Any], *, specs: Sequence[Path] | None = None) -> AbstractContextManager[Any]:
    observations: dict[str, str] = {}
    review_name = "source_update.json"
    if review_name in snapshot["files"]:
        review = json.loads(store.read_bytes(review_name, generation=snapshot["generation"]))
        source = Path(review["source"])
        inventory = review["source_files"]
        if not isinstance(inventory, dict):
            raise ValueError("The admitted source revision has no exact original source inventory")
        kind = review.get("source_kind")
        if kind not in {None, "file", "directory"}:
            raise ValueError("The admitted source revision has an invalid source kind")
        for name, digest in inventory.items():
            choices = [str(source / name)] if kind == "directory" else [str(source)] if kind == "file" else [
                str(source / name), *([str(source)] if name == source.name else [])]
            known = {literal for literal in choices if any(
                entry.get("locator") == literal for versions in snapshot["sources"].values() for entry in versions.values())}
            if len(known) > 1:
                raise ValueError("The historical source revision has an ambiguous original file locator")
            if known:
                observations[next(iter(known))] = digest
    names = ([path.relative_to(store.root).as_posix() for path in specs] if specs is not None else
             [name for name in snapshot["files"] if name == "studio/spec.json"])
    for name in names:
        if not name.startswith("studio/") or name not in snapshot["files"]:
            raise ValueError("A baseline scientific specification must be an admitted Studio member")
        spec = json.loads(store.read_bytes(name, generation=snapshot["generation"]))
        for source, digest in source_records(spec).items():
            literal = str(source)
            if literal in observations and observations[literal] != digest:
                raise ValueError("The reviewed native baseline repeats conflicting source versions")
            observations[literal] = digest
    selected = _expectations(snapshot, observations)
    return sealed_source_runtime(store, selected, generation=snapshot["generation"]) if selected else nullcontext()
