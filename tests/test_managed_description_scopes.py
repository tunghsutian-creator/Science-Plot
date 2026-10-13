"""Compact reads preserve managed edit contracts and currentness guards."""

import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from managed_plot_helpers import request_for_source
from test_figure_document import request_for_figure

from sciplot_core.plot_engine import service as service_module
from sciplot_core.plot_engine.description_scope import selector_issues
from sciplot_core.plot_engine.figure_updates import patch_capabilities
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec, store_spec
from sciplot_core.plot_protocol import rpc


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, figure: bool = True) -> tuple[PlotService, Path, dict]:
    request = request_for_figure(tmp_path) if figure else request_for_source(tmp_path)
    document = create_managed_document(request["template_definition"], request["data_binding"], plot_id="scoped-test")
    root = tmp_path / "saved-plot"
    root.mkdir()
    (root / "head.json").write_text("head remains unchanged")
    native = tmp_path / "current.vsz"
    native.write_text("saved native artifact")
    binding = {"document": str(native), "ir_hash": "a" * 64, "ir_path": str(tmp_path / "ir.json"),
               "fingerprint": {"files": {}},
               "graph": {"kind": "sciplot_dependency_graph", "schema_version": 1, "nodes": [
                   {"id": "compile", "kind": "compile", "dependencies": [], "parameters": {}, "version": "1"},
                   {"id": "render", "kind": "render", "dependencies": ["compile"], "parameters": {}, "version": "1"},
                   {"id": "export", "kind": "export", "dependencies": ["render"], "parameters": {}, "version": "1"},
               ]}}
    head = {"document": document, "binding": binding}
    monkeypatch.setattr(service_module, "load_head", lambda _: head)
    monkeypatch.setattr(service_module, "canonical_path", lambda path: path)
    monkeypatch.setattr(service_module, "external_project_session", lambda _: nullcontext())
    monkeypatch.setattr(service_module, "changed_inputs", lambda _backend, _binding: [])
    monkeypatch.setattr(service_module, "active", lambda _: None)
    monkeypatch.setattr(service_module, "dependency_state", lambda _doc, _binding, _changed: {"invalidated": []})
    return PlotService(backend=object()), root, document


def _wire_size(result: dict) -> int:
    return len(rpc.encode({"jsonrpc": "2.0", "id": "measure", "result": result}))


def test_omitted_full_and_compact_open_describe_equivalence(tmp_path, monkeypatch):
    service, root, document = _service(tmp_path, monkeypatch)
    full = service.describe(root)
    assert service.open(root) == full
    assert {"figure_spec", "figure_template_schema", "figure_edit_contract", "backend_capabilities"} <= full.keys()

    selector = {"scope": "summary"}
    summary = service.open(root, description=selector)
    assert service.describe(root, description=selector) == summary
    assert summary["plot_id"] == full["plot_id"] == document["plot_id"]
    for key in ("kind", "version", "status", "plot_type", "plot", "revision", "scientific_hash",
                "presentation_hash", "authority", "coverage", "pending", "changed_inputs", "artifact_status"):
        assert summary[key] == full[key]
    assert summary["dependencies"]["invalidated"] == full["dependencies"]["invalidated"]
    assert summary["next_step"]["action"] == "plot.describe"
    assert "figure_template_schema" not in summary and "figure_spec" not in summary
    assert {target: info["properties"] for target, info in summary["edit_targets"].items()} == {
        target: list(properties) for target, properties in patch_capabilities(figure_spec(document)).items()}
    assert summary["edit_targets"]["layer:modulus"]["kind"] == "layer"
    assert summary["edit_targets"]["layer:modulus"]["label"] == "Gprime"

    target, prop = "scale:x", "scale.domain"
    scoped = service.describe(root, description={"scope": "edit", "target": target, "property": prop})
    assert scoped["figure_edit_contract"] == {target: {prop: full["figure_edit_contract"][target][prop]}}
    assert scoped["figure_edit_contract"][target][prop]["risk"] == "scientific"
    assert scoped["current_value"] == figure_spec(document)["scales"][0]["domain"]
    assert scoped["target_context"] == {"dimension": "x", "quantity": "frequency", "unit": "Hz",
                                        "transform": "linear", "direction": "ascending"}
    assert scoped["next_step"]["intent_class"] == "scientific"
    assert scoped["next_step"]["base_revision"] == full["revision"]
    assert _wire_size(summary) < _wire_size(full) * .5
    assert _wire_size(scoped) < _wire_size(full) * .5

    ticks = service.describe(root, description={"scope": "edit", "target": "axis:xb", "property": "axis.ticks"})
    assert ticks["target_context"]["scale_id"] == "scale:x"
    assert ticks["target_context"]["unit"] == "Hz"
    assert ticks["target_context"]["domain"] == [0, 10]


def test_every_figure_summary_pair_matches_exact_full_contract(tmp_path, monkeypatch):
    service, root, document = _service(tmp_path, monkeypatch)
    full = patch_capabilities(figure_spec(document))
    summary = service.describe(root, description={"scope": "summary"})
    assert {target: info["properties"] for target, info in summary["edit_targets"].items()} == {
        target: list(properties) for target, properties in full.items()}
    for target, properties in full.items():
        for prop, descriptor in properties.items():
            scoped = service.describe(root, description={"scope": "edit", "target": target, "property": prop})
            assert scoped["figure_edit_contract"] == {target: {prop: descriptor}}


@pytest.mark.parametrize("description", [
    {}, {"scope": "full"}, {"scope": "summary", "target": "scale:x"},
    {"scope": "edit", "target": "scale:x"}, {"scope": "edit", "target": "", "property": "style"},
    {"scope": "edit", "target": "scale:x", "property": ""},
])
def test_malformed_selector_is_rejected_before_open_writes(tmp_path, description):
    service = PlotService(backend=object())
    target = tmp_path / "not-created"
    assert selector_issues(description)
    with pytest.raises(ValueError, match="description"):
        service.open(target, description=description)
    assert not target.exists()


@pytest.mark.parametrize("description", [
    {"scope": "summary", 3: True},
    {"scope": "summary", 3: True, "extra": 1},
    {"scope": "edit", "target": "scale:x", "property": "scale.domain", 3: True, "extra": 1},
])
def test_non_string_selector_keys_fail_closed_before_project_open(tmp_path, description):
    # A direct Python caller can pass keys impossible in JSON. They still
    # receive a normal, bounded selector issue before any import.
    issues = selector_issues(description)
    allowed = ["scope"] if description["scope"] == "summary" else ["property", "scope", "target"]
    assert issues == [{"path": "/description", "constraint": "additionalProperties", "allowed": allowed}]
    service = PlotService(backend=object())
    target = tmp_path / "not-created"
    with pytest.raises(ValueError) as error:
        service.open(target, description=description)
    assert error.value.reason_code == "invalid_description_selector"
    assert error.value.issues == issues
    assert not target.exists()


def test_unknown_target_and_property_fail_closed(tmp_path, monkeypatch):
    service, root, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="target ID") as target_error:
        service.describe(root, description={"scope": "edit", "target": "scale:missing", "property": "scale.domain"})
    assert target_error.value.reason_code == "description_unknown_target"
    with pytest.raises(ValueError, match="property advertised") as property_error:
        service.describe(root, description={"scope": "edit", "target": "scale:x", "property": "style"})
    assert property_error.value.reason_code == "description_unknown_property"


def test_equal_axis_labels_still_require_stable_ids_and_exact_scientific_context(tmp_path, monkeypatch):
    service, root, _ = _service(tmp_path, monkeypatch)
    head = service_module.load_head(root)
    spec = figure_spec(head["document"])
    for axis in spec["views"][0]["axes"]:
        axis["label"] = "frequency"
    head["document"] = store_spec(head["document"], spec)

    summary = service.describe(root, description={"scope": "summary"})
    assert summary["edit_targets"]["axis:xb"]["label"] == summary["edit_targets"]["axis:yl"]["label"]
    for axis_id, scale_id, unit, domain in (("axis:xb", "scale:x", "Hz", [0, 10]),
                                            ("axis:yl", "scale:y", "Pa", [0, 20])):
        edit = service.describe(root, description={"scope": "edit", "target": axis_id,
                                                   "property": "axis.label"})
        assert edit["edit_target"] == edit["next_step"]["target"] == axis_id
        assert edit["target_context"]["scale_id"] == scale_id
        assert edit["target_context"]["unit"] == unit
        assert edit["target_context"]["domain"] == domain
        assert edit["next_step"]["base_revision"] == summary["revision"]
        assert edit["scientific_hash"] == summary["scientific_hash"]

    with pytest.raises(ValueError) as error:
        service.describe(root, description={"scope": "edit", "target": "frequency",
                                            "property": "axis.label"})
    assert error.value.reason_code == "description_unknown_target"


def test_compact_reads_keep_native_stale_and_pending_guards(tmp_path, monkeypatch):
    service, root, _ = _service(tmp_path, monkeypatch)
    native = service_module.load_head(root)["binding"]["document"]
    monkeypatch.setattr(service_module, "changed_inputs", lambda _backend, _binding: [native])
    summary = service.describe(root, description={"scope": "summary"})
    assert summary["status"] == "stale"
    assert summary["changed_inputs"] == [native]
    assert summary["artifact_status"] == "changed"
    assert summary["dependencies"]["invalidated"] == ["render", "export"]
    assert summary["next_step"] == {"action": "resolve_external_mutation", "automatic_adoption": False}
    scoped = service.describe(root, description={"scope": "edit", "target": "scale:x", "property": "scale.domain"})
    assert scoped["next_step"] == summary["next_step"]

    monkeypatch.setattr(service_module, "changed_inputs", lambda _backend, _binding: [])
    monkeypatch.setattr(service_module, "active", lambda _: {"request": {"idempotency_key": "in-progress"},
                                                              "phase": "needs_review"})
    pending = service.describe(root, description={"scope": "summary"})
    assert pending["pending"] == {"idempotency_key": "in-progress", "phase": "needs_review"}
    assert "next_step" not in pending


def test_managed_v1_and_legacy_behavior(tmp_path, monkeypatch):
    service, root, _ = _service(tmp_path, monkeypatch, figure=False)
    full = service.open(root)
    summary = service.open(root, description={"scope": "summary"})
    assert summary["edit_targets"]
    target = next(target for target, info in summary["edit_targets"].items() if info["properties"])
    prop = summary["edit_targets"][target]["properties"][0]
    scoped = service.describe(root, description={"scope": "edit", "target": target, "property": prop})
    assert scoped["object_edit_contract"][target][prop] == full["objects"][target]["capabilities"][prop]
    assert scoped["current_value"] == full["objects"][target]["properties"][prop]

    head = service_module.load_head(root)
    head["document"]["plot_type"] = "LegacyPlot"
    monkeypatch.setattr("sciplot_core.plot_engine.external_mutation.authority_status", lambda _: {"mode": "LegacyPlot"})
    assert service.open(root, description={"scope": "summary"}) == service.open(root)
    with pytest.raises(ValueError, match="ManagedPlot"):
        service.open(root, description={"scope": "edit", "target": target, "property": prop})


def test_rpc_cli_and_mcp_expose_one_closed_selector(tmp_path, monkeypatch, capsys):
    from sciplot_core import cli
    from sciplot_core.cli.dispatch import plots as plot_dispatch
    from sciplot_core.mcp_server.schemas import tool_definitions

    class Capture:
        def __init__(self):
            self.calls = []

        def open(self, target, figure_id=None, *, description=None):
            self.calls.append(("open", target, figure_id, description))
            return {"description": description or {}}

        def describe(self, plot, *, description=None):
            self.calls.append(("describe", plot, description))
            return {"description": description or {}}

    capture = Capture()
    for method, params in (("project.open", {"target": str(tmp_path), "description": {"scope": "summary"}}),
                           ("plot.describe", {"plot": str(tmp_path), "description": {
                               "scope": "edit", "target": "scale:x", "property": "scale.domain"}})):
        response = rpc.handle(capture, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        assert response["result"]["description"] == params["description"]
    prior = len(capture.calls)
    invalid = rpc.handle(capture, {"jsonrpc": "2.0", "id": 2, "method": "project.open", "params": {
        "target": str(tmp_path), "description": {"scope": "summary", "typo": True}}})
    assert invalid["error"]["code"] == -32602 and len(capture.calls) == prior

    forwarded = []
    monkeypatch.setattr(plot_dispatch, "call", lambda method, params, **_: forwarded.append((method, params)) or {"status": "ready"})
    assert cli.main(["plot", "open", str(tmp_path), "--scope", "summary", "--direct"]) == 0
    assert cli.main(["plot", "describe", str(tmp_path), "--scope", "edit", "--target-id", "scale:x",
                     "--property", "scale.domain", "--direct"]) == 0
    capsys.readouterr()
    assert forwarded[0][1]["description"] == {"scope": "summary"}
    assert forwarded[1][1]["description"] == {"scope": "edit", "target": "scale:x", "property": "scale.domain"}
    tools = {tool.name: tool for tool in tool_definitions()}
    for name in ("sciplot_project_open", "sciplot_plot_describe"):
        schema = tools[name].input_schema
        assert "description" in schema["properties"]
        assert schema["properties"]["description"]["oneOf"]


def test_byte_sizes_are_transport_payloads_not_token_claims(tmp_path, monkeypatch):
    service, root, _ = _service(tmp_path, monkeypatch)
    full = service.describe(root)
    summary = service.describe(root, description={"scope": "summary"})
    scoped = service.describe(root, description={"scope": "edit", "target": "scale:x", "property": "scale.domain"})
    assert _wire_size(full) == len(json.dumps({"jsonrpc": "2.0", "id": "measure", "result": full},
                                              ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()) + 1
    assert 0 < _wire_size(summary) < _wire_size(full)
    assert 0 < _wire_size(scoped) < _wire_size(full)
