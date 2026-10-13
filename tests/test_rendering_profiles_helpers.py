"""The golden gate must reject coordinated renderer drift and changed authority."""

import json

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
