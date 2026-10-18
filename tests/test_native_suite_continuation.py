"""Native continuation binds existing selected audit files and visible artifacts."""

import json
from pathlib import Path

import pytest

from sciplot_core import rheology_tts_render
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.workflow.native_suite_operations import (
    decide_native_object, describe_native_object, export_native_object, patch_native_object,
)
from sciplot_core.workflow.native_suite_storage import operation_path
from sciplot_core.workflow.rheology_tts_style_storage import snapshot
from test_native_suite_operations import suite as suite, _accept, _request


@pytest.mark.comprehensive
@pytest.mark.parametrize("predecessor", ["edit", "export"])
def test_followup_edit_binds_existing_selected_audit_and_preserves_other_figures(suite, monkeypatch, predecessor):
    workspace, delivery, source, prepared, manifest = suite
    native, optional = [Path(item["path"]) for item in manifest["documents"]]
    if predecessor == "edit":
        described = describe_native_object(native, description={"scope": "summary"})
        preview = patch_native_object(native, _request(described, key="first-edit"))
        assert decide_native_object(native, _accept(preview))["status"] == "complete"
    else:
        assert export_native_object(native)["ready_to_use"] is True
    audit = delivery / "panels/Main.native-audit.json"
    assert audit.is_file()
    optional_context = {"workspace": str(workspace), "plot": str(optional)}
    broken = operation_path(optional_context, "broken-unselected")
    broken.parent.mkdir(parents=True)
    broken.write_text("{broken optional transaction", encoding="utf-8")
    (delivery / "SI/SI_Optional.native-audit.json").write_text("broken optional audit", encoding="utf-8")
    protected = snapshot([source, prepared, workspace / "figure_plan.json", delivery / "data/figure_plan.json",
        *(Path(item["spec_path"]) for item in manifest["native_result"]["figures"]), optional,
        *(Path(name) for name in manifest["documents"][1]["exports"]), broken,
        delivery / "SI/SI_Optional.native-audit.json"])
    described = describe_native_object(native, description={"scope": "summary"})
    calls, dispatch = [], rheology_tts_render._dispatch

    def counted(payload):
        calls.append((payload["action"], payload.get("figure", {}).get("id")))
        return dispatch(payload)

    monkeypatch.setattr(rheology_tts_render, "_dispatch", counted)
    request = _request(described, key="followup-edit", changes=[{"op": "set", "target": ["legend:graph1"],
        "property": "legend.location", "value": "bottom-right"}])
    preview = patch_native_object(native, request)
    record = json.loads(Path(preview["evidence"]).read_text())
    assert record["baseline"][str(audit)] == file_sha256(audit)
    result = decide_native_object(native, _accept(preview))
    assert result["status"] == "complete" and result["ready_to_use"] is True
    assert result["scientific_hash_changed"] is False and result["transform_execution"]["executed"] == []
    assert calls == [("display_state", "Main"), ("display_patch", "Main"), ("export", "Main")]
    assert snapshot([Path(name) for name in protected]) == protected


@pytest.mark.comprehensive
def test_selected_audit_drift_is_closed_and_exact_restoration_can_resume(suite, monkeypatch):
    workspace, delivery, source, prepared, manifest = suite
    native = Path(manifest["documents"][0]["path"])
    export_native_object(native)
    audit = delivery / "panels/Main.native-audit.json"
    original = audit.read_bytes()
    protected = snapshot([native, source, prepared, workspace / "figure_plan.json",
                          *(Path(name) for name in manifest["documents"][0]["exports"])])
    described = describe_native_object(native, description={"scope": "summary"})
    request = _request(described, key="selected-audit-drift")
    preview = patch_native_object(native, request)
    audit.write_bytes(original + b"\ncontrolled drift")
    with pytest.raises(ValueError, match="Stale presentation baseline"):
        decide_native_object(native, _accept(preview))
    assert snapshot([Path(name) for name in protected]) == protected
    assert not (Path(preview["evidence"]).parent / "applied.json").exists()
    assert "accepted" not in json.loads(Path(preview["evidence"]).read_text())
    audit.write_bytes(original)

    def forbidden(_payload):
        pytest.fail("Resuming a saved accepted candidate must not repeat native work.")

    monkeypatch.setattr(rheology_tts_render, "_dispatch", forbidden)
    result = decide_native_object(native, _accept(preview))
    assert result["status"] == "complete" and result["scientific_hash_changed"] is False


@pytest.mark.comprehensive
@pytest.mark.parametrize(("predecessor", "visible_state"), [
    ("fresh", "intact"), ("other_edited", "intact"), ("fresh", "missing"), ("fresh", "changed")])
def test_fresh_noop_reports_only_verified_visible_exports(suite, monkeypatch, predecessor, visible_state):
    _workspace, _delivery, _source, _prepared, manifest = suite
    index = 0
    if predecessor == "other_edited":
        first = Path(manifest["documents"][0]["path"])
        described = describe_native_object(first, description={"scope": "summary"})
        preview = patch_native_object(first, _request(described, key="edit-another-figure"))
        decide_native_object(first, _accept(preview))
        index = 1
    native = Path(manifest["documents"][index]["path"])
    visible = [Path(name) for name in manifest["documents"][index]["exports"]]
    protected = snapshot([native])
    described = describe_native_object(native, description={"scope": "summary"})
    if visible_state == "missing":
        visible[0].unlink()
    elif visible_state == "changed":
        visible[0].write_bytes(visible[0].read_bytes() + b"\ncontrolled artifact drift")
    calls, dispatch = [], rheology_tts_render._dispatch

    def counted(payload):
        calls.append(payload["action"])
        return dispatch(payload)

    monkeypatch.setattr(rheology_tts_render, "_dispatch", counted)
    request = _request(described, key="fresh-noop", changes=[{"op": "set", "target": ["legend:graph1"],
        "property": "legend.location", "value": "top-left"}])
    result = patch_native_object(native, request)
    assert result["changed"] is False and result["status"] == "complete"
    assert calls == ["display_state"]  # one inspection; no mutation, rendering or export
    assert snapshot([Path(name) for name in protected]) == protected
    if visible_state == "intact":
        assert result["ready_to_use"] is True and result["export_status"] == "complete"
        assert result["next_step"]["action"] == "deliver"
        assert {Path(item["path"]) for item in result["exports"]} == set(visible)
        assert all(item["sha256"] == file_sha256(Path(item["path"])) for item in result["exports"])
    else:
        assert result["ready_to_use"] is False and result["export_status"] == "pending"
        assert result["exports"] == [] and result["next_step"]["action"] == "plot.export"


@pytest.mark.parametrize("drift", ["none", "native_sha", "native_path", "artifact_path", "artifact_hash", "size", "inventory"])
def test_initial_export_projection_requires_bound_receipt_and_actual_visible_bytes(tmp_path, drift):
    from sciplot_core.workflow.native_suite_transactions import _current_exports

    workspace, delivery = tmp_path / ".sciplot/Figures", tmp_path / "Figures"
    native = delivery / "editable/Main.vsz"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"Generated byte-binding fixture, not native execution")
    exports = []
    for format_name, suffix in [("pdf", ".pdf"), ("tiff_300", "_300dpi.tiff"), ("png_300", "_300dpi.png")]:
        target = delivery / "panels" / ("Main" + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(format_name.encode())
        exports.append({"format": format_name, "path": str(workspace / "initial_render" / target.name),
                        "sha256": file_sha256(target), "exists": True, "size_bytes": target.stat().st_size})
    sha = file_sha256(native)
    visible = [str(delivery / "panels" / Path(item["path"]).name) for item in exports]
    document = {"id": "Main", "path": str(native), "sha256": sha, "exports": visible}
    receipt = {"document": str(workspace / "initial_render/Main.vsz"), "document_sha256": sha, "exports": exports}
    context = {"workspace": str(workspace), "delivery": str(delivery), "plot": str(native), "figure_id": "Main",
               "document": document, "manifest": {"native_result": {"figures": [receipt]}}}
    if drift == "native_sha":
        receipt["document_sha256"] = "0" * 64
    elif drift == "native_path":
        receipt["document"] = str(tmp_path / "unbound/Main.vsz")
    elif drift == "artifact_path":
        exports[0]["path"] = str(tmp_path / "unbound/Main.pdf")
    elif drift == "artifact_hash":
        exports[0]["sha256"] = "0" * 64
    elif drift == "size":
        exports[0]["size_bytes"] += 1
    elif drift == "inventory":
        document["exports"].pop()
    result = _current_exports(context, sha)
    if drift == "none":
        assert {item["path"] for item in result} == set(visible)
        assert all(item["sha256"] == file_sha256(Path(item["path"])) for item in result)
    else:
        assert result == []
