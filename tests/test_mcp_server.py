from __future__ import annotations

import asyncio
import base64
import json
import threading
import time

import anyio
import pytest

pytest.importorskip("mcp")

from sciplot_core.mcp_server import server
from sciplot_core.mcp_server.errors import AdapterError, error_payload
from sciplot_core.mcp_server.resources import ResourceStore
from sciplot_core.mcp_server.schemas import tool_definitions
from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII=")


def test_tool_discovery_uses_closed_shared_operation_schema():
    tools = {item.name: item for item in tool_definitions()}
    assert len(tools) == 13
    for item in tools.values():
        assert item.input_schema["additionalProperties"] is False
        assert item.annotations.open_world_hint is False
    schema = tools["sciplot_edit_preview"].input_schema["properties"]["operations"]
    assert schema == annotation_operation_capabilities()["operations_schema"]
    assert tools["sciplot_project_inspect"].annotations.read_only_hint is True
    assert tools["sciplot_edit_apply"].annotations.read_only_hint is False
    assert tools["sciplot_task_start"].annotations.idempotent_hint is False


def test_invalid_or_unknown_calls_never_reach_domain_owner(monkeypatch):
    monkeypatch.setattr(server, "invoke_owner", lambda *_: pytest.fail("invalid call reached owner"))

    async def scenario():
        adapter = server.Adapter()
        unknown = await adapter.call("exec_python", {})
        invalid = await adapter.call("sciplot_project_inspect", {"project": "/example", "code": "print(1)"})
        assert unknown.is_error and invalid.is_error
        assert unknown.structured_content["error"]["code"] == "unknown_tool"
        assert invalid.structured_content["error"]["code"] == "invalid_arguments"

    anyio.run(scenario)


def test_compact_result_keeps_editable_values_and_unknown_readiness(monkeypatch):
    full = {"kind": "sciplot_project_inspection", "status": "ok", "ready_to_use": None,
            "source": {"current": None}, "selected_figure": {"document_sha256": "a" * 64,
            "objects": {"/graph/x": {"settings": {"data": list(range(200))},
            "editable_fields": [{"setting_path": "/graph/x/Label/size", "current_value": "7pt"}]}}}}
    monkeypatch.setattr(server, "invoke_owner", lambda *_: full)

    async def scenario():
        adapter = server.Adapter()
        result = await adapter.call("sciplot_project_inspect", {"project": "/example"})
        payload = result.structured_content
        assert payload["ready_to_use"] is None and payload["source"]["current"] is None
        assert payload["selected_figure"]["objects"]["/graph/x"] == {"editable_fields": full["selected_figure"]["objects"]["/graph/x"]["editable_fields"]}
        restored = await adapter.call("sciplot_read_result", {"uri": payload["full_result_resource"]})
        assert restored.structured_content["result"] == full
        assert (await adapter.call("sciplot_project_inspect", {"project": "/example", "full": True})).structured_content == full

    anyio.run(scenario)


def test_preview_is_available_on_demand_as_immutable_image(tmp_path, monkeypatch):
    path = tmp_path / "candidate.png"
    path.write_bytes(PNG)
    monkeypatch.setattr(server, "invoke_owner", lambda *_: {"status": "ok", "preview": {"path": str(path)}})

    async def scenario():
        adapter = server.Adapter()
        result = await adapter.call("sciplot_preview", {"project": "/example"})
        assert [item.type for item in result.content] == ["text", "resource_link"]
        uri = result.structured_content["preview_resource"]
        path.write_bytes(b"changed after preview")
        read = await adapter.call("sciplot_read_result", {"uri": uri})
        assert base64.b64decode(read.content[1].data) == PNG
        assert read.content[1].mime_type == "image/png"
        unknown = await adapter.call("sciplot_read_result", {"uri": "sciplot://result/" + "0" * 64})
        assert unknown.is_error and unknown.structured_content["error"]["code"] == "unknown_resource"

    anyio.run(scenario)


def test_resource_store_never_reads_unregistered_paths_and_is_bounded(tmp_path):
    store = ResourceStore(byte_limit=12)
    first = store.add("first", "application/json", b"1" * 10)
    second = store.add("second", "application/json", b"2" * 10)
    with pytest.raises(AdapterError, match="returned in this connection"):
        store.get(first.uri)
    assert store.get(second.uri).data == b"2" * 10
    with pytest.raises(AdapterError, match="exceeds"):
        store.add("large", "application/json", b"3" * 13)
    with pytest.raises(AdapterError):
        store.get("file:///etc/passwd")
    preview = tmp_path / "preview.png"
    preview.write_bytes(PNG)
    link = tmp_path / "link.png"
    link.symlink_to(preview)
    with pytest.raises(AdapterError, match="ordinary PNG"):
        store.add_preview(link)
    with pytest.raises(AdapterError, match="changed after"):
        ResourceStore().add_preview(preview, expected_sha256="0" * 64)


def test_compact_query_keeps_visible_series_identity():
    value = server.compact_result({"selected_figure": {"objects": {
        "/graph/xy": {"name": "xy", "settings": {"key": "E3", "xData": "x_1", "yData": "y_1", "irrelevant": 50}},
    }}})
    assert value["selected_figure"]["objects"]["/graph/xy"]["display_context"] == {"key": "E3", "xData": "x_1", "yData": "y_1"}


def test_domain_calls_are_serialized_and_stdout_is_not_protocol(monkeypatch, capsys):
    active, maximum = 0, 0
    lock = threading.Lock()

    def invoke(*_):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        print("incidental domain diagnostic")
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"status": "ok"}

    monkeypatch.setattr(server, "invoke_owner", invoke)

    async def scenario():
        adapter = server.Adapter()
        results = await asyncio.gather(*(adapter.call("sciplot_capabilities", {}) for _ in range(3)))
        assert all(not item.is_error for item in results)

    anyio.run(scenario)
    output = capsys.readouterr()
    assert maximum == 1 and output.out == ""
    assert output.err.count("incidental domain diagnostic") == 3


def test_failure_mapping_preserves_domain_codes_and_masks_unexpected_errors():
    class DomainError(ValueError):
        reason_code = "anchor_missing"

    assert error_payload(DomainError("No matching source point"))["error"]["code"] == "anchor_missing"
    assert error_payload(ValueError("The document revision is stale"))["error"]["code"] == "stale_revision"
    payload = error_payload(RuntimeError("internal secret traceback"))
    assert "secret" not in json.dumps(payload)
    assert payload["error"]["code"] == "execution_failed"


def test_resource_failure_does_not_erase_completed_operation(monkeypatch):
    monkeypatch.setattr(server, "invoke_owner", lambda *_: {"status": "applied", "operation_id": "a" * 64,
        "preview": {"path": "/missing/preview.png"}})

    async def scenario():
        result = await server.Adapter().call("sciplot_edit_apply", {"project": "/example", "review_path": "/review.json"})
        assert not result.is_error
        assert result.structured_content["status"] == "applied"
        assert result.structured_content["resource_warnings"]

    anyio.run(scenario)
