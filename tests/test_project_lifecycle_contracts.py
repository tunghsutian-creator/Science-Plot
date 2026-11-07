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


@pytest.mark.parametrize("kind", ["create", "patch", "intent", "rollback", "reimport", "export"])
@pytest.mark.parametrize("field", ["original_request", "business_request"])
def test_normalized_command_owns_nested_values_exposed_to_callers(tmp_path, kind, field):
    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    supplied = request()
    command = NormalizedCommand.create(kind, supplied,
        expected_revision=None if kind == "create" else RevisionToken.of(document))
    original = command.to_payload()
    supplied["changes"][0]["target"].append("caller-owned")
    body = getattr(command, field)
    # Preserve the original mutable-field counterexample while checking the
    # detached compatibility value of the new owned request representation.
    exposed = body if isinstance(body, dict) else body.to_payload()
    exposed["changes"][0]["target"].append("exposed-value")
    exposed["changes"][0]["value"] = "changed after admission"
    exposed["changes"].append(deepcopy(exposed["changes"][0]))
    assert command.to_payload() == original
    returned = command.to_payload()
    returned["original_request"]["changes"].clear()
    returned["business_request"]["changes"][0]["target"].clear()
    assert command.to_payload() == original
    assert not backend.native_writes


def test_normalized_command_retains_literal_numeric_and_unicode_identity(tmp_path):
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    original = {**request(), "literal": {"μ": [1, 1.0, -0.0, "1.00", "1e0"]}}
    business = {**deepcopy(original), "literal": {"μ": [-0.0, 1.0, 1, "1e0", "1.00"]}}
    command = NormalizedCommand.create("intent", original,
        expected_revision=RevisionToken.of(document), business_request=business)
    payload = command.to_payload()
    assert payload["original_request"] == original and payload["business_request"] == business
    assert payload["version"] == 1 and set(payload) == {
        "version", "kind", "idempotency_key", "original_request", "original_request_digest",
        "business_request", "request_digest", "expected_revision", "authority"}
    assert command.original_request_digest == canonical_json_sha256(original, allow_nan=False)
    assert command.request_digest == canonical_json_sha256(business, allow_nan=False)
    assert command.original_request_digest != command.request_digest
    for field in ("original_request", "business_request"):
        assert json.dumps(payload[field], ensure_ascii=False) == json.dumps(
            original if field == "original_request" else business, ensure_ascii=False)


def test_direct_normalized_command_constructor_keeps_literal_v1_contract(tmp_path):
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    payload = request()
    digest = canonical_json_sha256(payload, allow_nan=False)
    token = RevisionToken.of(document)
    direct = NormalizedCommand("patch", payload["idempotency_key"], payload, digest, payload, digest,
                               token, token.authority)
    assert direct.to_payload() == NormalizedCommand.create("patch", payload, expected_revision=token).to_payload()
    for changes in ({"idempotency_key": "different"}, {"request_digest": "0" * 64},
                    {"original_request_digest": "0" * 64}):
        with pytest.raises(ValueError, match="normalized command"):
            replace(direct, **changes)
    assert not backend.native_writes


@pytest.mark.parametrize("value", [1, 1.0, True, -0.0, 0.0])
def test_equal_python_numbers_keep_their_distinct_command_json_identity(tmp_path, value):
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    original = {**request(), "literal": value}
    business = {**deepcopy(original), "literal": 1}
    command = NormalizedCommand.create("intent", original, expected_revision=RevisionToken.of(document),
                                       business_request=business)
    assert command.original_request_digest == canonical_json_sha256(original, allow_nan=False)
    assert command.request_digest == canonical_json_sha256(business, allow_nan=False)
    assert json.dumps(command.original_payload["literal"]) == json.dumps(value)


def test_non_json_command_values_fail_without_running_copy_hooks(tmp_path):
    from sciplot_core.plot_document import DocumentError

    class NotJSON:
        def __deepcopy__(self, memo):
            pytest.fail("Strict request capture must not invoke a non-JSON copy hook.")

    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    with pytest.raises(DocumentError, match="finite JSON"):
        NormalizedCommand.create("patch", {**request(), "bad": NotJSON()}, expected_revision=RevisionToken.of(document))
    assert not backend.native_writes


def test_command_value_equality_ignores_object_key_order_without_reordering_payload(tmp_path):
    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    original = request()
    reordered = dict(reversed(list(original.items())))
    reordered["changes"] = [dict(reversed(list(change.items()))) for change in original["changes"]]
    token = RevisionToken.of(document)
    first = NormalizedCommand.create("patch", original, expected_revision=token)
    second = NormalizedCommand.create("patch", reordered, expected_revision=token)
    assert first == second and first.original_request == second.original_request
    assert list(first.to_payload()["original_request"]) == list(original)
    assert list(second.to_payload()["original_request"]) == list(reordered)


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


def test_published_filesystem_index_continues_memory_repository_semantic_target(tmp_path):
    from managed_plot_helpers import request_for_source
    from test_project_lifecycle import ManagedBackend
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.project_lifecycle.repository import digest

    repo, backend = MemoryRepository(), ManagedBackend()
    app = application(backend, repo)
    created = app.create(request_for_source(tmp_path))
    plot = Path(created["plot"])
    head = repo.load_head(plot)
    native = Path(head["binding"]["document"])
    package = tmp_path / "published-snapshot"
    package.mkdir()
    snapshot = package / "Figure_A.vsz"
    snapshot.write_bytes(native.read_bytes())
    manifest = {"kind": "sciplot_managed_delivery", "version": 1, "mode": "native_snapshot",
                "managed_project_included": False, "snapshot_files": {snapshot.name: file_sha256(snapshot)},
                "items": [{"id": "figure-A", "label": "A", "scientific_hash": created["scientific_hash"],
                           "presentation_hash": created["presentation_hash"], "files": {"editable": snapshot.name},
                           "audit": {"native_sha256": file_sha256(native)}, "local_managed_continuation": {
                               "plot": str(plot), "plot_id": created["plot_id"], "revision": 0}}]}
    manifest["manifest_sha256"] = digest(manifest)
    index = package / "index.json"
    index.write_text(json.dumps(manifest))
    original = index.read_bytes()
    before = deepcopy(repo.values)
    opened = app.open(package, figure_id="figure-A")
    assert opened["plot_id"] == created["plot_id"] and opened["revision"] == 0
    assert opened["delivery_continuation"] == {"mode": "original_local_managed", "item_id": "figure-A",
        "independent_native_snapshot": str(snapshot), "portable_managed_project": False}
    assert repo.values == before and index.read_bytes() == original
    assert str(index) not in repo.values and not (plot / "head.json").exists()
    assert backend.calls == {"preview": 0, "apply": 0, "export": 1}


def test_old_rollback_and_reimport_execution_hash_is_not_a_business_digest(tmp_path):
    backend = FakeBackend(tmp_path / "native")
    document, _ = backend.initial()
    for original in ({"rollback_request": {"base_revision": 0, "target_revision": 0, "idempotency_key": "old"}},
                     {"mode": "reimport", "reimport_request": {"base_revision": 0, "decision_id": "b" * 64, "reimport": True}}):
        transaction = {"document": document, "phase": "complete", "request_hash": "a" * 64,
                       "request": {"base_revision": 0, "idempotency_key": "old", "generated_execution": True}, **original}
        untouched = deepcopy(transaction)
        assert Receipt.of(transaction).to_payload()["command_digest"] is None
        assert transaction == untouched and transaction["request_hash"] == "a" * 64
