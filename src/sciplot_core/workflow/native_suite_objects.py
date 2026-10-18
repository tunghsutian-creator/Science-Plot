"""Resolve source-bound suite figures without importing or replacing native authority."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_engine.description_scope import require_selector
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.studio_core.source_update_commit import reject_symlink_path
from sciplot_core.workflow.rheology_tts_suite import _check_sources, _compiled_figures
from sciplot_core.rheology_tts_native_display import native_targets as native_targets


def resolve_native_object(target: Path, figure_id: str | None = None) -> dict[str, Any] | None:
    target = target.expanduser()
    reject_symlink_path(target)
    target = target.resolve()
    candidates = ([target / "suite.json", target / "data/delivery_manifest.json"] if target.is_dir()
                  else [target] if target.name in {"suite.json", "delivery_manifest.json"}
                  else [target.parent.parent / "data/delivery_manifest.json"] if target.suffix.lower() == ".vsz"
                  else [])
    path = next((path for path in candidates if path.is_file()), None)
    if path is None:
        return None
    reject_symlink_path(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "sciplot_rheology_tts_suite":
        return None
    workspace, delivery = Path(manifest["workspace"]), Path(manifest["delivery"])
    for directory in (workspace, delivery):
        reject_symlink_path(directory)
        if directory != directory.resolve():
            raise ValueError("Native suite locations must be canonical absolute paths.")
    hidden, visible = workspace / "suite.json", delivery / "data/delivery_manifest.json"
    for bound in (hidden, visible):
        reject_symlink_path(bound)
        if json.loads(bound.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Visible and hidden suite manifests disagree.")
    if path not in (hidden, visible):
        raise ValueError("Native suite manifest is outside its bound workspace/delivery.")
    documents = manifest["documents"]
    identifiers = [item["id"] for item in documents]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Native suite document identities are not unique.")
    if target.suffix.lower() == ".vsz":
        matches = [item for item in documents if Path(item["path"]) == target]
        if len(matches) != 1 or (figure_id is not None and matches[0]["id"] != figure_id):
            raise EngineError("native_object_unknown_figure", "Choose an exact native figure from this suite.")
    else:
        matches = [item for item in documents if figure_id is None or item["id"] == figure_id]
    if len(matches) != 1:
        raise EngineError("native_object_figure_required", "Select one exact existing figure ID.",
                          available_figures=identifiers)
    selected = matches[0]
    native = Path(selected["path"])
    if native != delivery / "editable" / f"{selected['id']}.vsz":
        raise ValueError("Native figure lies outside its bound visible editable directory.")
    reject_symlink_path(native)
    if not native.is_file():
        raise EngineError("native_object_missing", "The selected native authority is missing; preserve the suite.")
    return {"plot": str(native), "figure_id": selected["id"], "workspace": str(workspace),
            "delivery": str(delivery), "manifest": manifest, "document": selected}


def require_object(target: Path) -> dict[str, Any]:
    context = resolve_native_object(target)
    if context is None:
        raise EngineError("native_object_unbound", "This is not a bound native suite figure.")
    return context


def selected_spec(context: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    manifest, identifier = context["manifest"], context["figure_id"]
    figure = _compiled_figures(manifest, figure_ids=(identifier,))[identifier]
    receipts = manifest.get("presentation_revision", {}).get("figures") or manifest["native_result"]["figures"]
    receipt = next(item for item in receipts if item["id"] == identifier)
    path = Path(receipt["spec_path"])
    reject_symlink_path(path)
    return path, figure


def capture_object(context: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.rheology_tts_render import inspect_tts_display

    manifest, native = context["manifest"], Path(context["plot"])
    _check_sources(manifest["sources"])
    spec_path, figure = selected_spec(context)
    spec_sha = file_sha256(spec_path)
    state = inspect_tts_display(native, figure)
    _check_sources(manifest["sources"])
    if spec_sha != file_sha256(spec_path):
        raise ValueError("Compiled figure changed during native inspection.")
    sources = manifest["sources"]
    scientific = json.loads(spec_path.read_text(encoding="utf-8"))
    return {**context, "state": state, "figure": figure, "spec_path": str(spec_path),
            "spec_sha256": spec_sha, **native_identity(context["workspace"], context["figure_id"],
                sources, spec_sha, state["document_sha256"]),
            "scientific_hash": canonical_json_sha256(scientific),
            "presentation_hash": state["document_sha256"]}


def native_identity(workspace: str, figure_id: str, sources: list[dict[str, Any]], spec_sha256: str,
                    native_sha256: str) -> dict[str, Any]:
    """Project existing successful creation evidence without native execution."""
    identity = {"workspace": workspace, "figure_id": figure_id}
    return {"plot_id": "native:" + canonical_json_sha256(identity)[:32],
            "revision": int(canonical_json_sha256({**identity, "sources": sources,
                "native": native_sha256, "spec": spec_sha256})[:13], 16),
            "revision_semantics": "content_bound"}


def descriptor(prop: str) -> dict[str, Any]:
    schema = ({"enum": ["top-left", "top-right", "bottom-left", "bottom-right"]}
              if prop == "legend.location" else {"type": "string", "minLength": 1, "maxLength": 500}
              if prop == "annotation.text" else {"type": "number", "minimum": 0, "maximum": 1})
    return {"risk": "presentation", "value_schema": schema}


def describe_native_object(target: Path, *, description: dict[str, Any] | None = None) -> dict[str, Any]:
    description = require_selector(description)
    captured = capture_object(require_object(target))
    targets = captured["state"]["targets"]
    contract = {identifier: {prop: descriptor(prop) for prop in item["properties"]}
                for identifier, item in targets.items()}
    result = {"kind": "sciplot_plot_description", "version": 1, "status": "current",
        "plot_type": "LegacyPlot", "plot": captured["plot"], "plot_id": captured["plot_id"],
        "revision": captured["revision"], "revision_semantics": "content_bound",
        "scientific_hash": captured["scientific_hash"], "presentation_hash": captured["presentation_hash"],
        "authority": {"kind": "native_suite", "visual": "saved_vsz", "semantic_adoption": False},
        "coverage": {"mode": "legacy_shadow", "limitations": ["Existing covered native legends and relative notes only."]},
        "changed_inputs": [], "pending": None,
        "dependencies": {"invalidated": [], "scope": "single_figure", "scientific_transforms_executed": 0},
        "artifact": captured["plot"], "artifact_status": "current"}
    from sciplot_core.workflow.native_suite_storage import pending_operation

    pending = pending_operation(captured)
    if pending:
        result["pending"] = {"idempotency_key": pending["request"]["idempotency_key"], "phase": pending["phase"]}
        result["next_step"] = {"action": "plot.resume", "plot": captured["plot"], "request": {
            key: pending["request"][key] for key in ("plot_id", "base_revision", "idempotency_key")}}
    if description is None:
        result["objects"] = {identifier: {key: deepcopy(item[key]) for key in ("kind", "label", "properties")}
                             for identifier, item in targets.items()}
        result["object_edit_contract"] = contract
        return result
    result["description_scope"] = description["scope"]
    if description["scope"] == "summary":
        result["edit_targets"] = {identifier: {"kind": item["kind"], "label": item["label"],
                                  "properties": list(item["properties"])} for identifier, item in targets.items()}
        return result
    identifier, prop = description["target"], description["property"]
    if identifier not in targets:
        raise EngineError("description_unknown_target", "Choose an exact stable target from the current summary.")
    if prop not in targets[identifier]["properties"]:
        raise EngineError("description_unknown_property", "Choose a property advertised for this target.")
    result.update(edit_target=identifier, edit_property=prop,
                  object_edit_contract={identifier: {prop: contract[identifier][prop]}},
                  current_value=targets[identifier]["properties"][prop])
    if not pending:
        result["next_step"] = {"action": "plot.patch", "plot": captured["plot"], "plot_id": captured["plot_id"],
            "base_revision": captured["revision"], "intent_class": "presentation", "target": identifier,
            "property": prop, "requires": ["authorized_value", "idempotency_key"]}
    return result
