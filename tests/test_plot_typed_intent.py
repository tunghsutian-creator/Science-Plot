"""Deterministic common text edits stay inside the existing patch transaction."""

from __future__ import annotations

import json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

import pytest
from test_figure_document import request_for_figure

from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine import service as service_module
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.typed_intent import compile_intent, validate_intent
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_protocol import rpc


def _document(tmp_path: Path, *, annotation: bool = False) -> dict:
    request = request_for_figure(tmp_path)
    if annotation:
        request["template_definition"]["figure_spec"]["annotations"] = [{
            "id": "annotation:peak", "space": "data", "view_id": "view:A", "x_scale": "scale:x",
            "y_scale": "scale:y", "x": 5, "y": 15, "text": "Peak", "visible": True, "style": {},
        }]
    return create_managed_document(request["template_definition"], request["data_binding"], plot_id="intent-test")


def _request(**changes: object) -> dict:
    return {"mode": "plan", "plot_id": "intent-test", "base_revision": 0,
            "idempotency_key": "same-key", "property": "axis.label",
            "target_label": "Frequency (Hz)", "value": "Frequency, Hz", **changes}


def test_axis_plan_compiles_to_existing_patch_without_scientific_change(tmp_path: Path) -> None:
    document = _document(tmp_path)
    source = tmp_path / "figure.csv"
    source_bytes = source.read_bytes()
    patch, plan = compile_intent(document, validate_intent(_request()))
    assert patch == {"plot_id": "intent-test", "base_revision": 0, "idempotency_key": "same-key",
                     "intent_class": "presentation", "changes": [{"op": "set", "target": ["axis:xb"],
                     "property": "axis.label", "value": "Frequency, Hz"}]}
    assert plan["target"] == {"id": "axis:xb", "kind": "axis", "label": "Frequency (Hz)"}
    assert plan["target_context"]["unit"] == "Hz"
    assert plan["target_context"]["view_id"] == "view:A"
    assert plan["target_context"]["side"] == "bottom"
    assert plan["effective_risk"] == "presentation"
    edited, diff, risk, science = prepare_update(document, patch)
    assert diff and risk == "presentation" and not science
    assert edited["scientific_hash"] == document["scientific_hash"]
    assert edited["presentation_hash"] != document["presentation_hash"]
    assert source.read_bytes() == source_bytes
    assert document["presentation"]["objects"]["axis:xb"]["label"] == "Frequency (Hz)"
    _, noop = compile_intent(document, validate_intent(_request(value="Frequency (Hz)")))
    assert noop["status"] == "no_change"


def test_annotation_text_and_exact_type_restrictions(tmp_path: Path) -> None:
    document = _document(tmp_path, annotation=True)
    request = _request(property="annotation.text", target_id="annotation:peak", target_label=None,
                       value="Observed peak")
    request.pop("target_label")
    patch, plan = compile_intent(document, validate_intent(request))
    assert patch["changes"][0]["target"] == ["annotation:peak"]
    assert plan["target_context"] == {"space": "data", "view_id": "view:A",
                                       "x_scale": "scale:x", "y_scale": "scale:y", "x": 5, "y": 15}
    with pytest.raises(ValueError) as bad_value:
        compile_intent(document, validate_intent({**request, "value": ""}))
    assert bad_value.value.reason_code == "plot_intent_invalid_value"
    with pytest.raises(EngineError) as bad_target:
        compile_intent(document, validate_intent({**request, "target_id": "axis:xb"}))
    assert bad_target.value.reason_code == "plot_intent_unknown_target"
    with pytest.raises(ValueError) as unsupported:
        validate_intent({**request, "property": "scale.domain"})
    assert unsupported.value.reason_code == "plot_intent_invalid"


def test_ambiguous_label_returns_typed_stable_candidates_and_does_not_mutate(tmp_path: Path) -> None:
    document = _document(tmp_path)
    duplicate = deepcopy(document)
    # Use the full FigureSpec projection to preserve the v2 split contract.
    from sciplot_core.plot_ir.figure_document import figure_spec, store_spec

    spec = figure_spec(duplicate)
    for axis in spec["views"][0]["axes"]:
        axis["label"] = "Same"
    duplicate = store_spec(duplicate, spec)
    before = deepcopy(duplicate)
    with pytest.raises(EngineError) as error:
        compile_intent(duplicate, validate_intent(_request(target_label="Same")))
    assert error.value.reason_code == "plot_intent_ambiguous_target"
    assert {item["id"] for item in error.value.repair["candidates"]} == {"axis:xb", "axis:yl"}
    assert {item["context"]["side"] for item in error.value.repair["candidates"]} == {"bottom", "left"}
    assert {item["context"]["unit"] for item in error.value.repair["candidates"]} == {"Hz", "Pa"}
    assert duplicate == before
    with pytest.raises(EngineError) as unknown:
        compile_intent(duplicate, validate_intent(_request(target_label="missing")))
    assert {item["id"] for item in unknown.value.repair["candidates"]} == {"axis:xb", "axis:yl"}


def test_ambiguous_annotation_context_identifies_anchor(tmp_path: Path) -> None:
    from sciplot_core.plot_ir.figure_document import figure_spec, store_spec

    document = _document(tmp_path, annotation=True)
    spec = figure_spec(document)
    other = deepcopy(spec["annotations"][0])
    other.update(id="annotation:second", x=8, y=10)
    spec["annotations"].append(other)
    document = store_spec(document, spec)
    request = _request(property="annotation.text", target_id=None, target_label="Peak", value="New peak")
    request.pop("target_id")
    with pytest.raises(EngineError) as ambiguous:
        compile_intent(document, validate_intent(request))
    candidates = ambiguous.value.repair["candidates"]
    assert {item["id"] for item in candidates} == {"annotation:peak", "annotation:second"}
    assert {item["context"]["x"] for item in candidates} == {5, 8}
    assert {item["context"]["space"] for item in candidates} == {"data"}


def test_stale_and_legacy_requests_fail_closed(tmp_path: Path) -> None:
    document = _document(tmp_path)
    with pytest.raises(EngineError) as stale:
        compile_intent(document, validate_intent(_request(base_revision=1)))
    assert stale.value.reason_code == "document_revision_conflict"
    with pytest.raises(EngineError) as identity:
        compile_intent(document, validate_intent(_request(plot_id="wrong")))
    assert identity.value.reason_code == "document_identity_conflict"
    legacy = deepcopy(document)
    legacy["plot_type"] = "LegacyPlot"
    with pytest.raises(EngineError) as unsupported:
        compile_intent(legacy, validate_intent(_request()))
    assert unsupported.value.reason_code == "plot_intent_v2_required"


def test_plan_is_read_only_and_apply_delegates_to_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = _document(tmp_path)
    root = tmp_path / "plot"
    root.mkdir()
    head = {"document": document, "binding": {}}
    monkeypatch.setattr(service_module, "canonical_path", lambda path: path)
    monkeypatch.setattr(service_module, "load_head", lambda _: head)
    monkeypatch.setattr(service_module, "active", lambda _: None)
    monkeypatch.setattr(service_module, "require_current", lambda *_: None)
    service = PlotService(backend=object())
    monkeypatch.setattr(service_module, "external_project_session", lambda _: pytest.fail("plan took a write lease"))
    monkeypatch.setattr(service, "_patch", lambda *_: pytest.fail("plan called the patch transaction"))
    before_files = list(root.rglob("*"))
    result = service.intent(root, _request())
    assert result["status"] == "ready" and result["plot"] == str(root)
    assert list(root.rglob("*")) == before_files

    captured = []
    monkeypatch.setattr(service_module, "external_project_session", lambda _: nullcontext())
    monkeypatch.setattr(service, "_patch", lambda _root, patch: captured.append(patch) or {"status": "complete"})
    assert service.intent(root, _request(mode="apply"))["status"] == "complete"
    assert captured == [result["patch_request"]]


def test_unsupported_plan_never_fingerprints_or_launches_native(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    document = _document(tmp_path)
    document["plot_type"] = "LegacyPlot"
    root = tmp_path / "plot"
    root.mkdir()
    monkeypatch.setattr(service_module, "canonical_path", lambda path: path)
    monkeypatch.setattr(service_module, "load_head", lambda _: {"document": document, "binding": {}})
    monkeypatch.setattr(service_module, "require_current", lambda *_: pytest.fail("Legacy plan fingerprinted native"))
    service = PlotService(backend=object())
    with pytest.raises(EngineError) as error:
        service.intent(root, _request())
    assert error.value.reason_code == "plot_intent_v2_required"


def test_plan_fails_if_inputs_drift_between_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = _document(tmp_path)
    root = tmp_path / "plot"
    root.mkdir()
    monkeypatch.setattr(service_module, "canonical_path", lambda path: path)
    monkeypatch.setattr(service_module, "load_head", lambda _: {"document": document, "binding": {}})
    monkeypatch.setattr(service_module, "active", lambda _: None)
    checks = []

    def current(*_args: object) -> None:
        checks.append(True)
        if len(checks) == 2:
            raise EngineError("document_inputs_changed", "Input changed after first fingerprint.")

    monkeypatch.setattr(service_module, "require_current", current)
    with pytest.raises(EngineError) as drift:
        PlotService(backend=object()).intent(root, _request())
    assert drift.value.reason_code == "document_inputs_changed"
    assert len(checks) == 2
    assert not list(root.rglob("*"))


def test_apply_retry_resolves_original_snapshot_not_renamed_label(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    original = _document(tmp_path)
    root = tmp_path / "plot"
    root.mkdir()
    patch, _ = compile_intent(original, validate_intent(_request()))
    newer, _, _, _ = prepare_update(original, patch)
    newer["revision"] = 1
    newer = seal_document(newer)
    saved = root / "transaction.json"
    saved.write_text("{}")
    monkeypatch.setattr(service_module, "canonical_path", lambda path: path)
    monkeypatch.setattr(service_module, "external_project_session", lambda _: nullcontext())
    monkeypatch.setattr(service_module, "transaction_path", lambda *_: saved)
    transaction = {"before": original, "request": patch, "request_hash": service_module.digest(patch),
                   "phase": "complete"}
    monkeypatch.setattr(service_module, "read", lambda _: transaction)
    monkeypatch.setattr(service_module, "load_head", lambda _: {"document": newer})
    service = PlotService(backend=object())
    replayed = []
    monkeypatch.setattr(service_module, "replay", lambda _root, tx, _backend: replayed.append(tx) or {"status": "complete"})
    assert service.intent(root, _request(mode="apply"))["status"] == "complete"
    assert replayed == [transaction]
    with pytest.raises(EngineError) as stale:
        service.intent(root, _request(mode="apply", base_revision=1))
    assert stale.value.reason_code == "document_revision_conflict"
    with pytest.raises(EngineError) as different:
        service.intent(root, _request(mode="apply", value="Different label"))
    assert different.value.reason_code == "document_idempotency_conflict"


def test_rpc_cli_mcp_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from sciplot_core import cli
    from sciplot_core.cli.dispatch import plots as dispatch
    from sciplot_core.mcp_server import services
    from sciplot_core.mcp_server.schemas import tool_definitions

    request = _request()
    class Capture:
        def intent(self, plot: Path, received: dict) -> dict:
            assert plot == tmp_path.resolve() and received == request
            return {"status": "ready"}

    call = {"jsonrpc": "2.0", "id": 1, "method": "plot.intent", "params": {"plot": str(tmp_path), "request": request}}
    assert rpc.handle(Capture(), call)["result"] == {"status": "ready"}
    assert rpc.handle(Capture(), {**call, "params": {**call["params"], "extra": True}})["error"]["code"] == -32602
    forwarded = []
    monkeypatch.setattr(dispatch, "call", lambda method, params, **_: forwarded.append((method, params)) or {"status": "ready"})
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    assert cli.main(["plot", "intent", str(tmp_path), "--request", str(path), "--direct"]) == 0
    capsys.readouterr()
    assert forwarded == [("plot.intent", {"plot": str(tmp_path), "request": request})]
    tools = {item.name: item for item in tool_definitions()}
    tool = tools["sciplot_plot_intent"]
    assert not tool.annotations.read_only_hint and tool.annotations.destructive_hint
    assert tool.input_schema["properties"]["request"]["properties"]["property"]["enum"] == [
        "axis.label", "annotation.text"]
    monkeypatch.setattr("sciplot_core.plot_protocol.client.call", lambda method, params: forwarded.append((method, params)) or {"status": "ready"})
    assert services.invoke_owner("sciplot_plot_intent", call["params"]) == {"status": "ready"}
    assert forwarded[-1] == ("plot.intent", call["params"])
