"""Public delivery adapters share one closed request and truthful partial status."""

import json

import anyio
from jsonschema import Draft202012Validator

from sciplot_core.cli.dispatch import plots
from sciplot_core.cli.parsers import build_parser
from sciplot_core.mcp_server import server, services
from sciplot_core.mcp_server.schemas import tool_definitions
from sciplot_core.plot_engine.managed_delivery_contract import managed_delivery_schema


def request():
    return {"idempotency_key": "public-test", "title": "Display names", "mode": "native_snapshot",
            "out": "/new-delivery", "items": [{"plot": "/original", "plot_id": "plot:stable", "revision": 2, "label": "P0.3/0.7"}]}


def test_cli_deliver_routes_only_request_and_partial_is_nonzero(tmp_path, monkeypatch, capsys):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request()))
    args = build_parser().parse_args(["plot", "deliver", "--request", str(path), "--json"])
    calls = []
    monkeypatch.setattr(plots, "call", lambda method, params, **kwargs: calls.append((method, params)) or {"status": "partial", "ready_to_use": False})
    assert plots.dispatch_plot(args) == 1
    assert calls == [("plot.deliver", {"request": request()})]
    assert json.loads(capsys.readouterr().out)["ready_to_use"] is False


def test_mcp_discovery_closed_schema_dispatch_and_partial_error(monkeypatch):
    from test_task_capabilities import expand

    tool = {item.name: item for item in tool_definitions()}["sciplot_plot_deliver"]
    schema = expand(tool.input_schema)
    assert schema["properties"]["request"] == managed_delivery_schema()
    assert schema["additionalProperties"] is False
    assert tool.annotations.idempotent_hint and not tool.annotations.read_only_hint
    for invalid in ({"request": {**request(), "code": "execute"}}, {"request": request(), "plot": "/other"}):
        assert not Draft202012Validator(schema).is_valid(invalid)
    calls = []
    monkeypatch.setattr("sciplot_core.plot_protocol.client.call", lambda method, params: calls.append((method, params)) or {"status": "partial", "ready_to_use": False})
    assert services.invoke_owner("sciplot_plot_deliver", {"request": request()})["status"] == "partial"
    assert calls == [("plot.deliver", {"request": request()})]
    monkeypatch.setattr(server, "invoke_owner", lambda *_: {"status": "partial", "ready_to_use": False, "items": [{"status": "sealed"}, {"status": "failed"}]})

    async def scenario():
        result = await server.Adapter().call("sciplot_plot_deliver", {"request": request()})
        assert result.is_error and result.structured_content["ready_to_use"] is False
        assert [item["status"] for item in result.structured_content["items"]] == ["sealed", "failed"]

    anyio.run(scenario)
