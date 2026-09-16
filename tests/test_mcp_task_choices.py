from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
import struct
import zlib

import anyio
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import pytest

pytest.importorskip("mcp")

from mcp import Client

from sciplot_core import task_control, task_execution
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mcp_server import server
from sciplot_core.mcp_server.schemas import tool_definitions
from sciplot_core.task_contract import task_request_schema, task_response_schema


def _column_source(tmp_path: Path) -> Path:
    source = tmp_path / "UVvis.csv"
    source.write_text(
        "Wavelength,Absorbance,,Wavelength,Absorbance,Notes\n"
        "nm,a.u.,,nm,a.u.,\nE0,E0,,E3,E3,\n"
        "400,1.00,,405,3.00, NA \n425,2.00,,430,4.00,N/A\n450,1.00,,455,5.00,\n",
        encoding="utf-8",
    )
    return source


def _request(source: Path) -> dict:
    return {"version": 1, "action": "create", "source": str(source),
            "rule_id": "uvvis_spectrum", "choose_columns": True}


def test_mcp_column_choices_use_shared_closed_request_and_question_schemas():
    tools = {tool.name: tool for tool in tool_definitions()}
    start = tools["sciplot_task_start"].input_schema
    resume = tools["sciplot_task_resume"].input_schema
    from test_task_capabilities import expand

    assert expand(start)["properties"]["request"] == task_request_schema()
    assert expand(resume)["properties"]["response"] == task_response_schema()
    request = _request(Path("/source.csv"))
    Draft202012Validator(start).validate({"request": request})
    response = {"expected_question_id": "a" * 64, "column_mapping": {"x_column": 3, "y_column": 4}}
    Draft202012Validator(resume).validate({"task": "/task", "response": response})
    for malformed in ("true", False, 1):
        with pytest.raises(ValidationError):
            Draft202012Validator(start).validate({"request": {**request, "choose_columns": malformed}})
    invalid_responses = [
        {"column_mapping": response["column_mapping"]},
        {**response, "expected_question_id": "stale"},
        {**response, "column_mapping": {"x_column": True, "y_column": 4}},
        {**response, "column_mapping": {"x_column": 3, "y_column": 4, "unit": "nm"}},
    ]
    for malformed in invalid_responses:
        with pytest.raises(ValidationError):
            Draft202012Validator(resume).validate({"task": "/task", "response": malformed})


def test_mcp_real_column_evidence_and_mapping_resume_survive_new_connection(tmp_path, monkeypatch):
    source = _column_source(tmp_path)
    original = source.read_bytes()
    calls = []
    project = tmp_path / "mocked_native_project"

    def create(path, **kwargs):
        calls.append((path, kwargs))
        return {"project_dir": str(project), "status": "created",
                "studio_run": {"ready_to_use": True, "failure_reason": None}}

    monkeypatch.setattr(task_execution, "create_project", create)
    monkeypatch.setattr(task_control, "inspect_project", lambda path: {
        "project": str(path), "source": {"current": source.read_bytes() == original},
        "ready_to_use": None, "readiness_evaluated": False,
    })

    async def scenario():
        async with Client(server.create_server()) as client:
            started = await client.call_tool("sciplot_task_start", {
                "request": _request(source), "task_dir": str(tmp_path / "task"),
            })
            assert not started.is_error, started.content
            pending = started.structured_content
            assert pending["status"] == "needs_input" and not calls
            question = pending["question"]
            assert question["field"] == "column_mapping"
            evidence = question["evidence"]
            assert evidence["source"] == str(source)
            assert evidence["file_sha256"] == file_sha256(source)
            assert [column["index"] for column in evidence["columns"]] == list(range(6))
            assert evidence["columns"][2]["header"] == ""
            assert evidence["rows"][3]["cells"] == ["400", "1.00", "", "405", "3.00", " NA "]
            assert evidence["rows"][4]["cells"][-1] == "N/A"
            before_answer = (Path(pending["task_dir"]) / "task.json").read_bytes()
            stale = await client.call_tool("sciplot_task_resume", {
                "task": pending["task_dir"], "response": {
                    "expected_question_id": "0" * 64,
                    "column_mapping": {"x_column": 3, "y_column": 4},
                },
            })
            assert stale.is_error and not calls
            assert (Path(pending["task_dir"]) / "task.json").read_bytes() == before_answer
            completed = await client.call_tool("sciplot_task_resume", {
                "task": pending["task_dir"], "response": {
                    "expected_question_id": question["question_id"],
                    "column_mapping": {"x_column": 3, "y_column": 4},
                },
            })
            assert not completed.is_error, completed.content
            result = completed.structured_content
            assert result["status"] == "complete" and len(calls) == 1
            assert result["model_calls_by_sciplot"] == 0 and result["external_model_tokens"] is None
            assert calls[0][0] == source
            plan = calls[0][1]["expected_plan"]
            assert plan["source"] == str(source)
            mapping_path = Path(result["data_mapping"]["data_mapping_execution"])
            mapping = json.loads(mapping_path.read_text())
            assert mapping["source_hashes"] == {source.name: file_sha256(source)}
            state = json.loads((Path(result["task_dir"]) / "task.json").read_text())
            proposal = json.loads(Path(state["mapping_choice"]["proposal_path"]).read_text())
            assert [column["source_column_index"] for column in proposal["columns"]] == [3, 4]
            assert proposal["sample_labels"] == {"source": "E3"}
            assert proposal["transformations"] == []
        async with Client(server.create_server()) as fresh_client:
            inspected = await fresh_client.call_tool("sciplot_task_inspect", {"task": result["task_dir"]})
            assert not inspected.is_error, inspected.content
            current = inspected.structured_content
            assert current["status"] == "complete"
            assert current["data_mapping"] == result["data_mapping"]
            assert current["current_project"]["source"]["current"] is True
            assert len(calls) == 1

    anyio.run(scenario)
    assert source.read_bytes() == original


def test_mcp_pending_column_answer_rejects_changed_source_before_creation(tmp_path, monkeypatch):
    source = _column_source(tmp_path)
    monkeypatch.setattr(task_execution, "create_project", lambda *args, **kwargs: pytest.fail("stale source reached creation"))

    async def scenario():
        async with Client(server.create_server()) as client:
            started = await client.call_tool("sciplot_task_start", {
                "request": _request(source), "task_dir": str(tmp_path / "task"),
            })
            assert not started.is_error, started.content
            pending = started.structured_content
            source.write_text(source.read_text().replace("455,5.00", "455,50.00"))
            result = await client.call_tool("sciplot_task_resume", {
                "task": pending["task_dir"], "response": {
                    "expected_question_id": pending["question"]["question_id"],
                    "column_mapping": {"x_column": 3, "y_column": 4},
                },
            })
            assert result.is_error
            assert result.structured_content["blocker"]["reason_code"] == "source_changed"

    anyio.run(scenario)


def _png(rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgb))) + chunk(b"IEND", b""))


def _source_update_payload(tmp_path: Path) -> tuple[dict, dict[str, bytes]]:
    images = {"before": _png((255, 0, 0)), "candidate": _png((0, 0, 255))}
    previews = []
    for scope, data in images.items():
        path = tmp_path / f"{scope}.png"
        path.write_bytes(data)
        previews.append({"figure_id": "uvvis", "scope": scope,
                         "preview": {"path": str(path), "sha256": file_sha256(path)}})
    return ({"kind": "sciplot_task", "version": 1, "status": "needs_review",
             "phase": "source_review", "revision_id": "a" * 64, "previews": previews}, images)


def test_mcp_source_update_exposes_both_pngs_as_readable_session_resources(tmp_path, monkeypatch):
    payload, images = _source_update_payload(tmp_path)
    monkeypatch.setattr(server, "invoke_owner", lambda *args: deepcopy(payload))

    async def scenario():
        async with Client(server.create_server()) as client:
            result = await client.call_tool("sciplot_task_inspect", {"task": str(tmp_path / "task")})
            assert not result.is_error, result.content
            references = result.structured_content["preview_resources"]
            assert {item["scope"] for item in references} == {"before", "candidate"}
            assert len({item["uri"] for item in references}) == 2
            assert all(item["figure_id"] == "uvvis" for item in references)
            assert len([item for item in result.content if item.type == "resource_link"]) == 2
            for reference in references:
                read = await client.read_resource(reference["uri"])
                assert base64.b64decode(read.contents[0].blob) == images[reference["scope"]]
                image = await client.call_tool("sciplot_read_result", {"uri": reference["uri"]})
                assert not image.is_error and image.content[1].type == "image"
                assert base64.b64decode(image.content[1].data) == images[reference["scope"]]
            (tmp_path / "candidate.png").write_bytes(images["before"])
            candidate = next(item for item in references if item["scope"] == "candidate")
            frozen = await client.read_resource(candidate["uri"])
            assert base64.b64decode(frozen.contents[0].blob) == images["candidate"]
        async with Client(server.create_server()) as fresh_client:
            expired = await fresh_client.call_tool("sciplot_read_result", {"uri": candidate["uri"]})
            assert expired.is_error and expired.structured_content["error"]["code"] == "unknown_resource"

    anyio.run(scenario)


@pytest.mark.parametrize("changed_scope", ["before", "candidate"])
def test_mcp_source_update_resource_hash_failure_preserves_completed_mutation(tmp_path, monkeypatch, changed_scope):
    payload, images = _source_update_payload(tmp_path)
    payload.update(status="complete", phase="finished", source_update_outcome={"status": "applied", "revision_id": "a" * 64})
    other_scope = "candidate" if changed_scope == "before" else "before"
    (tmp_path / f"{changed_scope}.png").write_bytes(images[other_scope])
    owner_calls = []

    def applied_result(name, arguments):
        owner_calls.append((name, arguments))
        return deepcopy(payload)

    monkeypatch.setattr(server, "invoke_owner", applied_result)

    async def scenario():
        async with Client(server.create_server()) as client:
            result = await client.call_tool("sciplot_task_resume", {
                "task": str(tmp_path / "task"),
                "response": {"expected_revision_id": "a" * 64, "accept_source_update": True},
            })
            assert not result.is_error, result.content
            assert len(owner_calls) == 1
            returned = result.structured_content
            assert returned["status"] == "complete"
            assert returned["source_update_outcome"] == payload["source_update_outcome"]
            assert len(returned["resource_warnings"]) == 1
            assert "changed after its owner returned it" in returned["resource_warnings"][0]
            references = returned["preview_resources"]
            assert [item["scope"] for item in references] == [other_scope]
            read = await client.read_resource(references[0]["uri"])
            assert base64.b64decode(read.contents[0].blob) == images[other_scope]

    anyio.run(scenario)
