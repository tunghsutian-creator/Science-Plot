"""One pure reader of retained NativeSuite declarations; no host IO or repair."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

from sciplot_core.project_commands.resource_roles import SourceVersionRef


def _manifest(value: dict[str, Any]) -> None:
    # The original saved suites predate an explicit version field. Missing is
    # their retained v1 shape; an explicit unknown version is never that shape.
    if (not isinstance(value, dict) or value.get("kind") != "sciplot_rheology_tts_suite"
            or "version" in value and (type(value["version"]) is not int or value["version"] != 1)):
        raise ValueError("Expected a supported retained NativeSuite manifest.")


@dataclass(frozen=True)
class NativeSuiteCatalog:
    """Finite old catalog projections do not need or invent host/root fields."""
    _documents: tuple[dict[str, Any], ...]
    _original: tuple[dict[str, Any], ...]
    _overlay: tuple[dict[str, Any], ...]
    _exports: tuple[dict[str, Any], ...]

    def documents(self, figure_ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        identifiers = [document["id"] for document in self._documents]
        if (figure_ids is not None and (not isinstance(figure_ids, tuple) or not figure_ids
                or len(set(figure_ids)) != len(figure_ids) or any(identifier not in identifiers for identifier in figure_ids))):
            raise ValueError("Select exact, unique existing figure IDs before native execution.")
        return [deepcopy(document) for document in self._documents if figure_ids is None or document["id"] in figure_ids]

    def active_receipts(self) -> list[dict[str, Any]]:
        original = {item["id"]: item for item in self._original}
        if len({item["id"] for item in self._overlay}) != len(self._overlay):
            raise ValueError("Active compiled figure identities are not unique.")
        original.update({item["id"]: item for item in self._overlay})
        return [deepcopy(original[document["id"]]) for document in self._documents]

    def export_receipts(self) -> dict[str, dict[str, Any]]:
        identifiers = [item["id"] for item in self._documents]
        result: dict[str, dict[str, Any]] = {}
        for rows in (self._original, self._exports):
            seen = set()
            for item in rows:
                identifier = PurePosixPath(item["document"]).stem
                if identifier not in identifiers or identifier in seen or item.get("id", identifier) != identifier:
                    raise ValueError("Saved export receipts require unique bound figure identities.")
                seen.add(identifier)
                result[identifier] = deepcopy(item)
        if set(result) != set(identifiers):
            raise ValueError("Saved export receipts lack a creation-bound figure.")
        return result


def _rows(value: Any, label: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"NativeSuite {label} records must be an ordered list.")
    return tuple(deepcopy(value))


def parse_suite_catalog(value: dict[str, Any]) -> NativeSuiteCatalog:
    # Old current-export readers receive a selected catalog, not a complete
    # manifest. Validate only that declared format; never supply fake roots.
    if not isinstance(value, dict):
        raise ValueError("A NativeSuite catalog requires an object.")
    if "kind" in value:
        _manifest(value)
    elif "version" in value and (type(value["version"]) is not int or value["version"] != 1):
        raise ValueError("Unsupported retained NativeSuite catalog version.")
    documents = _rows(value.get("documents", []), "document")
    identifiers = [row["id"] for row in documents]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Saved document identities are not unique.")
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise ValueError("NativeSuite documents require exact figure identities.")
    native = value.get("native_result", {})
    presentation = value.get("presentation_revision", {})
    if not isinstance(native, dict) or not isinstance(presentation, dict):
        raise ValueError("NativeSuite receipt overlays require their retained object format.")
    return NativeSuiteCatalog(documents, _rows(native.get("figures", []), "creation"),
        _rows(presentation.get("figures", []), "presentation"), _rows(value.get("last_export", []), "export"))


@dataclass(frozen=True)
class NativeSuiteBindings:
    """Original scientific locators are independent of selected host IO roots."""
    workspace_locator: str
    delivery_locator: str
    sources: tuple[SourceVersionRef, ...]
    catalog: NativeSuiteCatalog
    prepared_input: SourceVersionRef | None = None

    def documents(self, figure_ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        return self.catalog.documents(figure_ids)

    def native_locator(self, document: dict[str, Any]) -> str:
        identifier = document["id"]
        selected = next((row for row in self.catalog._documents if row["id"] == identifier), None)
        from sciplot_core.project_commands.native_suite_projections import native_suite_native_locator
        expected = native_suite_native_locator(self.delivery_locator, identifier)
        if selected is None or PurePosixPath(document["path"]) != expected or document["path"] != selected["path"]:
            raise ValueError("Native figure is outside its exact bound editable member.")
        return str(expected)



def parse_suite_bindings(value: dict[str, Any]) -> NativeSuiteBindings:
    _manifest(value)
    workspace, delivery = value["workspace"], value["delivery"]
    if (not isinstance(workspace, str) or not isinstance(delivery, str)
            or not PurePosixPath(workspace).is_absolute() or not PurePosixPath(delivery).is_absolute()):
        raise ValueError("NativeSuite origins must be exact absolute locations.")
    sources = _rows(value.get("sources", []), "source")
    references = source_references(sources)
    prepared = value.get("prepared_input")
    if prepared is not None and not isinstance(prepared, dict):
        raise ValueError("NativeSuite prepared input requires its retained source declaration.")
    prepared_ref = SourceVersionRef(prepared["path"], prepared["sha256"]) if prepared else None
    return NativeSuiteBindings(workspace, delivery, references, parse_suite_catalog(value), prepared_ref)


def validate_suite_manifest(value: Any) -> dict[str, Any]:
    """Minimal root reader for known legacy/pending shapes, without fake fields."""
    _manifest(value)
    return cast(dict[str, Any], value)


def source_references(sources: Any) -> tuple[SourceVersionRef, ...]:
    return tuple(SourceVersionRef(row["path"], row["sha256"], row.get("source_id"))
                 for row in _rows(sources, "source"))
