"""Construct genuine old pending receipts from captured native leaf results."""
from copy import deepcopy
import json
from pathlib import Path

from sciplot_core import rheology_tts_render as render
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow import native_suite_transactions as native
from sciplot_core.workflow.native_suite_objects import require_object
from sciplot_core.workflow.native_suite_preview import baseline_files
from sciplot_core.workflow.native_suite_storage import operation_path
from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
from sciplot_core.workflow.rheology_tts_saved_state import _active_receipts, _figure_folder
from sciplot_core.workflow.rheology_tts_style_storage import snapshot
from sciplot_core.workflow.rheology_tts_tables import write_json


def legacy_case(suite, monkeypatch, evidence_kind, *, installed=True, accepted=True):
    workspace, delivery, _source, _prepared, manifest = suite
    target = Path(manifest["documents"][0]["path"])
    context = require_object(target)
    captured = native.capture_object(context)
    request = {"plot_id": captured["plot_id"], "base_revision": captured["revision"],
        "idempotency_key": "current-native-effect", "intent_class": "presentation",
        "changes": [{"op": "set", "target": ["legend:graph1"], "property": "legend.location", "value": "top-right"}]}
    baseline = baseline_files(context)
    patch, export = render.patch_tts_display, render.export_tts_document
    frozen = {}

    def capture_patch(*args, **kwargs):
        receipt = patch(*args, **kwargs)
        frozen["edit"] = deepcopy(receipt)
        frozen["native"] = Path(receipt["document"]).read_bytes()
        return receipt

    def capture_export(*args, **kwargs):
        receipt = export(*args, **kwargs)
        frozen["export"] = deepcopy(receipt)
        frozen["outputs"] = {item["format"]: Path(item["path"]).read_bytes() for item in receipt["exports"]}
        return receipt

    with monkeypatch.context() as patcher:
        patcher.setattr(render, "patch_tts_display", capture_patch)
        patcher.setattr(render, "export_tts_document", capture_export)
        preview = native.patch_native(target, request)
        decided = native.decide_native(target, {**preview["next_step"]["request"], "accept": installed})
        assert decided["status"] == ("complete" if installed else "rejected")
    store = FileProjectStore(workspace, locations={"delivery": delivery})
    saved, = [item for item in store.commands() if item["metadata"]["request"].get("adapter") == "native_display"
              and item["metadata"]["request"].get("request") == request]
    historical_request = {**request, "idempotency_key": "genuine-legacy-pending"}
    path = operation_path(context, historical_request["idempotency_key"])
    path.parent.mkdir(parents=True)
    candidate = path.parent / "native" / target.name
    candidate.parent.mkdir()
    candidate.write_bytes(frozen["native"])
    edit = deepcopy(frozen["edit"])
    old_candidate = edit["document"]
    edit["document"] = str(candidate)
    for field in ("candidate_audit", "native_audit"):
        if edit.get(field, {}).get("document") == old_candidate:
            edit[field]["document"] = str(candidate)
    exported = deepcopy(frozen["export"])
    exported["document"] = str(candidate)
    exported["native_audit"]["document"] = str(candidate)
    for item in exported["exports"]:
        output = path.parent / "exports" / Path(item["path"]).name
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(frozen["outputs"][item["format"]])
        item["path"] = str(output)
    edit_path, export_path = path.parent / "native_edit.json", path.parent / "export_result.json"
    write_json(edit_path, edit)
    write_json(export_path, exported)
    old_preview = {"kind": "sciplot_native_display_preview", "version": 1,
        "workspace": str(workspace), "delivery": str(delivery), "sources": manifest["sources"],
        "contract_sha256": rheology_capabilities()["contract_sha256"], "baseline": baseline,
        "candidate_files": snapshot([candidate, edit_path, export_path,
            *(Path(item["path"]) for item in exported["exports"])]),
        "figures": deepcopy(_active_receipts(manifest)),
        "candidates": [{"id": context["figure_id"], "edit": edit, "export": exported}],
        "presentation_plan": {}, "status": "preview_ready"}
    preview_path = path.parent / "preview.json"
    write_json(preview_path, old_preview)
    (path.parent / "preview.sha256").write_text(canonical_json_sha256(old_preview))
    record = {**saved["result"], "kind": "sciplot_native_display_operation", "version": 1,
        "request": historical_request, "phase": "needs_review", "baseline": baseline,
        "decision_id": "legacy-" + saved["decision_id"], "preview": str(preview_path),
        "preview_png": next(item["path"] for item in exported["exports"] if item["format"] == "png_300")}
    spec = next(item for item in _active_receipts(manifest) if item["id"] == context["figure_id"])
    record["scientific_hash"] = canonical_json_sha256(json.loads(Path(spec["spec_path"]).read_bytes()))
    if not installed and accepted:
        record.update(phase="prepared", accepted=True)
    write_json(path, record)
    document = manifest["documents"][0]
    audit = _figure_folder(delivery, context["figure_id"]) / (context["figure_id"] + ".native-audit.json")
    installed_files = snapshot([target, *(Path(name) for name in document["exports"]),
                          *([audit] if audit.exists() else []), workspace / "suite.json", delivery / "data/delivery_manifest.json"])
    evidence = {"published_files": installed_files, "result": {"status": "ready", "workspace": str(workspace),
                "delivery": str(delivery), "exact_candidate_export": True, "numerical_refit": False}}
    if evidence_kind == "applied":
        write_json(path.parent / "applied.json", evidence)
    elif evidence_kind == "intent":
        evidence.update(kind="sciplot_rheology_publication_intent", version=1,
                        preview_sha256=canonical_json_sha256(old_preview))
        intent = path.parent / "publication_intents" / "exact.json"
        write_json(intent, evidence)
        intent.with_suffix(".sha256").write_text(canonical_json_sha256(evidence))
    assert (file_sha256(target) == exported["document_sha256"]) is installed
    assert ("accepted" not in json.loads(path.read_bytes())) is (installed or not accepted)
    return target, historical_request, record, path, installed_files
