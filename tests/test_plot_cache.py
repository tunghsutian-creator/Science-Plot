"""Recipe identities observe implementation/runtime inputs independently of outputs."""

from collections import Counter
from copy import deepcopy
import os
from pathlib import Path

from sciplot_core.plot_engine import cache_identity


def test_cache_recipe_changes_for_backend_runtime_font_export_and_input_changes(monkeypatch):
    runtime = {"backend": "version-1", "python": "runtime-1"}
    monkeypatch.setattr(cache_identity, "runtime_identity", lambda: runtime.copy())
    document = {"scientific_hash": "a" * 64, "presentation_hash": "b" * 64,
                "presentation": {"export_configuration": {"formats": ["pdf", "tiff_300"]}}}
    binding = {"fingerprint": {"files": {"/native.vsz": "c" * 64}},
               "font_configuration": {"families": ["Arial"]}}
    original = cache_identity.build_key(document, binding)
    runtime["backend"] = "version-2"
    assert cache_identity.build_key(document, binding) != original
    runtime["backend"] = "version-1"
    changed = deepcopy(document)
    changed["presentation"]["export_configuration"]["formats"] = ["pdf", "tiff_600"]
    assert cache_identity.build_key(changed, binding) != original
    changed_binding = deepcopy(binding)
    changed_binding["font_configuration"]["families"] = ["Times"]
    assert cache_identity.build_key(document, changed_binding) != original
    changed_binding = deepcopy(binding)
    changed_binding["fingerprint"]["files"]["/native.vsz"] = "d" * 64
    assert cache_identity.build_key(document, changed_binding) != original
    description = cache_identity.build_metadata(document, binding)
    assert description["fonts"]["coverage"] == "requested_configuration_only_resolved_font_files_unobserved"


def test_source_recipe_observes_actual_bytes_without_mtime_guessing(tmp_path, monkeypatch):
    from sciplot_core.native_process import identity

    core, veusz = tmp_path / "core", tmp_path / "third_party"
    sources = [core / folder / "renderer.py" for folder in ("plot_backends", "veusz_worker", "studio_render")]
    sources.append(veusz / "veusz" / "plot.py")
    for source in sources:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("value = 1")
    monkeypatch.setattr(identity, "PACKAGE_ROOT", core)
    monkeypatch.setattr(identity, "VEUSZ_ROOT", veusz)
    monkeypatch.setattr(cache_identity, "VEUSZ_ROOT", veusz)
    reads = Counter()
    original_open = Path.open

    def counted_open(path, *args, **kwargs):
        if path in sources:
            reads[path] += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    original = cache_identity.runtime_identity()
    assert reads == Counter({source: 1 for source in sources})
    for source in sources:
        stamp = source.stat()
        source.write_text("value = 2")
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert source.stat().st_size == stamp.st_size
        reads.clear()
        assert cache_identity.runtime_identity() != original
        assert reads == Counter({item: 1 for item in sources})
        source.write_text("value = 1")
    assert cache_identity.runtime_identity() == original


def test_runtime_identity_observes_font_environment_without_qt_import(monkeypatch):
    monkeypatch.setattr(cache_identity, "_version", lambda _: "package-version")
    first = cache_identity.runtime_identity()
    monkeypatch.setenv("QT_QPA_FONTDIR", "/another/font/configuration")
    second = cache_identity.runtime_identity()
    assert first["runtime_environment_sha256"] != second["runtime_environment_sha256"]
    assert first["python_executable_sha256"] == second["python_executable_sha256"]
