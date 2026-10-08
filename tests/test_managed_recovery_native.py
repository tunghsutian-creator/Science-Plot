"""Real managed native compile intent recovery without repeating scientific work."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from sciplot_core.plot_backends.managed_plan import native_name
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import digest, load_head, read
from managed_plot_helpers import request_for_source


class SimulatedCrash(BaseException):
    """Model process interruption beyond the ordinary recoverable error handler."""


def _root(directory, request):
    return directory / ".sciplot_documents/managed" / digest(request["idempotency_key"])


def _spy_work(monkeypatch):
    from sciplot_core.plot_engine import managed_creation

    counts = {"science": 0, "compile": 0}
    resolve, compile_ir = managed_creation.resolve_science, ManagedVeuszCompiler.compile_ir

    def scientific(*args, **kwargs):
        counts["science"] += 1
        return resolve(*args, **kwargs)

    def native(*args, **kwargs):
        counts["compile"] += 1
        return compile_ir(*args, **kwargs)

    monkeypatch.setattr(managed_creation, "resolve_science", scientific)
    monkeypatch.setattr(ManagedVeuszCompiler, "compile_ir", native)
    return counts


def _crash_before_build_receipt(monkeypatch):
    from sciplot_core.plot_engine import managed_backend

    original = managed_backend.write
    fired = []

    def interrupted(path, value):
        if Path(path).name == "build.json" and not fired:
            fired.append(str(path))
            raise SimulatedCrash("Native compilation finished; durable build receipt not written.")
        return original(path, value)

    monkeypatch.setattr(managed_backend, "write", interrupted)
    return fired


def _assert_semantics_untouched(root, prior):
    head = load_head(root)
    assert head["document"] == prior["document"]
    assert head["document"]["revision"] == 0
    assert len(list((root / "revisions").glob("*.json"))) == 1
    assert len(list((root / "transform-cache").glob("*.result.json"))) == 1


@pytest.mark.comprehensive
@pytest.mark.parametrize("when", ["initial", "rebuild"])
def test_public_retry_adopts_completed_native_compile_after_receipt_crash(tmp_path, monkeypatch, when):
    request = request_for_source(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    source_bytes = source.read_bytes()
    counts = _spy_work(monkeypatch)
    service = PlotService()
    root = _root(tmp_path, request)
    try:
        if when == "rebuild":
            assert service.create(request)["ready_to_use"]
            head = load_head(root)
            native = Path(head["binding"]["document"])
            previous_build = read(native.parent / "build.json")
            native.unlink()  # Keep the old build receipt to test its stale-marker case.
        fired = _crash_before_build_receipt(monkeypatch)
        with pytest.raises(SimulatedCrash):
            service.create(request) if when == "initial" else service.export(root)
        prior = load_head(root)
        native = Path(prior["binding"]["document"])
        intent = read(native.parent / "compile-intent.json")
        native_hash = file_sha256(native)
        assert fired and native.exists()
        if when == "initial":
            assert not (native.parent / "build.json").exists()
        else:
            assert read(native.parent / "build.json") == previous_build
            assert intent["compile_id"] != previous_build["compile_id"]
        count_at_crash = deepcopy(counts)
        service.close()
        service = PlotService()  # Recovery also survives daemon/native-worker replacement.
        recovered = service.create(request) if when == "initial" else service.export(root)
        assert recovered["ready_to_use"] and recovered["revision"] == 0, recovered
        assert counts == count_at_crash == {"science": 1, "compile": 1 if when == "initial" else 2}
        assert file_sha256(native) == native_hash  # Recovery audits/adopts; it does not compile again.
        assert read(native.parent / "build.json")["compile_id"] == intent["compile_id"]
        assert source.read_bytes() == source_bytes
        _assert_semantics_untouched(root, prior)
    finally:
        service.close()


@pytest.mark.comprehensive
@pytest.mark.parametrize("change", ["metadata_only", "represented_style"])
def test_owned_compile_intent_accepts_only_complete_canonical_native_equivalence(tmp_path, monkeypatch, change):
    request = request_for_source(tmp_path)
    root = _root(tmp_path, request)
    counts = _spy_work(monkeypatch)
    _crash_before_build_receipt(monkeypatch)
    service = PlotService()
    try:
        with pytest.raises(SimulatedCrash):
            service.create(request)
        prior = load_head(root)
        native = Path(prior["binding"]["document"])
        if change == "metadata_only":
            native.write_bytes(native.read_bytes() + b"\n# Equivalent external serialization metadata\n")
        else:
            path = "/page1/graph1/" + native_name("series", "series:A")
            batch = tmp_path / "manual-style.json"
            batch.write_text(json.dumps([{"object_path": path, "setting_path": path + "/PlotLine/width",
                                          "expected_value": "0.7pt", "value": "1.2pt"}]))
            changed = tmp_path / "manual-native.vsz"
            service.backend.managed.compiler._run(["edit-document", str(native), "--changes", str(batch),
                "--output-document", str(changed), "--preview-png", str(tmp_path / "manual-native.png")])
            changed.replace(native)
        observed_hash = file_sha256(native)
        recovered = service.create(request)
        if change == "metadata_only":
            assert recovered["ready_to_use"], recovered
            assert read(native.parent / "build.json")["document_sha256"] == observed_hash
        else:
            assert recovered["status"] == "blocked" and not recovered.get("ready_to_use")
            assert recovered["error"]["reason_code"] == "managed_external_mutation"
            assert not (native.parent / "build.json").exists()
        assert file_sha256(native) == observed_hash
        assert counts == {"science": 1, "compile": 1}
        _assert_semantics_untouched(root, prior)
    finally:
        service.close()


@pytest.mark.comprehensive
@pytest.mark.parametrize("interrupt_upgrade,same_native_bytes", [(False, False), (True, False), (True, True)])
def test_compiler_upgrade_rebuilds_known_unchanged_native_product(tmp_path, monkeypatch, interrupt_upgrade, same_native_bytes):
    from sciplot_core.plot_backends import managed
    from sciplot_core.plot_engine import cache_identity, managed_backend

    request = request_for_source(tmp_path)
    counts = _spy_work(monkeypatch)
    service = PlotService()
    try:
        created = service.create(request)
        assert created["ready_to_use"]
        root = Path(created["plot"])
        prior = load_head(root)
        native = Path(prior["binding"]["document"])
        previous = read(native.parent / "build.json")
        prior_native_bytes = native.read_bytes()
        assert file_sha256(native) == previous["document_sha256"]
        upgraded = {**managed.compiler_identity(), "version": "test-upgrade", "content_hash": "f" * 64}
        runtime = cache_identity.runtime_identity()
        monkeypatch.setattr(managed, "compiler_identity", lambda: upgraded)
        monkeypatch.setattr(managed_backend, "compiler_identity", lambda: upgraded)
        # A genuine compiler source update also changes the artifact recipe identity.
        monkeypatch.setattr(cache_identity, "runtime_identity", lambda: {**runtime, "adapter_source_sha256": "f" * 64})
        if same_native_bytes:
            original_compile = service.backend.managed.compiler.compile_ir

            def identical_product(ir, output):
                result = original_compile(ir, output)
                # A renderer upgrade need not alter generated bytes. Preserve the
                # original harmless Save metadata to exercise this exact case.
                Path(result["document"]).write_bytes(prior_native_bytes)
                result["document_sha256"] = file_sha256(Path(result["document"]))
                result["evidence_files"][result["document"]] = result["document_sha256"]
                return result

            monkeypatch.setattr(service.backend.managed.compiler, "compile_ir", identical_product)
        if interrupt_upgrade:
            _crash_before_build_receipt(monkeypatch)
            with pytest.raises(SimulatedCrash):
                service.export(root)
            at_crash = deepcopy(counts)
        exported = service.export(root)
        assert exported["ready_to_use"] and exported["revision"] == 0, exported
        assert counts == {"science": 1, "compile": 2}
        if interrupt_upgrade:
            assert counts == at_crash
        current = read(native.parent / "build.json")
        assert current["compiler_identity"] == upgraded
        assert current["compile_id"] != previous["compile_id"]
        assert current["document_sha256"] == file_sha256(native)
        _assert_semantics_untouched(root, prior)
    finally:
        service.close()


@pytest.mark.comprehensive
def test_partial_native_compile_remains_unaccepted_without_scientific_reexecution(tmp_path, monkeypatch):
    request = request_for_source(tmp_path)
    counts = _spy_work(monkeypatch)
    service = PlotService()
    compile_ir = service.backend.managed.compiler.compile_ir
    fired = []

    def incomplete(ir, output):
        if not fired:
            fired.append(True)
            output.mkdir(parents=True, exist_ok=True)
            (output / "document.vsz").write_bytes(b"Incomplete native file after process interruption\n")
            raise SimulatedCrash("Interrupted during native save.")
        return compile_ir(ir, output)

    monkeypatch.setattr(service.backend.managed.compiler, "compile_ir", incomplete)
    try:
        with pytest.raises(SimulatedCrash):
            service.create(request)
        root = _root(tmp_path, request)
        prior = load_head(root)
        native = Path(prior["binding"]["document"])
        original = native.read_bytes()
        retry = service.create(request)
        assert retry["status"] == "blocked" and not retry.get("ready_to_use")
        assert not (native.parent / "build.json").exists()
        assert native.read_bytes() == original
        assert counts["science"] == 1
        _assert_semantics_untouched(root, prior)
    finally:
        service.close()


def test_compiler_identity_covers_vendored_renderer_and_shared_helpers(tmp_path, monkeypatch):
    from sciplot_core.native_process import identity
    from sciplot_core.plot_backends.managed import compiler_identity

    package = tmp_path / "sciplot"
    renderer = tmp_path / "renderer"
    package.mkdir()
    (renderer / "veusz").mkdir(parents=True)
    helper = package / "shared_render_helper.py"
    native = renderer / "veusz/widget.py"
    helper.write_text("STYLE_VERSION = 1\n")
    native.write_text("NATIVE_DEFAULT_VERSION = 1\n")
    monkeypatch.setattr(identity, "PACKAGE_ROOT", package)
    monkeypatch.setattr(identity, "VEUSZ_ROOT", renderer)
    initial = compiler_identity()
    native.write_text("NATIVE_DEFAULT_VERSION = 2\n")
    renderer_changed = compiler_identity()
    helper.write_text("STYLE_VERSION = 2\n")
    helper_changed = compiler_identity()
    assert len({entry["content_hash"] for entry in (initial, renderer_changed, helper_changed)}) == 3
