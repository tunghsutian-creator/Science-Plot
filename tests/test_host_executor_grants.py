"""Real synthetic executor canaries separate host authority from request identity."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import sys

import anyio
import pytest

from managed_plot_helpers import patch, request_for_source
from test_plot_ir import managed_example
from test_project_lifecycle import ManagedBackend, application

from sciplot_core import cli
from sciplot_core.host_grants import (
    EXECUTE_TRANSFORM, HostRegistry, SourceScope, admit_registration,
    execution_context, using_host_registry,
)
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_transforms import ExternalExecutor, execute_node
from sciplot_core.project_lifecycle.repository import FileProjectRepository


def setup(directory):
    directory = directory.resolve()
    source = directory / "A.csv"
    source.write_text("Time,Signal\ns,V\n0,2\n1,\n2,4\n")
    canary = directory / "process-and-outbound-attempt.txt"
    script = directory / "executor.py"
    script.write_text("""import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--response');a=p.parse_args()
with Path(CANARY).open('a') as f:f.write('execution attempted\\n')
r=json.loads(Path(a.request).read_text());c=r['input']['columns']
for name in r['parameters']['columns']:
    c[name]['values']=[None if v is None else v*2 for v in c[name]['values']]
Path(a.response).write_text(json.dumps({'kind':'sciplot_transform_response','schema_version':1,
    'request_sha256':r['request_sha256'],'columns':c}))
""".replace("CANARY", repr(str(canary))))
    schema = {"type": "object", "properties": {"columns": {"type": "array", "items": {"type": "string"}}},
              "required": ["columns"], "additionalProperties": False}
    executor = ExternalExecutor(Path(sys.executable), script, schema)
    node = {"id": "external-A", "kind": "external", "inputs": ["A"], "output": "A-normalized",
            "parameters": {"columns": ["column:1"]}, "executor": executor.descriptor("fixed"), "determinism": "deterministic"}
    scope = SourceScope.local_file("A", source)
    _, _, datasets = managed_example()
    datasets["A"]["provenance"]["sources"][0]["sha256"] = scope.sha256
    return HostRegistry(directory / "host-private/grants.json"), executor, node, scope, datasets, canary


def grant(store, executor, scope):
    store.grant("fixed", executor.to_dict("fixed"), [scope], action=EXECUTE_TRANSFORM)


def test_request_registration_cannot_authorize_a_process_or_outbound_attempt(tmp_path):
    store, executor, node, scope, datasets, canary = setup(tmp_path)
    with using_host_registry(store), execution_context([scope]), pytest.raises(DocumentError) as error:
        execute_node(node, datasets, external_executors={"fixed": executor})
    assert error.value.reason_code == "host_executor_ungranted"
    assert not canary.exists() and not store.path.exists()


def test_trusted_local_grant_runs_exact_code_and_preserves_scientific_input(tmp_path):
    store, executor, node, scope, datasets, canary = setup(tmp_path)
    grant(store, executor, scope)
    original = deepcopy(datasets)
    with using_host_registry(store), execution_context([scope]):
        result, _ = execute_node(node, datasets, external_executors={"fixed": executor})
    assert result["columns"]["column:1"]["values"] == [4, None, 8]
    assert result["columns"]["column:1"]["unit"] == "V" and datasets == original
    assert canary.read_text().splitlines() == ["execution attempted"]
    assert store.path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("field", ["actions", "sources", "host_registry", "allow_network", "timeout_seconds"])
def test_request_fields_never_expand_a_host_grant(tmp_path, field):
    store, executor, node, scope, _, canary = setup(tmp_path)
    grant(store, executor, scope)
    registration = executor.to_dict("fixed")
    wire = {**registration, field: 120 if field == "timeout_seconds" else ["all"]}
    document = {"scientific": {"data_sources": [scope.to_dict()], "transforms": [node]}}
    before = store.path.read_bytes()
    with using_host_registry(store), pytest.raises(DocumentError) as error:
        admit_registration(document, "fixed", wire)
    assert error.value.reason_code == "host_executor_registration_mismatch"
    assert store.path.read_bytes() == before and not canary.exists()


@pytest.mark.parametrize("field", ["source_id", "path", "sha256"])
def test_every_actual_source_fact_is_in_the_explicit_scope(tmp_path, field):
    store, executor, node, scope, datasets, canary = setup(tmp_path)
    grant(store, executor, scope)
    other = tmp_path / "same-bytes-other-source.csv"
    other.write_bytes(Path(scope.path).read_bytes())
    values = scope.to_dict()
    values[field] = {"source_id": "B", "path": str(other.resolve()), "sha256": "0" * 64}[field]
    with using_host_registry(store), execution_context([SourceScope.of(values)]), pytest.raises(DocumentError):
        execute_node(node, datasets, external_executors={"fixed": executor})
    assert not canary.exists()


def test_declared_action_does_not_override_host_action_refusal(tmp_path):
    store, executor, node, scope, datasets, canary = setup(tmp_path)
    grant(store, executor, scope)
    value = json.loads(store.path.read_text())
    value["grants"][0]["actions"] = []
    store.path.write_text(json.dumps(value))
    with using_host_registry(store), execution_context([scope]), pytest.raises(DocumentError) as error:
        execute_node(node, datasets, external_executors={"fixed": executor})
    assert error.value.reason_code == "host_executor_action_denied" and not canary.exists()


def test_registry_alias_or_public_file_cannot_become_a_trusted_grant(tmp_path):
    store, executor, node, scope, datasets, canary = setup(tmp_path)
    grant(store, executor, scope)
    store.path.chmod(0o644)
    with using_host_registry(store), execution_context([scope]), pytest.raises(DocumentError) as error:
        execute_node(node, datasets, external_executors={"fixed": executor})
    assert error.value.reason_code == "host_registry_untrusted" and not canary.exists()


@pytest.mark.parametrize("configuration", ["invalid-json", "missing-identity"])
def test_malformed_host_configuration_refuses_with_no_process(tmp_path, configuration):
    store, executor, node, scope, datasets, canary = setup(tmp_path)
    grant(store, executor, scope)
    value = json.loads(store.path.read_text())
    value["grants"][0]["registration"].pop("identity")
    store.path.write_text("{" if configuration == "invalid-json" else json.dumps(value))
    with using_host_registry(store), execution_context([scope]), pytest.raises(DocumentError) as error:
        execute_node(node, datasets, external_executors={"fixed": executor})
    assert error.value.reason_code == "host_registry_invalid" and not canary.exists()


def test_transformed_input_requires_every_original_source_scope(tmp_path):
    from sciplot_core.plot_transforms import builtin_executor

    store, executor, node, scope, _, canary = setup(tmp_path)
    other = tmp_path / "B.csv"
    other.write_bytes(Path(scope.path).read_bytes())
    scope_b = SourceScope.local_file("B", other)
    combined = {"id": "concat", "kind": "concat_time", "inputs": ["A", "B"], "output": "combined",
                "parameters": {"time_column": "column:0", "boundary": "preserve_endpoint", "first_origin": "preserve"},
                "executor": builtin_executor(), "determinism": "deterministic"}
    node = {**node, "inputs": ["combined"]}
    document = {"scientific": {"data_sources": [scope.to_dict(), scope_b.to_dict()], "transforms": [combined, node]}}
    grant(store, executor, scope)
    with using_host_registry(store), pytest.raises(DocumentError) as error:
        admit_registration(document, "fixed", {"identity": executor.descriptor("fixed")})
    assert error.value.reason_code == "host_executor_source_denied" and not canary.exists()
    store.grant("fixed", executor.to_dict("fixed"), [scope, scope_b], action=EXECUTE_TRANSFORM)
    with using_host_registry(store):
        assert admit_registration(document, "fixed", {"identity": executor.descriptor("fixed")}) == executor.to_dict("fixed")
    assert not canary.exists()


def managed_request(directory):
    store, executor, node, _, _, canary = setup(directory)
    executor.script.write_text(executor.script.read_text().replace(
        "v*2 for v in c[name]['values']", "v/max(x for x in c[name]['values'] if x is not None) for v in c[name]['values']"
    ).replace("Path(a.response).write_text", "    c[name]['unit']='1'\nPath(a.response).write_text"))
    node["executor"] = executor.descriptor("fixed")
    request = request_for_source(directory)
    scope = SourceScope.local_file("A", Path(request["data_binding"]["data_sources"][0]["path"]))
    request["data_binding"]["transforms"] = [node]
    request["scientific_executors"] = {"fixed": {"identity": executor.descriptor("fixed")}}
    repo = FileProjectRepository(lease=lambda _: nullcontext())
    return store, executor, scope, request, application(ManagedBackend(), repo), canary


def test_create_and_rpc_cannot_mint_grants_before_journal_allocation(tmp_path):
    from sciplot_core.plot_protocol import rpc

    store, _, _, wire, app, canary = managed_request(tmp_path)
    with using_host_registry(store):
        response = rpc.handle(app, {"jsonrpc": "2.0", "id": 1, "method": "plot.create", "params": {"request": wire}})
    assert response["error"]["data"]["reason_code"] == "host_executor_ungranted"
    assert not canary.exists() and not list(tmp_path.rglob("managed-creation.json"))


def test_completed_creation_replay_remains_readable_after_revocation_without_execution(tmp_path):
    store, executor, scope, wire, app, canary = managed_request(tmp_path)
    grant(store, executor, scope)
    with using_host_registry(store):
        created = app.create(wire)
        root = Path(created["plot"])
        original = app.repository.load_head(root)
        count = canary.read_bytes()
        store.revoke("fixed")
        replayed = app.create(wire)
        described = app.describe(root)
    assert replayed["ready_to_use"] and described["revision"] == 0
    assert app.repository.load_head(root) == original and canary.read_bytes() == count


def test_executor_patch_needs_a_host_grant_and_keeps_old_seals_on_refusal(tmp_path):
    store, executor, scope, wire, app, canary = managed_request(tmp_path)
    grant(store, executor, scope)
    with using_host_registry(store):
        created = app.create(wire)
        root = Path(created["plot"])
        before = app.repository.load_head(root)
        count = canary.read_bytes()
        store.revoke("fixed")
        update = patch(created, "ungranted-registration", "executor.registration", executor.to_dict("fixed"), "executor:fixed", scientific=True)
        with pytest.raises(DocumentError) as error:
            app.patch(root, update)
    assert error.value.reason_code == "host_executor_ungranted"
    assert app.repository.load_head(root) == before and canary.read_bytes() == count


def test_cache_read_is_not_a_grant_and_cold_execution_refuses_before_start_marker(tmp_path):
    from sciplot_core.plot_engine.managed_resolution import resolve_science
    from sciplot_core.project_lifecycle.context import repository_scope

    store, executor, scope, wire, app, canary = managed_request(tmp_path)
    grant(store, executor, scope)
    with using_host_registry(store):
        created = app.create(wire)
        root = Path(created["plot"])
        original = app.repository.load_head(root)
        count = canary.read_bytes()
        store.revoke("fixed")
        with repository_scope(app.repository, capabilities=app.capabilities):
            _, result = resolve_science(root, original["document"])
            assert result["reused"] == ["external-A"] and not result["executed"]
            cache = root / "transform-cache"
            for path in cache.glob("*.json"):
                path.unlink()  # Only this synthetic case's disposable transform cache.
            with pytest.raises(DocumentError) as error:
                resolve_science(root, original["document"])
            assert error.value.reason_code == "host_executor_ungranted"
            assert not list(cache.glob("*.started.json"))
    assert app.repository.load_head(root) == original and canary.read_bytes() == count


def test_unknown_external_outcome_never_reexecutes_even_with_a_valid_host_grant(tmp_path):
    from sciplot_core.project_lifecycle.errors import EngineError

    store, executor, scope, wire, app, canary = managed_request(tmp_path)
    executor.script.write_text(executor.script.read_text().replace(
        "r=json.loads", "import time;time.sleep(2)\nr=json.loads"))
    executor = ExternalExecutor(executor.executable, executor.script, executor.parameter_schema, timeout_seconds=.2)
    wire["data_binding"]["transforms"][0]["executor"] = executor.descriptor("fixed")
    wire["scientific_executors"]["fixed"] = {"identity": executor.descriptor("fixed")}
    grant(store, executor, scope)
    with using_host_registry(store):
        with pytest.raises(DocumentError) as first:
            app.create(wire)
        assert first.value.reason_code == "transform_external_timeout"
        count = canary.read_bytes()
        with pytest.raises(EngineError) as retry:
            app.create(wire)
        assert retry.value.reason_code == "external_transform_outcome_unknown"
    assert canary.read_bytes() == count and count.splitlines() == [b"execution attempted"]


def test_environment_labels_cannot_enable_ungranted_execution(tmp_path, monkeypatch):
    store, executor, node, scope, datasets, canary = setup(tmp_path)
    for key in ("SCIPLOT_ALLOW_EXTERNAL_EXECUTORS", "SCIPLOT_HOST_GRANTS", "SCIPLOT_TRUSTED_EXECUTOR"):
        monkeypatch.setenv(key, "1")
    with using_host_registry(store), execution_context([scope]), pytest.raises(DocumentError) as error:
        execute_node(node, datasets, external_executors={"fixed": executor})
    assert error.value.reason_code == "host_executor_ungranted" and not canary.exists()


def test_canonical_local_entry_grants_and_revokes_but_mcp_and_rpc_have_no_admin(tmp_path, capsys):
    from sciplot_core.mcp_server.server import Adapter
    from sciplot_core.plot_protocol import rpc

    store, executor, _, scope, _, canary = setup(tmp_path)
    registration = tmp_path / "registration.json"
    registration.write_text(json.dumps(executor.to_dict("fixed")))
    assert cli.main(["host", "grant", "--id", "fixed", "--registration", str(registration),
                     "--action", EXECUTE_TRANSFORM, "--source", "A=" + scope.path,
                     "--registry", str(store.path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["grants"][0]["registration"] == executor.to_dict("fixed")
    assert not canary.exists()
    assert not any("host" in name or "grant" in name for name in Adapter().tools)
    async def reject():
        return await Adapter().call("sciplot_host_grant", {"registry": str(store.path)})
    rejected = anyio.run(reject)
    assert rejected.is_error
    with pytest.raises(rpc.ProtocolError):
        rpc.validate_params("host.grant", {"registration": executor.to_dict("fixed")})
    assert cli.main(["host", "revoke", "--id", "fixed", "--registry", str(store.path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["grants"] == [] and not canary.exists()
