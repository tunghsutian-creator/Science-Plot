"""Read-only service-owned export readiness survives the process boundary."""
import json

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine import service as service_module
from test_managed_description_scopes import _service


@pytest.mark.parametrize("mutation", ["bytes", "added_file", "recipe", "pending", "source", "missing_cache"])
def test_summary_checks_server_recipe_exact_output_inventory_and_current_guards(tmp_path, monkeypatch, mutation):
    service, root, document = _service(tmp_path, monkeypatch)
    graph = service_module.load_head(root)["binding"]["graph"]
    source = document["scientific"]["data_sources"][0]
    source_node = "source:" + source["source_id"]
    graph["nodes"][0]["dependencies"] = [source_node]
    graph["nodes"].insert(0, {"id": source_node, "kind": "source", "dependencies": [],
                            "parameters": {}, "version": "1", "content_hash": source["sha256"]})
    exported = tmp_path / "exports"
    exported.mkdir()
    pdf = exported / "figure.pdf"
    pdf.write_bytes(b"generated publication bytes")
    cache = {"build_key": "server-recipe", "export": {},
             "artifact_files": {str(pdf): file_sha256(pdf)},
             "evidence_inventories": {str(exported): ["figure.pdf"]}}
    cache_path = root / "export-cache.json"
    cache_path.write_text(json.dumps(cache))
    monkeypatch.setattr(service_module, "build_key", lambda *_args: "server-recipe")
    before = (root / "head.json").read_bytes()
    summary = service.describe(root, description={"scope": "summary"})
    assert summary["export_current"] == {"current": True, "byte_inventory_verified": True,
        "artifact_build_key": "server-recipe", "validation": "current"}
    assert (root / "head.json").read_bytes() == before
    if mutation == "bytes":
        pdf.write_bytes(b"independent changed publication")
    elif mutation == "added_file":
        (exported / "extra.csv").write_text("unsealed data")
    elif mutation == "recipe":
        monkeypatch.setattr(service_module, "build_key", lambda *_args: "different-server-recipe")
    elif mutation == "pending":
        pending = {"id": "pending", "phase": "needs_review", "request": {"idempotency_key": "pending"}}
        monkeypatch.setattr(service_module, "active", lambda _: pending)
        monkeypatch.setattr(service_module, "project_recovery", lambda *_args: None)
    elif mutation == "source":
        path = document["scientific"]["data_sources"][0]["path"]
        monkeypatch.setattr(service_module, "changed_inputs", lambda *_args: [path])
    else:
        cache_path.unlink()
    stale = service.describe(root, description={"scope": "summary"})
    assert stale["export_current"]["current"] is False
    assert stale["export_current"]["validation"] == "stale_or_missing"
    assert (root / "head.json").read_bytes() == before


def test_unavailable_recipe_is_unknown_read_only_instead_of_a_delivery_pass(tmp_path, monkeypatch):
    service, root, _ = _service(tmp_path, monkeypatch)

    def unavailable(*_args):
        raise RuntimeError("renderer identity unavailable")

    monkeypatch.setattr(service, "_cached_export", unavailable)
    before = (root / "head.json").read_bytes()
    result = service.describe(root, description={"scope": "summary"})
    assert result["export_current"]["current"] is False
    assert result["export_current"]["validation"] == "unknown"
    assert (root / "head.json").read_bytes() == before
