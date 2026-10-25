"""Closed host projections leave scientific values and explicit labels intact."""

from copy import deepcopy

from sciplot_core.workflow.project_results import project_workflow_result


def test_project_artifacts_without_rewriting_scientific_identity_or_user_text():
    scientific = {"path": "/private-candidate/raw.csv", "output": "/private-candidate/literal"}
    payload = {"output": "/private-candidate/runs/one", "figures": ["/private-candidate/plot.pdf"],
        "result": {"veusz_documents": ["/private-candidate/doc.vsz"], "scientific_audit": scientific},
        "request": scientific, "transform_ledger": scientific, "source_request": scientific,
        "label": "/private-candidate/explicit-user-label", "raw_archive": {"source": "/original/raw.csv", "path": "/private-candidate/raw/copy.csv"},
        "delivery_package": {"path": "/private-candidate/delivery", "figures": [{"source": "/private-candidate/plot.pdf", "path": "/private-candidate/delivery/plot.pdf"}]}}
    original = deepcopy(payload)
    def logical(path):
        return path.replace("/private-candidate/", "/original-project/", 1)
    result = project_workflow_result(payload, logical)
    assert payload == original
    assert result["output"] == "/original-project/runs/one"
    assert result["figures"] == ["/original-project/plot.pdf"]
    assert result["result"]["veusz_documents"] == ["/original-project/doc.vsz"]
    assert all(result[field] == scientific for field in ("request", "transform_ledger", "source_request"))
    assert result["result"]["scientific_audit"] == scientific
    assert result["label"] == payload["label"]
    assert result["raw_archive"]["source"] == "/original/raw.csv"
    assert result["raw_archive"]["path"] == "/original-project/raw/copy.csv"
    assert result["delivery_package"]["figures"][0]["source"] == "/original-project/plot.pdf"
