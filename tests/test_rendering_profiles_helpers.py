"""The golden gate must reject coordinated renderer drift and changed authority."""

import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from rendering_profiles_helpers import NativeSnapshot, assert_three_way, load_profile
from sciplot_core.foundation.file_hashing import file_sha256


def _profile(root):
    root.mkdir()
    (root / "raw.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (root / "accepted.vsz").write_text("# immutable test authority\n", encoding="utf-8")
    image = Image.new("RGB", (50, 50), "white")
    ImageDraw.Draw(image).line((10, 10, 10, 40), fill="black", width=2)
    image.save(root / "golden.png")
    for name, value in (("structure", {"axis": {"width_pt": .8}}), ("environment", {"font_sha256": "fixed-font"})):
        (root / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
    filenames = {"raw": "raw.csv", "accepted_vsz": "accepted.vsz", "golden_png": "golden.png",
                 "golden_structure": "structure.json", "golden_environment": "environment.json"}
    manifest = {"schema_version": 1, "profile_id": "synthetic-helper-test", "family": "test",
                "roles": {}, "identity": {"source": "synthetic-test-data"}, "unsupported": [],
                "files": {role: {"path": name, "sha256": file_sha256(root / name)} for role, name in filenames.items()}}
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_profile(path)


def _snapshot(directory, image, profile):
    return NativeSnapshot(directory, {"axis": {"width_pt": .8}}, {"font_sha256": "fixed-font"}, image, {}, {},
                          {"document_sha256": profile.manifest["files"]["accepted_vsz"]["sha256"]})


def test_changed_raw_authority_rejected_before_rendering(tmp_path):
    profile = _profile(tmp_path / "fixture")
    profile.files["raw"].write_text("x,y\n1,200\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="Immutable fixture changed or missing: raw"):
        load_profile(profile.manifest_path)


def test_fixed_golden_rejects_identical_drift_in_all_current_renderers(tmp_path):
    profile = _profile(tmp_path / "fixture")
    drifted = tmp_path / "drift.png"
    image = Image.new("RGB", (50, 50), "white")
    ImageDraw.Draw(image).line((11, 10, 11, 40), fill="black", width=2)
    image.save(drifted)
    # All current routes agree. Comparing them with each other would falsely pass.
    snapshot = _snapshot(tmp_path, drifted, profile)
    with pytest.raises(AssertionError, match="Three-way profile failed"):
        assert_three_way(profile, snapshot, snapshot, snapshot, output_dir=tmp_path / "gates")
    report = json.loads((tmp_path / "gates/three-way-report.json").read_text())
    assert set(report["gates"]) == {"accepted_current_environment", "legacy_fresh_replay", "managed"}
    assert all(gate["raster"]["status"] == "failed" for gate in report["gates"].values())


def test_current_environment_must_match_pinned_golden_environment(tmp_path):
    profile = _profile(tmp_path / "fixture")
    clean = _snapshot(tmp_path, profile.files["golden_png"], profile)
    changed = NativeSnapshot(tmp_path, clean.structure, {"font_sha256": "replacement-font"}, clean.image, {}, {}, clean.capture)
    with pytest.raises(AssertionError, match="Three-way profile failed"):
        assert_three_way(profile, changed, clean, clean, output_dir=tmp_path / "gates")
    report = json.loads((tmp_path / "gates/three-way-report.json").read_text())
    assert report["gates"]["accepted_current_environment"]["environment"]["status"] == "failed"
    assert report["gates"]["legacy_fresh_replay"]["status"] == "passed"


def test_profile_rejects_fixture_escape(tmp_path):
    profile = _profile(tmp_path / "fixture")
    manifest = profile.manifest
    outside = tmp_path / "raw.csv"
    outside.write_bytes(profile.files["raw"].read_bytes())
    manifest["files"]["raw"]["path"] = "../raw.csv"
    profile.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError, match="Pinned fixture escapes"):
        load_profile(profile.manifest_path)


def test_accepted_route_cannot_substitute_a_freshly_generated_document(tmp_path):
    profile = _profile(tmp_path / "fixture")
    clean = _snapshot(tmp_path, profile.files["golden_png"], profile)
    substituted = NativeSnapshot(tmp_path, clean.structure, clean.environment, clean.image, {}, {},
                                 {"document_sha256": "freshly-generated-document"})
    with pytest.raises(AssertionError, match="did not reopen the immutable accepted VSZ"):
        assert_three_way(profile, substituted, clean, clean, output_dir=tmp_path / "gates")


@pytest.mark.parametrize("paint_failure", [False, True])
def test_native_capture_releases_renderers_without_cycle_gc(monkeypatch, paint_failure):
    import gc
    from types import SimpleNamespace
    from weakref import ref

    import rendering_profiles_native as capture

    renderer_refs = []
    helper_release_observations = []

    class PaintFailed(Exception):
        pass

    class Renderer:
        def __init__(self, painter, *_args, **_kwargs):
            self.painter = painter
            renderer_refs.append(ref(self))

        def render(self):
            return "painted"

        def getBounds(self):
            return (10, 20, 30, 40)

    utils = SimpleNamespace(Renderer=Renderer)
    bar = SimpleNamespace(plotBars=lambda *_args: None)
    polygon = SimpleNamespace(draw=lambda *_args, **_kwargs: None)
    line = SimpleNamespace(draw=lambda *_args, **_kwargs: None)
    original_hooks = (bar.plotBars, polygon.draw, line.draw)
    font = SimpleNamespace(family=lambda: "Requested", pointSizeF=lambda: 9.5,
                           pixelSize=lambda: 12, weight=lambda: 400, italic=lambda: False)
    modules = {
        "veusz.utils": utils,
        "PyQt6.QtGui": SimpleNamespace(QFontInfo=lambda _font: SimpleNamespace(family=lambda: "Resolved")),
        "veusz.widgets.bar": SimpleNamespace(BarPlotter=bar),
        "veusz.widgets.polygon": SimpleNamespace(Polygon=polygon),
        "veusz.widgets.line": SimpleNamespace(Line=line),
    }
    monkeypatch.setattr(capture, "import_module", modules.__getitem__)

    class PaintHelper:
        def __init__(self, _document, _page_size, *, dpi):
            assert dpi == (150, 150)

        def __del__(self):
            helper_release_observations.append(any(renderer_ref() is not None for renderer_ref in renderer_refs))

    class Document:
        def pageSize(self, _page, *, dpi, integer):
            assert dpi == (150, 150) and integer is False
            return (100, 100)

        def paintTo(self, helper, _page):
            painter = SimpleNamespace(widget=SimpleNamespace(path="/page/axis"), helper=helper)
            renderer = utils.Renderer(painter, font, 150, 300, "Label", 0, 0, 12)
            assert renderer.render() == renderer.render() == "painted"
            del renderer
            assert utils.Renderer(painter, font, 15, 30, "Inline", angle=45).render() == "painted"
            if paint_failure:
                raise PaintFailed

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        if paint_failure:
            with pytest.raises(PaintFailed):
                capture._painted_text(Document(), SimpleNamespace(PaintHelper=PaintHelper))
        else:
            text, primitives = capture._painted_text(Document(), SimpleNamespace(PaintHelper=PaintHelper))
            assert primitives == []
            common = {"widget_path": "/page/axis",
                      "bounds_mm": [value * 25.4 / 150 for value in (10, 20, 30, 40)],
                      "font_family": "Requested", "resolved_font_family": "Resolved",
                      "font_size_pt": 9.5, "font_pixel_size": 12, "font_weight": 400, "italic": False}
            assert text == [
                {**common, "text": "Inline", "anchor_mm": [15 * 25.4 / 150, 30 * 25.4 / 150], "angle": 45.0},
                {**common, "text": "Label", "anchor_mm": [25.4, 50.8], "angle": 12.0},
                {**common, "text": "Label", "anchor_mm": [25.4, 50.8], "angle": 12.0},
            ]
            assert helper_release_observations == [False]
        assert utils.Renderer is Renderer
        assert (bar.plotBars, polygon.draw, line.draw) == original_hooks
        assert len(renderer_refs) == 2
        assert all(renderer_ref() is None for renderer_ref in renderer_refs)
    finally:
        if was_enabled:
            gc.enable()


def _capture_environment_inputs(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import rendering_profiles_native as capture
    from sciplot_core import _paths

    renderer = tmp_path / "renderer"
    (renderer / "veusz").mkdir(parents=True)
    (renderer / "veusz/generated.py").write_text("# generated renderer identity\n")
    monkeypatch.setattr(_paths, "VEUSZ_ROOT", renderer)
    font = tmp_path / "generated-font.ttf"
    font.write_bytes(b"generated font identity, not a native font\n")
    modules = {}
    for name in ("QtCore", "QtGui", "QtWidgets", "QtSvg", "QtPrintSupport"):
        path = tmp_path / (name + ".so")
        path.write_bytes(("generated binding identity: " + name).encode())
        modules["PyQt6." + name] = SimpleNamespace(__file__=str(path))
    modules["PyQt6.QtCore"].QT_VERSION_STR = "compiled-qt-version"
    modules["PyQt6.QtCore"].qVersion = lambda: "loaded-qt-runtime"
    modules["PyQt6.QtWidgets"].QApplication = SimpleNamespace(platformName=lambda: "generated-platform")
    monkeypatch.setattr(capture, "import_module", modules.__getitem__)
    packages = {name: "distribution:" + name for name in
                ("PyQt6", "PyQt6-Qt6", "PyQt6-sip", "numpy", "Pillow", "PyMuPDF")}

    def version(name):
        if name not in packages:
            raise capture.metadata.PackageNotFoundError(name)
        return packages[name]

    monkeypatch.setattr(capture.metadata, "version", version)
    return capture, {"generated-font.ttf": str(font)}, [{"resolved_font_family": "Generated font"}], packages


@pytest.mark.parametrize("wheel_installed", [False, True])
def test_native_capture_separates_optional_qt_wheel_from_loaded_runtime(tmp_path, monkeypatch, wheel_installed):
    capture, fonts, text, packages = _capture_environment_inputs(tmp_path, monkeypatch)
    if not wheel_installed:
        del packages["PyQt6-Qt6"]
    environment = capture._environment(fonts, text)
    assert environment["packages"] == {**packages, **({"PyQt6-Qt6": "not-installed"} if not wheel_installed else {})}
    assert environment["qt_compiled"] == "compiled-qt-version"
    assert environment["qt_runtime"] == "loaded-qt-runtime"
    assert environment["qt_platform"] == "generated-platform"
    assert environment["qt_modules_sha256"] == {
        name: file_sha256(tmp_path / (name + ".so"))
        for name in ("QtCore", "QtGui", "QtWidgets", "QtSvg", "QtPrintSupport")}
    assert environment["font_files_sha256"] == {name: file_sha256(Path(path)) for name, path in fonts.items()}


def test_native_capture_still_requires_binding_distribution_metadata(tmp_path, monkeypatch):
    capture, fonts, text, packages = _capture_environment_inputs(tmp_path, monkeypatch)
    del packages["PyQt6"]
    with pytest.raises(capture.metadata.PackageNotFoundError, match="PyQt6"):
        capture._environment(fonts, text)


def test_native_capture_wheel_metadata_cannot_replace_missing_qt(tmp_path, monkeypatch):
    capture, fonts, text, _packages = _capture_environment_inputs(tmp_path, monkeypatch)

    def missing_qt(name):
        raise ImportError("Generated missing Qt binding: " + name)

    monkeypatch.setattr(capture, "import_module", missing_qt)
    with pytest.raises(ImportError, match="Generated missing Qt binding: PyQt6.QtCore"):
        capture._environment(fonts, text)


def test_native_capture_optional_qt_wheel_does_not_relax_font_pins(tmp_path, monkeypatch):
    capture, _fonts, text, packages = _capture_environment_inputs(tmp_path, monkeypatch)
    del packages["PyQt6-Qt6"]
    with pytest.raises(ValueError, match="must pin its actual font files"):
        capture._environment({}, text)


def test_generated_capture_payload_cannot_supply_golden_authority(tmp_path, monkeypatch):
    import rendering_profiles_helpers as helpers
    import rendering_profiles_native as capture

    payload = {"document_sha256": "generated-document", "painted_text": [], "export": {"pdf_pages": 1}}

    def generated_core(document, output, font_files):
        assert document == tmp_path / "generated.vsz" and output == tmp_path and font_files is None
        return payload

    monkeypatch.setattr(capture, "_capture_document", generated_core)
    result = capture.capture_generated_geometry(tmp_path / "generated.vsz", tmp_path)
    assert result == {"kind": "sciplot_generated_native_geometry", "version": 1, "capture": payload}
    assert json.loads((tmp_path / "generated-geometry.json").read_text()) == result
    assert not isinstance(result, NativeSnapshot)
    assert not (tmp_path / "environment.json").exists()
    assert not (tmp_path / "producer-identity.json").exists()
    with pytest.raises(AssertionError, match="requires complete native profile evidence"):
        helpers.assert_accepted_golden(object(), result, output_dir=tmp_path / "comparison")
    with pytest.raises(AssertionError, match="requires complete native profile evidence"):
        helpers._compare_golden(object(), result, tmp_path / "comparison")


def test_native_capture_request_keeps_profile_default_and_explicit_generated_kind(monkeypatch):
    import rendering_profiles_native as capture

    calls = []
    monkeypatch.setattr(capture, "capture", lambda *args: calls.append(("profile", args)))
    monkeypatch.setattr(capture, "capture_generated_geometry", lambda *args: calls.append(("generated", args)))
    capture.capture_request({"document": "original.vsz", "output": "profile-output", "font_files": {"font": "face.ttf"}})
    capture.capture_request({"kind": "generated_geometry", "document": "generated.vsz", "output": "generated-output"})
    assert calls == [("profile", (Path("original.vsz"), Path("profile-output"), {"font": "face.ttf"})),
                     ("generated", (Path("generated.vsz"), Path("generated-output")))]


@pytest.mark.parametrize("capture_request_data", [
    {"kind": "unknown", "document": "doc.vsz", "output": "out"},
    {"kind": "generated_geometry", "document": "doc.vsz", "output": "out", "font_files": {}},
    {"document": "doc.vsz", "output": "out"},
    {"document": "doc.vsz", "output": "out", "font_files": None},
])
def test_native_capture_rejects_unknown_or_incomplete_request_before_native(monkeypatch, capture_request_data):
    import rendering_profiles_native as capture

    def no_native(*_args):
        raise AssertionError("Invalid request reached native capture")

    monkeypatch.setattr(capture, "_capture_document", no_native)
    with pytest.raises(ValueError):
        capture.capture_request(capture_request_data)
