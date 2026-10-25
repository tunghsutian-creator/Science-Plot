"""Finite explicit scientific source declarations under the admitted figure lease."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
from typing import Any, Iterator

from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.project_store.locators import logical_for_literal
from .attachment_sources import _read_source, capture_source
from .errors import EngineError


def declarations(repository: Any, request: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    if request.get("intent_class") != "scientific":
        return ()
    document = repository.load_head(repository.attachment.root)["document"]
    if document.get("plot_type") != "ManagedPlot":
        return ()
    snapshot = repository.attachment.store.snapshot()
    result = []
    for change in request["changes"]:
        if change["property"] == "source.append":
            from sciplot_core.plot_engine.managed_source_append import append_schema

            validate_wire(change["value"], append_schema(), code="managed_append_invalid_value")
            sources = [dict(change["value"]["source"])]
        elif change["property"] == "source.sha256":
            from sciplot_core.plot_engine.managed_source_revision import source_descriptor, source_group

            if len(change["target"]) != 1:
                continue  # The existing domain validator rejects this before reading.
            target = change["target"][0]
            value = change["value"]
            validate_wire(value, source_descriptor(document, target, root=repository.attachment.root)["value_schema"],
                          code="managed_source_hash_invalid")
            _path, selected = source_group(document, target)
            version = value if isinstance(value, str) else value["sha256"]
            sources = [{**source, "sha256": version} for source in selected]
        else:
            continue
        for source in sources:
            literal = source["path"]
            if not Path(literal).is_absolute():
                raise EngineError("semantic_source_declaration_invalid", "An admitted source requires its exact absolute original locator.")
            logical = logical_for_literal(snapshot, literal)
            captured = None
            if logical is not None:
                before = snapshot["files"][logical]["sha256"]
                identities = [identity for identity, versions in snapshot["sources"].items()
                              if versions.get(before, {}).get("locator") == literal]
                if len(identities) != 1:
                    raise EngineError("semantic_source_declaration_invalid", "A tracked source observation requires its one registered original identity.")
                captured = repository.attachment.store.capture_source_observation(logical, source_id=identities[0], before_sha256=before)
                actual = Path(captured["path"])
            else:
                actual = Path(literal)
            version = source.get("sha256")
            if version is None:
                # The existing facts-only append asks to inspect this one exact
                # original file; its observed SHA never expands the read scope.
                version = captured["version"] if captured is not None else hashlib.sha256(capture_source(actual)[0]).hexdigest()
            _read_source(actual, version)
            result.append({"path": literal, "sha256": version, "source_id": source["source_id"],
                           "actual": str(actual), "logical": logical, "captured": captured})
    return tuple(result)


@contextmanager
def scientific_sources(repository: Any, request: dict[str, Any]) -> Iterator[None]:
    incoming = declarations(repository, request)
    resolver = repository._source.get()
    if not incoming or resolver is None:
        yield
        return
    with resolver.declaration_scope(incoming):
        yield
