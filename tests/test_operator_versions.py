"""Actual retained implementations, scoped drift and cache-cleared historical replay."""
from copy import deepcopy
from dataclasses import replace
import importlib
from pathlib import Path
import shutil

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document import DocumentError, seal_document
from sciplot_core.plot_transforms import builtin_executor, builtin_files, execute_node, require_builtin, resolve_transforms
from sciplot_core.plot_transforms import identity
from sciplot_core.plot_transforms.versions.catalog import LEGACY_DESCRIPTOR
from test_plot_ir import managed_example, resolved_example


CASES = {
    "select": {"columns": ["column:1"]},
    "rename": {"columns": {"column:1": {"id": "signal", "label": "Measured"}}},
    "scale": {"columns": ["column:1"], "factor": -2},
    "normalize": {"columns": ["column:1"], "method": "max_abs", "output_unit": "1"},
    "row_slice": {"start": 0, "end": 2},
    "concat_time": {"time_column": "column:0", "boundary": "next_sample", "first_origin": "zero"},
    "convert_unit": {"columns": ["column:0"], "from_unit": "s", "to_unit": "min"},
    "time_offset": {"time_column": "column:0", "offset": 2, "unit": "s"},
    "rheology_complex_viscosity": {"frequency_column": "w", "storage_column": "gp", "loss_column": "gpp",
                                     "output_column": "eta", "output_unit": "Pa s"},
}
# Recorded from actual 597fee38 execution on these generated inputs, before migration.
LEGACY_KEYS = {
    "concat_time": "4044c025ae5a7ffeb9f58669693fdb3a523f0aa7243736cec44b83ee75b5717f",
    "convert_unit": "9c94211de3210ade063f75344f99ac5b36ef1f44431a0aab0f67729f38a4058c",
    "normalize": "db890def4d4036a25794bdbdd960ad30d2ea463d1964eb33cc739b3ef23140ca",
    "rename": "4fbf99de3ea1eb428b16f77c202a2ed0ce1ba6257295847610075e831a6a5d53",
    "rheology_complex_viscosity": "dc37c63673d9fe348c664226043f4aef51d74eadaaedffe3c5f8720691be7816",
    "row_slice": "bad0a12d6d3f19c93fc0b695c24c697cd96f01cd20184b6065ef14b684338c93",
    "scale": "c916d2bc54c1ad9f68b33ffd6a16d1ab4a2c35799d23ca76df728631e188de0e",
    "select": "ad4c1f3efb25be86935e5c849ad2ec237cff4ae71c9bb9324e94527b5bbae81d",
    "time_offset": "de116236020dee41fa9f2c6b777ffc045e9a0f77f611066f920bc7749d959150",
}


LEGACY_OUTPUT_HASHES = {'concat_time': 'bb47ce1225bbfd1f1e1cfce08b3b5c9136ba5b57f1c57a0d62a39dbda249fdeb',
 'convert_unit': '24b1f1b8ec8c48a35040eac4d23b4f83c579ca700c4728cc587f207e5728928b',
 'normalize': '41db7ece0b2ccb88d3292ccc4714ecd86fb9d6672ce88a70388fff1124303a53',
 'rename': '7c95f5df1da08c8428bc990f517d5d820fbb0efd0960bfdc124839dc0632e02f',
 'rheology_complex_viscosity': 'c8c4ef1367f6454b93945489cea557a3d9b6e80e0c4482efe010b484fcfd41d2',
 'row_slice': 'ba62fd7b9a515610d6848c8a9bf0635e465d96d60eaf66f36be49dcd6ae2b289',
 'scale': '03b5b05d0e248e5e1b7c2c20d73e8443c837fe074fb3820efd17a4f5d9c8bb7c',
 'select': 'c9513a95b46a96b32daa3860b43a9d6021ba0ed17632f0feab5781c95d9abdca',
 'time_offset': '0ea5dc540b863da7fe4effbdde7e09ac1aec2f5ba01acb4799c565b4f31aeccf'}

def example(kind, *, legacy=False):
    _, _, inputs = managed_example()
    if kind == "rheology_complex_viscosity":
        inputs = {"A": {"id": "A", "columns": {
            "w": {"label": "Frequency", "unit": "rad/s", "values": [1, 2, None]},
            "gp": {"label": "Storage", "unit": "Pa", "values": [3, 6, 9]},
            "gpp": {"label": "Loss", "unit": "Pa", "values": [4, 8, 12]}},
            "provenance": inputs["A"]["provenance"]}}
    return {"id": "rheology" if kind == "rheology_complex_viscosity" else kind, "kind": kind,
            "inputs": ["A"], "output": "output", "parameters": deepcopy(CASES[kind]),
            "executor": builtin_executor() if legacy else builtin_executor(kind), "determinism": "deterministic"}, inputs


@pytest.mark.parametrize("kind", CASES)
def test_every_supported_operator_executes_retained_code_with_unchanged_old_identity(kind):
    old, inputs = example(kind, legacy=True)
    original = deepcopy(old)
    retained, key = execute_node(old, inputs)
    assert old == original and key == LEGACY_KEYS[kind]
    assert canonical_json_sha256(retained, allow_nan=False) == LEGACY_OUTPUT_HASHES[kind]
    current, _ = example(kind)
    result, new_key = execute_node(current, inputs)
    assert result["columns"] == retained["columns"]
    assert result["provenance"]["sources"] == retained["provenance"]["sources"]
    assert result["provenance"]["transforms"][-1]["details"] == retained["provenance"]["transforms"][-1]["details"]
    assert result["provenance"]["transforms"][-1]["parameters"] == retained["provenance"]["transforms"][-1]["parameters"]
    assert new_key != key and current["executor"]["operator"] == kind
    assert old["executor"] == LEGACY_DESCRIPTOR
    assert all(file_sha256(Path(path)) == sha for path, sha in builtin_files(kind, current["executor"]).items())


def test_unrelated_rheology_drift_cannot_invalidate_select_but_its_real_dependency_drift_refuses(monkeypatch):
    node, inputs = example("select")
    expected, key = execute_node(node, inputs)
    rheology, _ = example("rheology_complex_viscosity")
    rheology_path = next(path for path in builtin_files("rheology_complex_viscosity") if path.endswith("/rheology.py"))
    assert rheology_path not in builtin_files("select")
    original = identity.file_sha256
    monkeypatch.setattr(identity, "file_sha256", lambda path: "0" * 64 if str(path) == rheology_path else original(path))
    assert execute_node(node, inputs) == (expected, key)
    with pytest.raises(DocumentError, match="immutable"):
        require_builtin(rheology)
    select_path = next(path for path in builtin_files("select") if path.endswith("/columns.py"))
    monkeypatch.setattr(identity, "file_sha256", lambda path: "0" * 64 if str(path) == select_path else original(path))
    with pytest.raises(DocumentError) as caught:
        execute_node(node, inputs)
    assert caught.value.reason_code == "transform_runtime_changed"
    assert caught.value.repair["automatic_refresh"] is False


@pytest.mark.parametrize("missing", ["version", "unknown_version", "unknown_hash", "uninstalled_version", "missing_file"])
def test_missing_or_unknown_saved_implementation_refuses_before_cache_or_execution(missing, monkeypatch):
    resolved, raw = resolved_example()
    document = deepcopy(resolved["document"])
    for node in document["scientific"]["transforms"]:
        node["executor"] = builtin_executor(node["kind"])
    cache = resolve_transforms(seal_document(document), raw)["cache"]
    node = document["scientific"]["transforms"][0]
    if missing == "version":
        node["executor"].pop("version")
    elif missing == "unknown_version":
        node["executor"]["version"] = "absent"
    elif missing == "unknown_hash":
        node["executor"]["content_hash"] = "0" * 64
    elif missing == "uninstalled_version":
        monkeypatch.delitem(identity._VERSIONS, (node["kind"], "1"))
    else:
        def missing_bytes(_):
            raise FileNotFoundError("The installed implementation is absent")
        monkeypatch.setattr(identity, "file_sha256", missing_bytes)
    frozen_cache = deepcopy(cache)
    with pytest.raises(DocumentError):
        resolve_transforms(seal_document(document), raw, cache=cache,
                           before_execute=lambda *_: pytest.fail("Unavailable science cannot be started"))
    assert cache == frozen_cache


def install_generated_version(monkeypatch, tmp_path, kind):
    """A trusted test installation, never a public registration or request field."""
    from sciplot_core.plot_transforms import versions

    old = identity._VERSIONS[kind, "1"]
    name = "generated_newer_" + kind
    module = tmp_path / (name + ".py")
    original_module, original_function = old.entry.split(":")
    module.write_text(f"from .{original_module} import {original_function} as original\n"
                      "def run(node, source):\n"
                      "    result, details = original(node, source)\n"
                      "    return result, {**details, 'installed_version_canary': 'newer'}\n")
    module_sha = file_sha256(module)
    monkeypatch.setattr(versions, "__path__", [*versions.__path__, str(tmp_path)])
    files = (*old.files, (module.name, module_sha))
    payload = {"operator": kind, "version": "2", "entry": name + ":run", "runtime": old.runtime,
               "multiple_inputs": old.multiple_inputs, "files": dict(files)}
    new = replace(old, version="2", content_hash=canonical_json_sha256(payload, allow_nan=False),
                  entry=name + ":run", files=files)
    original_files = identity.builtin_files
    def installed_files(operator=None, executor=None):
        if operator == kind and executor in (None, new.descriptor()):
            return {**{str(Path(identity.__file__).with_name("versions") / path): sha for path, sha in old.files},
                    str(module): module_sha}
        return original_files(operator, executor)
    monkeypatch.setattr(identity, "builtin_files", installed_files)
    monkeypatch.setitem(identity._VERSIONS, (kind, "2"), new)
    monkeypatch.setitem(identity._CURRENT, kind, "2")
    importlib.invalidate_caches()
    return new


@pytest.mark.parametrize("installed_kind", ["select", "rheology_complex_viscosity"])
def test_installing_actual_new_related_or_unrelated_code_keeps_old_versions_executable(tmp_path, monkeypatch, installed_kind):
    old, inputs = example("select")
    legacy, _ = example("select", legacy=True)
    original = execute_node(old, inputs)
    legacy_result = execute_node(legacy, inputs)
    newer = install_generated_version(monkeypatch, tmp_path, installed_kind)
    assert execute_node(old, inputs) == original
    assert execute_node(legacy, inputs) == legacy_result
    assert builtin_executor(installed_kind) == newer.descriptor()
    node, data = example(installed_kind)
    result, _ = execute_node(node, data)
    assert result["provenance"]["transforms"][-1]["details"]["installed_version_canary"] == "newer"


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("installed_kind", ["normalize", "rheology_complex_viscosity"])
def test_cache_and_ir_deletion_reconstruct_saved_science_after_version_install(tmp_path, monkeypatch, legacy, installed_kind):
    from managed_plot_helpers import request_for_source
    from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
    from sciplot_core.plot_engine.managed_state import make_binding, resolved_ir
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
    from sciplot_core.project_lifecycle.context import repository_scope
    from sciplot_core.project_lifecycle.repository import FileProjectRepository
    from contextlib import nullcontext

    wire = request_for_source(tmp_path)
    if not legacy:
        for node in wire["data_binding"]["transforms"]:
            node["executor"] = builtin_executor(node["kind"])
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="cold-history")
    document = resolved_metadata(document, rule_id=wire["rule_id"], executors={})
    root = tmp_path / "semantic"
    repo = FileProjectRepository(lease=lambda _: nullcontext())
    with repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
        original, first = resolve_science(root, document)
        binding = make_binding(root, original, output=tmp_path / "output")
        ir = resolved_ir(root, original)
        original_bytes = deepcopy(original)
        assert first["executed"] and list((root / "transform-cache").glob("*.result.json"))
        shutil.rmtree(root / "transform-cache")
        shutil.rmtree(root / "ir")
        install_generated_version(monkeypatch, tmp_path, installed_kind)
        rebuilt, actual = resolve_science(root, original)
        assert actual["executed"] == first["executed"] and actual["reused"] == []
        assert rebuilt == original_bytes and rebuilt["scientific_hash"] == original["scientific_hash"]
        assert resolved_ir(root, rebuilt) == ir
        assert not Path(binding["ir_path"]).exists()  # No read/reseal silently recreated artifacts.
        assert original == original_bytes


def test_mutating_an_installed_version_in_place_refuses_without_blessing_new_bytes(tmp_path, monkeypatch):
    old, inputs = example("select")
    expected = execute_node(old, inputs)
    newer = install_generated_version(monkeypatch, tmp_path, "select")
    current = {**old, "executor": newer.descriptor()}
    execute_node(current, inputs)
    module = tmp_path / (newer.entry.split(":")[0] + ".py")
    module.write_text(module.read_text() + "\n# drift after installation\n")
    with pytest.raises(DocumentError) as caught:
        execute_node(current, inputs)
    assert caught.value.reason_code == "transform_runtime_changed"
    assert caught.value.repair["automatic_refresh"] is False
    assert builtin_executor("select") == newer.descriptor()
    assert execute_node(old, inputs) == expected


@pytest.mark.parametrize("partial", [False, True])
def test_old_complete_pin_fingerprint_uses_retained_bytes_without_rewriting_history(tmp_path, partial):
    from contextlib import nullcontext
    from managed_plot_helpers import request_for_source
    from sciplot_core.plot_engine.builtin_history import fingerprint_for_read
    from sciplot_core.plot_engine.current import changed_inputs
    from sciplot_core.plot_engine.managed_backend import ManagedBackend
    from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
    from sciplot_core.plot_engine.managed_state import make_binding
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms.versions.catalog import LEGACY_ORIGINAL_PATHS
    from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
    from sciplot_core.project_lifecycle.context import repository_scope
    from sciplot_core.project_lifecycle.repository import FileProjectRepository

    wire = request_for_source(tmp_path)
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="old-pin-history")
    document = resolved_metadata(document, rule_id=wire["rule_id"], executors={})
    root = tmp_path / "semantic"
    repo = FileProjectRepository(lease=lambda _: nullcontext())
    with repository_scope(repo, capabilities=COMPATIBILITY_CAPABILITIES):
        resolved, _ = resolve_science(root, document)
        binding = make_binding(root, resolved, output=tmp_path / "output")
        pins = {str(tmp_path / "historic-install" / relative): sha for relative, sha in LEGACY_ORIGINAL_PATHS.items()}
        if partial:
            pins.pop(next(path for path in pins if path.endswith("/lineage.py")))
        binding["fingerprint"]["files"] = {wire["data_binding"]["data_sources"][0]["path"]:
                                           wire["data_binding"]["data_sources"][0]["sha256"], **pins}
        original = deepcopy(binding)
        model = Path(binding["canonical_document"])
        before = model.read_bytes(), model.stat().st_mtime_ns
        expected = fingerprint_for_read(binding)
        backend = ManagedBackend.__new__(ManagedBackend)  # Fingerprinting initializes no renderer.
        if partial:
            assert expected == binding["fingerprint"] and changed_inputs(backend, binding)
        else:
            assert not set(pins) & set(expected["files"])
            assert set(builtin_files()) <= set(expected["files"])
            assert changed_inputs(backend, binding) == []
        assert binding == original and (model.read_bytes(), model.stat().st_mtime_ns) == before


@pytest.mark.parametrize("dependency", ["columns.py", "datasets.py", "wire.py", "hashing.py", "schema.py"])
def test_real_saved_dependency_drift_refuses_even_a_matching_cached_result(dependency, monkeypatch):
    resolved, raw = resolved_example()
    document = deepcopy(resolved["document"])
    for node in document["scientific"]["transforms"]:
        node["executor"] = builtin_executor(node["kind"])
    document = seal_document(document)
    ready = resolve_transforms(document, raw)
    cache = deepcopy(ready["cache"])
    path = next(path for path in builtin_files("normalize") if path.endswith("/" + dependency))
    original = identity.file_sha256
    monkeypatch.setattr(identity, "file_sha256", lambda candidate: "0" * 64 if str(candidate) == path else original(candidate))
    with pytest.raises(DocumentError) as caught:
        resolve_transforms(document, raw, cache=cache,
                           before_execute=lambda *_: pytest.fail("Drift cannot execute through a matching cache"))
    assert caught.value.reason_code == "transform_runtime_changed"
    assert cache == ready["cache"]


def test_registered_operator_closures_include_real_imports_and_no_mutable_numerical_owner():
    import ast

    root = Path(identity.__file__).with_name("versions")
    for implementation in identity._VERSIONS.values():
        payload = {"operator": implementation.operator, "version": implementation.version,
                   "entry": implementation.entry, "runtime": implementation.runtime,
                   "multiple_inputs": implementation.multiple_inputs, "files": dict(implementation.files)}
        assert canonical_json_sha256(payload, allow_nan=False) == implementation.content_hash
        names = set(dict(implementation.files))
        for relative in names:
            path = root / relative
            for statement in ast.walk(ast.parse(path.read_text())):
                if isinstance(statement, ast.ImportFrom):
                    if statement.level:
                        assert statement.level == 1
                        modules = [statement.module] if statement.module else [alias.name for alias in statement.names]
                        assert all(str(Path(relative).parent / (module + ".py")) in names for module in modules)
                    elif statement.module and statement.module.startswith("sciplot_core"):
                        assert statement.module == "sciplot_core.plot_document.errors"
                        assert {alias.name for alias in statement.names} <= {"DocumentError", "fail"}


def test_historical_descriptor_recognizes_the_exact_original_seventeen_file_identity():
    from sciplot_core.plot_transforms.versions.catalog import LEGACY_ORIGINAL_FILES, LEGACY_ORIGINAL_PATHS

    assert len(LEGACY_ORIGINAL_FILES) == len(LEGACY_ORIGINAL_PATHS) == 17
    assert canonical_json_sha256(LEGACY_ORIGINAL_FILES, allow_nan=False) == LEGACY_DESCRIPTOR["content_hash"]
    assert {Path(path).name: sha for path, sha in LEGACY_ORIGINAL_PATHS.items()} == LEGACY_ORIGINAL_FILES
    assert builtin_executor() == LEGACY_DESCRIPTOR


def test_historical_bundle_alias_cannot_be_retargeted_by_reusing_a_version_number(tmp_path, monkeypatch):
    old, inputs = example("select", legacy=True)
    newer = install_generated_version(monkeypatch, tmp_path, "select")
    payload = {"operator": newer.operator, "version": "1", "entry": newer.entry,
               "runtime": newer.runtime, "multiple_inputs": newer.multiple_inputs, "files": dict(newer.files)}
    replacement = replace(newer, version="1", content_hash=canonical_json_sha256(payload, allow_nan=False))
    monkeypatch.setitem(identity._VERSIONS, ("select", "1"), replacement)
    with pytest.raises(DocumentError) as caught:
        execute_node(old, inputs)
    assert caught.value.reason_code == "transform_executor_unavailable"
    assert caught.value.repair["automatic_refresh"] is False
    monkeypatch.delitem(identity._VERSIONS, ("select", "1"))
    with pytest.raises(DocumentError):
        execute_node(old, inputs)


def test_executor_wire_bridge_preserves_original_parameter_acceptance_and_rejection():
    from sciplot_core.plot_transforms.versions.v1 import node_contract, schema as original

    for kind in CASES:
        legacy, _ = example(kind, legacy=True)
        current, _ = example(kind)
        checked = node_contract.validate_node(current)
        original_checked = original.validate_node(legacy)
        assert {key: value for key, value in checked.items() if key != "executor"} == {
            key: value for key, value in original_checked.items() if key != "executor"}
        assert checked["executor"] == current["executor"]
        for value in (legacy, current):
            invalid = deepcopy(value)
            invalid["parameters"]["unsupported"] = True
            with pytest.raises(DocumentError) as actual:
                node_contract.validate_node(invalid)
            projected = deepcopy(invalid)
            projected["executor"] = legacy["executor"]
            with pytest.raises(DocumentError) as expected:
                original.validate_node(projected)
            assert actual.value.reason_code == expected.value.reason_code
            assert actual.value.issues == expected.value.issues
