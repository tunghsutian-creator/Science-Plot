"""Pure native creation source/spec identity and exact preserved output locators."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.rheology_tts_spec import _identifier

def _check_sources(spec: dict[str, Any]) -> None:
    binding = spec["source_binding"]
    sources = binding.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("Native creation requires a list of explicit source bindings.")
    if "prepared_plan" in binding:
        sources = [*sources, binding["prepared_plan"]]
    for source in sources:
        if not isinstance(source, dict) or not {"path", "sha256"} <= source.keys():
            raise ValueError("Native creation source binding requires path and SHA256.")
        from sciplot_core.foundation.source_locations import resolve_source_path as resolve_runtime_path
        original = Path(source["path"])
        path = resolve_runtime_path(original, expected_sha256=source["sha256"])
        if not original.is_absolute() or not path.is_file() or file_sha256(path) != source["sha256"]:
            raise ValueError(f"Native creation source changed; preserve the saved documents: {path}")


def _sidecar(spec: dict[str, Any], figure: dict[str, Any]) -> dict[str, Any]:
    return {"kind": spec["kind"], "version": 1, "source_binding": spec["source_binding"],
            "transform_ledger": spec["transform_ledger"], "figure": figure}


def _literal(path: Path) -> str:
    from sciplot_core.foundation.source_locations import literal_source_path as literal_runtime_path
    return literal_runtime_path(path) if path.exists() else str(path)


def _context(spec: dict[str, Any], out: Path) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    identifiers = [_identifier(figure["id"]) for figure in spec["figures"]]
    if len(set(name.casefold() for name in identifiers)) != len(identifiers):
        raise ValueError("Native creation figure names must be unique, including case.")
    plan_sha = canonical_json_sha256(spec, allow_nan=False)
    bindings = [{"out": _literal(out), "plan_sha256": plan_sha, "figure_id": identifier}
                for identifier in identifiers]
    return identifiers, bindings, [_sidecar(spec, figure) for figure in spec["figures"]]

