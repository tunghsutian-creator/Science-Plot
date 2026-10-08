"""Recipe identities observe implementation/runtime inputs independently of outputs."""

from copy import deepcopy

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


def test_source_recipe_observes_actual_bytes_without_mtime_guessing(tmp_path):
    source = tmp_path / "renderer.py"
    source.write_text("value = 1")
    original = cache_identity._source_digest(tmp_path)
    source.write_text("value = 2")
    assert cache_identity._source_digest(tmp_path) != original
    source.write_text("value = 1")
    assert cache_identity._source_digest(tmp_path) == original


def test_runtime_identity_observes_font_environment_without_qt_import(monkeypatch):
    monkeypatch.setattr(cache_identity, "_source_digest", lambda _: "source-hash")
    monkeypatch.setattr(cache_identity, "_version", lambda _: "package-version")
    first = cache_identity.runtime_identity()
    monkeypatch.setenv("QT_QPA_FONTDIR", "/another/font/configuration")
    second = cache_identity.runtime_identity()
    assert first["runtime_environment_sha256"] != second["runtime_environment_sha256"]
    assert first["python_executable_sha256"] == second["python_executable_sha256"]
