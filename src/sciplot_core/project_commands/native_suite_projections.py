"""Fixed NativeSuite figure reads and under-lock manifest merges, without I/O."""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePath
import re
from typing import Any


_BINDINGS = ("kind", "version", "workspace", "delivery", "sources", "prepared_input",
             "figure_layout", "contract_sha256")
_PUBLICATION_CLOCKS = ("timestamp", "created_at", "updated_at", "started_at", "finished_at",
                       "started_utc", "finished_utc", "elapsed_seconds", "wall_seconds")


def _manifest(value: dict[str, Any]) -> None:
    if (not isinstance(value, dict) or value.get("kind") != "sciplot_rheology_tts_suite"
            or type(value.get("version")) is not int or value["version"] != 1
            or not isinstance(value.get("workspace"), str)
            or not isinstance(value.get("delivery"), str)
            or not isinstance(value.get("sources"), list)):
        raise ValueError("Expected a version-1 NativeSuite manifest.")


def _identifier(row: dict[str, Any], *, exported: bool = False) -> str:
    identity = row.get("id")
    if identity is None and exported and isinstance(row.get("document"), str):
        identity = PurePath(row["document"]).stem
    if not isinstance(identity, str) or not identity:
        raise ValueError("NativeSuite figure rows require an exact identity.")
    return identity


def _selected(rows: Any, key: str, *, exported: bool = False) -> dict[str, Any] | None:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("NativeSuite figure records must be an ordered list.")
    identities = [_identifier(row, exported=exported) for row in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("NativeSuite figure identities cannot be duplicated.")
    return next((row for row, identity in zip(rows, identities, strict=True) if identity == key), None)


def _spec(value: dict[str, Any], key: str) -> dict[str, Any]:
    revision = value.get("presentation_revision", {})
    if not isinstance(revision, dict):
        raise ValueError("Invalid NativeSuite presentation revision.")
    selected = _selected(revision.get("figures", []), key)
    if selected is None:
        native = value.get("native_result")
        if not isinstance(native, dict):
            raise ValueError("NativeSuite creation evidence is absent.")
        selected = _selected(native.get("figures"), key)
    if (selected is None or not isinstance(selected.get("spec_path"), str)
            or not selected["spec_path"] or not isinstance(selected.get("spec_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", selected["spec_sha256"]) is None):
        raise ValueError("The selected NativeSuite scientific specification is unbound.")
    return {name: deepcopy(selected[name]) for name in ("id", "spec_path", "spec_sha256")}


def native_suite_figure(value: dict[str, Any], key: str) -> dict[str, Any]:
    """Bind one figure's authority and output inventory, never another figure."""
    _manifest(value)
    document = _selected(value.get("documents"), key)
    if document is None or any(name not in document for name in ("path", "sha256", "exports")):
        raise ValueError("The selected NativeSuite document is unbound.")
    exported = _selected(value.get("last_export", []), key, exported=True)
    publication = deepcopy(exported)
    if publication is not None:
        for name in _PUBLICATION_CLOCKS:
            publication.pop(name, None)
        for artifact in publication.get("exports", []):
            for name in _PUBLICATION_CLOCKS:
                artifact.pop(name, None)
    # Preview locations and whole-suite publication descriptions are not native,
    # scientific or source authority for this selected figure.
    return {"bindings": {name: deepcopy(value[name]) for name in _BINDINGS if name in value},
            "document": deepcopy(document), "spec": _spec(value, key),
            "last_export": publication}


def _replace(rows: list[dict[str, Any]], row: dict[str, Any], key: str, *,
             exported: bool = False) -> list[dict[str, Any]]:
    selected = _selected(rows, key, exported=exported)
    if selected is None:
        return [*deepcopy(rows), deepcopy(row)]
    return [deepcopy(row if _identifier(item, exported=exported) == key else item) for item in rows]


def merge_native_suite_figure(current: dict[str, Any], candidate: dict[str, Any],
                              key: str) -> dict[str, Any]:
    """Merge only the declared figure after the store revalidates its read token."""
    before, after = native_suite_figure(current, key), native_suite_figure(candidate, key)
    if before["bindings"] != after["bindings"]:
        raise ValueError("NativeSuite source and project bindings require a whole-set command.")
    old, new = before["document"], after["document"]
    if old["path"] != new["path"] or old["exports"] != new["exports"]:
        raise ValueError("NativeSuite selected publication paths cannot be remapped by a figure command.")
    result = deepcopy(current)
    result["documents"] = _replace(result["documents"], new, key)
    active = _spec(candidate, key)
    if active != _spec(current, key):
        revision = result.setdefault("presentation_revision", {"version": 1, "figures": []})
        revision["figures"] = _replace(revision.get("figures", []), active, key)
    exported = _selected(candidate.get("last_export", []), key, exported=True)
    if exported is not None:
        result["last_export"] = _replace(result.get("last_export", []), exported,
                                         key, exported=True)
    return result
