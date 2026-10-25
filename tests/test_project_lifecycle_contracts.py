"""Closed command admission, target resolution and actual public receipt projection."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json

import pytest
from test_plot_engine import FakeBackend, request
from test_project_lifecycle import MemoryRepository, application
from sciplot_core.project_lifecycle.contracts import AuthorityMode, RevisionToken, NormalizedCommand, Receipt


@pytest.mark.parametrize("field,value", [
    ("revision", True), ("revision", -1), ("revision", 1.0), ("plot_id", ""),
    ("plot_id", "invalid id"), ("scientific_hash", "bad"), ("presentation_hash", "A" * 64),
    ("authority", "managed"),
])
def test_revision_token_rejects_invalid_fields_before_execute(tmp_path, field, value):
    backend = FakeBackend(tmp_path / "native")
    doc, _ = backend.initial()
    fields = RevisionToken.of(doc).to_payload()
    fields["authority"] = AuthorityMode.LEGACY_NATIVE
    fields[field] = value
    with pytest.raises(ValueError):
        RevisionToken(**fields)
    assert not backend.native_writes


@pytest.mark.parametrize("field,value", [
    ("kind", "unknown"), ("kind", []), ("request_digest", "0" * 64),
    ("original_request_digest", "0" * 64), ("authority", "legacy_native"),
    ("idempotency_key", ""), ("expected_revision", None),
])
def test_normalized_command_rejects_invalid_envelopes(tmp_path, field, value):
    backend = FakeBackend(tmp_path / "native")
    doc, _ = backend.initial()
    command = NormalizedCommand.create("patch", request(), expected_revision=RevisionToken.of(doc))
    with pytest.raises(ValueError):
        replace(command, **{field: value})
    assert backend.calls["apply"] == 0


def test_unknown_authority_is_not_treated_as_legacy_and_old_model_is_not_rewritten(tmp_path):
    backend = FakeBackend(tmp_path / "native")
    old, _ = backend.initial()
    original = deepcopy(old)
    assert "plot_type" not in old and AuthorityMode.of(old) == AuthorityMode.LEGACY_NATIVE
    assert old == original
    with pytest.raises(ValueError, match="authority"):
        AuthorityMode.of({**old, "plot_type": "unknown_native"})
    with pytest.raises(ValueError):
        AuthorityMode.of({"scientific_hash": "a" * 64})


def test_execute_rejects_tampered_business_body_and_incorrect_creation_authority(tmp_path):
    backend, repo = FakeBackend(tmp_path / "native"), MemoryRepository()
    document, binding = backend.initial()
    root = tmp_path / "plot"
    repo.commit(root, document, binding, "import")
    app = application(backend, repo)
    original = request()
    other = request(width="2pt")
    command = NormalizedCommand.create("patch", original, expected_revision=RevisionToken.of(document), business_request=other)
    before = deepcopy(repo.values)
    with pytest.raises(ValueError, match="canonical business request"):
        app.execute(root, command)
    create = {"source": str(backend.raw), "idempotency_key": "create"}
    with pytest.raises(ValueError, match="authority"):
        app.execute(root, NormalizedCommand.create("create", create, authority=AuthorityMode.MANAGED))
    assert repo.values == before and backend.calls["apply"] == backend.calls["preview"] == 0


def test_application_consumes_closed_targets_and_never_discovers_store_layout(tmp_path, monkeypatch):
    import ast
    from sciplot_core.project_lifecycle.targets import ImportTarget, StoredTarget
    from sciplot_core.project_lifecycle import application as module

    backend, repo = FakeBackend(tmp_path / "native"), MemoryRepository()
    app = application(backend, repo)
    root = tmp_path / "explicit-store"
    monkeypatch.setattr(app.targets, "resolve_open", lambda *_: ImportTarget(root, backend.directory, "primary"))
    opened = app.open(tmp_path / "arbitrary-display-locator")
    assert opened["plot"] == str(root)
    monkeypatch.setattr(app.targets, "resolve_open", lambda *_: StoredTarget(root))
    assert app.open(tmp_path / "another-locator")["plot_id"] == opened["plot_id"]
    tree = ast.parse(Path(module.__file__).read_text())
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "mkdir"
                   for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Constant) and node.value in {"head.json", "index.json"}
                   for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str))




def test_public_rpc_cli_and_mcp_project_the_actual_typed_receipt(tmp_path, monkeypatch, capsys):
    from sciplot_core import cli
    from sciplot_core.cli.dispatch import plots
    from sciplot_core.mcp_server import services
    from sciplot_core.plot_protocol import rpc

    repo, backend = MemoryRepository(), FakeBackend(tmp_path / "native")
    document, binding = backend.initial()
    root = tmp_path / "plot"
    repo.commit(root, document, binding, "import")
    app = application(backend, repo)
    params = {"plot": str(root), "request": request()}
    def invoke(method, arguments, **_):
        response = rpc.handle(app, {"jsonrpc": "2.0", "id": 1, "method": method, "params": arguments})
        assert "error" not in response, response
        return response["result"]
    first = invoke("plot.patch", params)
    monkeypatch.setattr(plots, "call", invoke)
    payload = tmp_path / "patch.json"
    payload.write_text(json.dumps(request()))
    assert cli.main(["plot", "patch", str(root), "--request", str(payload), "--direct"]) == 0
    via_cli = json.loads(capsys.readouterr().out)
    monkeypatch.setattr("sciplot_core.plot_protocol.client.call", invoke)
    via_mcp = services.invoke_owner("sciplot_plot_patch", params)
    for result in (first, via_cli, via_mcp):
        assert result["status"] == result["export_status"] == "complete"
        assert result["commit_status"] == "committed"
        assert RevisionToken.of(result) == RevisionToken.of(repo.load_head(root)["document"])
        assert {key: result[key] for key in ("status", "commit_status", "export_status")} == {
            "status": "complete", "commit_status": "committed", "export_status": "complete"}
        assert result["command_digest"] == NormalizedCommand.create("patch", request(), expected_revision=RevisionToken.of(document)).request_digest
    assert backend.native_writes == 1
    unknown = {"document": document, "phase": "applying"}
    assert Receipt.of(unknown).to_payload()["command_digest"] is None
    assert Receipt.of(unknown).recovery.outcome == "native_outcome_requires_owner_validation"


def test_typed_recovery_is_the_single_compatible_status_projection(tmp_path):
    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    for phase, expected in (("planned", "blocked"), ("applying", "blocked"), ("export_pending", "blocked"), ("complete", "complete")):
        state = {"document": document, "phase": phase, "error": {"stage": "export"}}
        assert Receipt.of(state).to_payload()["status"] == expected
