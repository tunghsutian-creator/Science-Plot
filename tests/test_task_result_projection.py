from copy import deepcopy

import pytest

from sciplot_core.task_result_projection import compact_task_result


def receipt():
    return {"kind": "sciplot_task", "status": "complete", "task_dir": "/task", "project": "/project",
            "next_step": {"task": "/task", "action": "review_exports_and_deliver", "images": ["/figure.tiff"]},
            "result": {"kind": "sciplot_project_creation_result", "document": "/figure.vsz", "request": "/request.json",
                       "figures": [{"exports": [{"path": "/figure.tiff"}]}], "studio_run": {"ready_to_use": True}},
            "current_project": {"ready_to_use": None, "readiness_evaluated": False,
                "figures": [{"figure_id": "f", "document": "/figure.vsz", "document_sha256": "a" * 64,
                             "spec": "/figure.json", "spec_sha256": "b" * 64, "sample_styles": [{"sample": "A", "unique": True}]}],
                "source": {"status": "current", "current": True, "scope": "hashes", "scientific_audit_evaluated": False,
                           "input": {"path": "/data.csv", "sha256": "c" * 64}},
                "qa": {"status": "stale", "current": False, "error": "changed document"},
                "delivery": {"status": "unknown", "current": None, "failed_checks": ["missing export"]}}}


def test_compact_response_keeps_edit_bindings_readiness_and_failed_evidence():
    full = receipt()
    before = deepcopy(full)
    result = compact_task_result(full)
    assert full == before
    assert "figures" not in result["result"]
    assert result["next_step"]["images"] == ["/figure.tiff"]
    for key in ("qa", "delivery", "ready_to_use", "readiness_evaluated"):
        assert result["current_project"][key] == full["current_project"][key]
    figure = result["current_project"]["figures"][0]
    assert figure["document_sha256"] == "a" * 64 and figure["document"] == "/figure.vsz"
    assert figure["sample_styles"] == full["current_project"]["figures"][0]["sample_styles"]


def test_pending_questions_audits_and_review_bindings_are_lossless():
    full = {"kind": "sciplot_task", "status": "needs_review", "operation_id": "a" * 64,
            "question": {"evidence": {"raw_metadata": {"unit": ""}, "conflicts": ["unit missing"]}},
            "preview": {"image": "/preview.png", "scientific_audit": {"valid": False}},
            "previews": [{"scope": "candidate", "path": "/candidate.png"}],
            "mapping_error": {"message": "invalid columns"}, "revision_id": "b" * 64}
    assert compact_task_result(full) == full


def test_mcp_task_full_response_remains_available_by_flag_and_immutable_resource(monkeypatch):
    anyio = pytest.importorskip("anyio")
    pytest.importorskip("mcp")
    from sciplot_core.mcp_server import server

    full = receipt()
    monkeypatch.setattr(server, "invoke_owner", lambda *_: deepcopy(full))

    async def scenario():
        adapter = server.Adapter()
        result = await adapter.call("sciplot_task_inspect", {"task": "/task"})
        payload = result.structured_content
        assert "figures" not in payload["result"]
        restored = await adapter.call("sciplot_read_result", {"uri": payload["full_result_resource"]})
        assert restored.structured_content["result"] == full
        assert (await adapter.call("sciplot_task_inspect", {"task": "/task", "full": True})).structured_content == full

    anyio.run(scenario)


def test_missing_current_project_keeps_historical_artifact_paths_for_diagnosis():
    full = receipt()
    full["current_project"] = {"status": "unknown", "message": "project unavailable"}
    full["next_step"] = {"action": "inspect_current_project"}
    compact = compact_task_result(full)
    assert compact["current_project"] == full["current_project"]
    assert compact["result"]["figures"] == full["result"]["figures"]
    assert compact["result"]["document"] == full["result"]["document"]
