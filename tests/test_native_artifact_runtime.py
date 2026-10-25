"""Finite native metadata witnesses never weaken scientific source resolution."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.source_locations import resolve_source_path, selected_source_resolver, source_location_scope
from sciplot_core.project_store import ProjectConflict, ProjectStoreError
from sciplot_core.project_store.io import sha
from sciplot_core.project_store.native_artifacts import NativeArtifactInput, NativeArtifactOutput, native_artifact_runtime, resolve_native_artifact
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.project_store.worker_binding import native_runtime_binding, worker_project_runtime

from test_project_store import fixture_store


def metadata_fixture(tmp_path):
    store, before = fixture_store(tmp_path)
    cache = store.root / ".sciplot_store/semantic-derived" / ("a" * 32)
    cache.mkdir(parents=True, mode=0o700)
    ir = cache / "plot-ir-exact.json"
    ir.write_bytes(b'{"ir_hash":"reviewed","scientific_hash":"unchanged"}')
    ir.chmod(0o600)
    document, preview = cache / "document.vsz", cache / "preview.png"
    argv = ["compile-plot-ir", str(ir), str(document), "--preview", str(preview)]
    inputs = (NativeArtifactInput("ir", ir, sha(ir.read_bytes()), 0o600),)
    outputs = (NativeArtifactOutput("document", document), NativeArtifactOutput("preview", preview))
    return store, before, ir, document, preview, argv, inputs, outputs


def test_metadata_ir_without_capability_is_refused_before_native_dispatch(tmp_path, monkeypatch):
    from sciplot_core.veusz_worker import cli, managed
    store, before, ir, document, preview, argv, _, _ = metadata_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(managed, "compile_plot_ir", lambda *_a: calls.append("native forbidden"))
    with project_runtime(store), pytest.raises((ProjectStoreError, ProjectConflict)):
        cli._execute(argv)
    assert not calls and not document.exists() and not preview.exists() and store.snapshot() == before
    assert ir.read_bytes() == b'{"ir_hash":"reviewed","scientific_hash":"unchanged"}'


def test_cli_resolves_only_exact_metadata_roles_preserving_sources_and_project_head(tmp_path, monkeypatch):
    from sciplot_core.veusz_worker import cli, managed
    store, before, ir, document, preview, argv, inputs, outputs = metadata_fixture(tmp_path)
    calls = []
    def compile_exact(actual_ir, actual_document, actual_preview):
        calls.append((actual_ir, actual_document, actual_preview))
        assert (actual_ir, actual_document, actual_preview) == (ir, document, preview)
        assert resolve_source_path(store.root / "raw/same.csv").read_bytes() == b"x,y\n1,2\n"
        document.write_bytes(b"controlled native placeholder")
        preview.write_bytes(b"controlled preview placeholder")
        return {"ir_hash": "reviewed", "scientific_hash": "unchanged"}
    monkeypatch.setattr(managed, "compile_plot_ir", compile_exact)
    with project_runtime(store), native_artifact_runtime(argv, inputs=inputs, outputs=outputs):
        assert cli._execute(argv) == 0
    assert calls == [(ir, document, preview)] and store.snapshot() == before
    with project_runtime(store), pytest.raises((ProjectStoreError, ProjectConflict)):
        resolve_native_artifact(ir, role="ir")
    assert selected_source_resolver() is None


@pytest.mark.parametrize("failure", ["input-sha", "input-mode", "symlink", "hardlink", "parent-alias", "input-directory",
    "existing-document", "existing-preview", "missing-canonical", "output-alias", "output-hardlink", "output-parent-mode", "missing-parent"])
def test_host_witnesses_refuse_changed_inputs_aliases_and_existing_outputs(tmp_path, failure):
    store, _before, ir, document, preview, argv, inputs, outputs = metadata_fixture(tmp_path)
    if failure == "input-sha":
        ir.write_bytes(b"changed after IR validation")
    elif failure == "input-mode":
        ir.chmod(0o644)
    elif failure == "input-directory":
        ir.unlink()
        ir.mkdir()
    elif failure in {"symlink", "hardlink"}:
        ir.unlink()
        if failure == "symlink":
            ir.symlink_to(store.root / "studio/spec.json")
        else:
            ir.hardlink_to(store.root / "studio/spec.json")
    elif failure == "parent-alias":
        parent = ir.parent
        actual = parent.with_name("relocated")
        parent.rename(actual)
        parent.symlink_to(actual, target_is_directory=True)
    elif failure == "existing-document":
        document.write_bytes(b"old audited native")
    elif failure == "existing-preview":
        preview.write_bytes(b"old unknown preview must survive")
    elif failure == "missing-canonical":
        document = store.root / "studio/document.vsz"
        document.unlink()
        argv[2] = str(document)
        outputs = (NativeArtifactOutput("document", document), outputs[1])
    elif failure == "output-alias":
        document.symlink_to(store.root / "studio/document.vsz")
    elif failure == "output-hardlink":
        document.hardlink_to(store.root / "studio/document.vsz")
    elif failure == "output-parent-mode":
        document.parent.chmod(0o777)
    else:
        document = document.parent / "not-created/document.vsz"
        argv[2] = str(document)
        outputs = (NativeArtifactOutput("document", document), outputs[1])
    with project_runtime(store), pytest.raises((ProjectStoreError, ProjectConflict, OSError)):
        with native_artifact_runtime(argv, inputs=inputs, outputs=outputs):
            pytest.fail("Unverified metadata input or replacing output admitted")
    if failure == "existing-preview":
        assert preview.read_bytes() == b"old unknown preview must survive"


@pytest.mark.parametrize("failure", ["role", "direction", "path", "sha", "source-id", "input-drift", "output-created", "parent-replaced", "argv"])
def test_selected_metadata_witnesses_are_revalidated_and_role_bound(tmp_path, monkeypatch, failure):
    from sciplot_core.veusz_worker import cli
    store, before, ir, document, preview, argv, inputs, outputs = metadata_fixture(tmp_path)
    with project_runtime(store), native_artifact_runtime(argv, inputs=inputs, outputs=outputs):
        with pytest.raises((ProjectStoreError, ProjectConflict, OSError)):
            if failure == "role":
                resolve_native_artifact(ir, role="document")
            elif failure == "direction":
                resolve_native_artifact(ir, role="ir", output=True)
            elif failure == "path":
                resolve_native_artifact(ir.parent / "other.json", role="ir")
            elif failure == "sha":
                resolve_native_artifact(ir, role="ir", expected_sha256="0" * 64)
            elif failure == "source-id":
                identity = before["files"]["raw/same.csv"]["file_id"]
                resolve_native_artifact(ir, role="ir", source_id=identity, expected_sha256=inputs[0].sha256)
            elif failure == "input-drift":
                ir.write_bytes(b"raced input")
                resolve_native_artifact(ir, role="ir")
            elif failure == "output-created":
                document.write_bytes(b"concurrent output")
                resolve_native_artifact(document, role="document", output=True)
            elif failure == "parent-replaced":
                ir.parent.rename(ir.parent.with_name("old-cache"))
                ir.parent.mkdir(mode=0o700)
                resolve_native_artifact(document, role="document", output=True)
            else:
                cli._execute([*argv, "--preview", str(preview)])


@pytest.mark.parametrize("failure", ["role", "wrong-argv", "duplicate-role", "same-file", "missing-input", "missing-output",
    "no-project", "custom-resolver"])
def test_only_a_trusted_project_host_can_bind_closed_exact_argument_witnesses(tmp_path, failure):
    store, _before, ir, _document, _preview, argv, inputs, outputs = metadata_fixture(tmp_path)
    if failure == "role":
        inputs = (NativeArtifactInput("request", ir, inputs[0].sha256, inputs[0].mode),)
    elif failure == "wrong-argv":
        argv[1] = str(ir.parent / "other.json")
    elif failure == "duplicate-role":
        inputs *= 2
    elif failure == "same-file":
        outputs = (NativeArtifactOutput("document", ir),)
    elif failure == "missing-input":
        inputs = ()
    elif failure == "missing-output":
        outputs = outputs[:1]
    if failure == "no-project":
        context = source_location_scope(None)
    elif failure == "custom-resolver":
        class CustomResolver:
            def resolve_path(self, value, **_kwargs):return Path(value)
            def literal_path(self, value):return str(value)
        context = source_location_scope(CustomResolver())
    else:
        context = project_runtime(store)
    with context, pytest.raises((ProjectStoreError, ProjectConflict)):
        with native_artifact_runtime(argv, inputs=inputs, outputs=outputs):
            pytest.fail("Invalid host metadata scope admitted")


@pytest.mark.parametrize("failure", ["unknown-field", "wrong-role", "wrong-mode", "wrong-sha", "parent-identity", "argv", "host-parent"])
def test_worker_rejects_unclosed_tampered_and_wrong_invocation_metadata(tmp_path, monkeypatch, failure):
    store, _before, ir, _document, _preview, argv, inputs, outputs = metadata_fixture(tmp_path)
    with project_runtime(store), native_artifact_runtime(argv, inputs=inputs, outputs=outputs), native_runtime_binding(argv) as reference:
        monkeypatch.setattr(os, "getppid", os.getpid)
        path = Path(reference["path"])
        value = json.loads(path.read_bytes())
        cap = value["project"]["native_artifacts"]
        if failure == "unknown-field":
            cap["allow_parent"] = str(ir.parent)
        elif failure == "wrong-role":
            cap["inputs"][0]["role"] = "document"
        elif failure == "wrong-mode":
            cap["inputs"][0]["mode"] = 0o644
        elif failure == "wrong-sha":
            cap["inputs"][0]["sha256"] = "0" * 64
        elif failure == "parent-identity":
            cap["outputs"][0]["parent"]["inode"] += 1
        elif failure == "argv":
            argv = [*argv, "--unbound"]
        else:
            value["parent_pid"] += 1
        data = json.dumps(value).encode()
        path.chmod(0o600)
        path.write_bytes(data)
        reference["sha256"] = sha(data)
        with pytest.raises((ProjectStoreError, ProjectConflict)):
            with worker_project_runtime(reference, argv):
                pytest.fail("Unbound metadata witness reached native code")


def test_worker_metadata_scope_clears_for_unbound_request_and_after_failure(tmp_path, monkeypatch):
    store, _before, ir, _document, _preview, argv, inputs, outputs = metadata_fixture(tmp_path)
    with project_runtime(store), native_artifact_runtime(argv, inputs=inputs, outputs=outputs), native_runtime_binding(argv) as reference:
        monkeypatch.setattr(os, "getppid", os.getpid)
        with pytest.raises(ValueError, match="controlled"):
            with worker_project_runtime(reference, argv):
                assert resolve_native_artifact(ir, role="ir") == ir
                raise ValueError("controlled worker exception")
        with worker_project_runtime(None, argv):
            assert selected_source_resolver() is None
    with project_runtime(store), pytest.raises((ProjectStoreError, ProjectConflict)):
        resolve_native_artifact(ir, role="ir")


@pytest.mark.parametrize("command", ["inspect-plot-ir", "preview-document", "export-document", "inspect-document-state"])
def test_inspection_preview_and_export_have_exact_closed_file_roles(tmp_path, monkeypatch, command):
    store, _before, ir, document, preview, _argv, ir_inputs, _outputs = metadata_fixture(tmp_path)
    document.write_bytes(b"known native metadata bytes")
    document.chmod(0o600)
    document_input = NativeArtifactInput("document", document, sha(document.read_bytes()), 0o600)
    outputs = ()
    if command == "inspect-plot-ir":
        argv, inputs = [command, str(ir), str(document)], (*ir_inputs, document_input)
    elif command == "preview-document":
        argv, inputs = [command, str(document), "--out", str(preview)], (document_input,)
        outputs = (NativeArtifactOutput("out", preview),)
    elif command == "export-document":
        argv, inputs = [command, str(document), "--formats", "pdf,tiff_300", "--out", str(ir.parent / "exports")], (document_input,)
    else:
        argv, inputs = [command, str(document), "--font-evidence"], (document_input,)
    with project_runtime(store), native_artifact_runtime(argv, inputs=inputs, outputs=outputs), native_runtime_binding(argv) as reference:
        monkeypatch.setattr(os, "getppid", os.getpid)
        with worker_project_runtime(reference, argv):
            assert resolve_native_artifact(document, role="document") == document
            if command == "inspect-plot-ir":
                assert resolve_native_artifact(ir, role="ir") == ir
            if command == "preview-document":
                assert resolve_native_artifact(preview, role="out", output=True) == preview
        payload = json.loads(Path(reference["path"]).read_bytes())["project"]["native_artifacts"]
        assert payload["outputs"] == [] if not outputs else len(payload["outputs"]) == 1


@pytest.mark.comprehensive
def test_actual_readonly_child_inherits_exact_ir_metadata_role_and_clears_scope(tmp_path):
    store, before, ir, document, preview, argv, inputs, outputs = metadata_fixture(tmp_path)
    script = """import json,sys
from pathlib import Path
from sciplot_core.project_store.worker_binding import worker_project_runtime
from sciplot_core.project_store.native_artifacts import resolve_native_artifact
from sciplot_core.foundation.source_locations import selected_source_resolver,resolve_source_path
from sciplot_core.project_store import ProjectStoreError
reference=json.loads(sys.argv[1]);argv=json.loads(sys.argv[2])
with worker_project_runtime(reference,argv):
 ir=resolve_native_artifact(argv[1],role='ir');document=resolve_native_artifact(argv[2],role='document',output=True)
 try:resolve_source_path(ir,source_id='b'*32,expected_sha256='0'*64)
 except ProjectStoreError:pass
 else:raise AssertionError('Scientific source identity was bypassed')
 print(json.dumps({'ir':ir.read_text(),'document':str(document)}))
assert selected_source_resolver() is None
"""
    with project_runtime(store), native_artifact_runtime(argv, inputs=inputs, outputs=outputs), native_runtime_binding(argv) as reference:
        child = subprocess.run([sys.executable, "-c", script, json.dumps(reference), json.dumps(argv)],
                               text=True, capture_output=True, check=True, timeout=30)
    assert json.loads(child.stdout) == {"ir": ir.read_text(), "document": str(document)}
    assert not document.exists() and not preview.exists() and store.snapshot() == before
