"""SVG viewport physical units are distinct from decoder coordinates."""

from xml.etree import ElementTree

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.qa.additional_exports import _svg_physical_canvas
from sciplot_core.qa.run import run_qa
from test_delivery_extra_formats import _real_artifacts


def _root(width="96px", height="48px", **attributes):
    values = {"height": height, **attributes}
    if width is not None:
        values["width"] = width
    return ElementTree.Element("{http://www.w3.org/2000/svg}svg", values)


@pytest.mark.parametrize("width,height", [
    ("96px", "48px"), ("72pt", "36pt"), ("25.4mm", "12.7mm"),
    ("2.54cm", "1.27cm"), ("1in", ".5in"),
])
def test_svg_explicit_absolute_units_share_the_existing_physical_point_owner(width, height):
    report = _svg_physical_canvas(_root(width, height))
    assert report["physical_size_pt"] == pytest.approx([72, 36])
    assert report["declared_dimensions"] == {"width": width, "height": height}
    assert report["css_pixels_per_inch"] == 96


@pytest.mark.parametrize("width", [None, "100%", "100", "2em", "NaNpx", "0pt", "1inch"])
def test_svg_unknown_or_missing_physical_canvas_never_uses_decoder_or_viewbox_as_a_guess(width):
    with pytest.raises(ValueError):
        _svg_physical_canvas(_root(width, viewBox="0 0 96 48"))


def test_svg_viewbox_remains_a_user_coordinate_mapping_not_a_physical_dimension():
    report = _svg_physical_canvas(_root(viewBox="-10, 4, 960, 480"))
    assert report["physical_size_pt"] == [72, 36]
    assert report["declared_view_box"] == "-10, 4, 960, 480"
    assert report["view_box"] == [-10, 4, 960, 480]


@pytest.mark.parametrize("view_box", ["0 0 0 48", "0 0 96", "0 0 NaN 48"])
def test_svg_invalid_or_nonfinite_viewbox_is_rejected(view_box):
    with pytest.raises(ValueError):
        _svg_physical_canvas(_root(viewBox=view_box))


def test_svg_css_pixel_physical_size_and_actual_decoder_canvas_are_separate_observations(tmp_path):
    root = _real_artifacts(tmp_path / "actual")
    svg = root / "a.svg"
    svg.write_text(svg.read_text().replace('width="100pt" height="50pt"',
        'width="133.333333px" height="66.666667px" viewBox="0 0 100 50"'))
    content, digest = svg.read_bytes(), file_sha256(svg)
    report, = run_qa(root)["svgs"]
    assert report["svg_canvas"]["physical_size_pt"] == pytest.approx([100, 50])
    assert report["decoder_canvas_pt"] == pytest.approx([133.333333, 66.666667])
    assert "media_box_pt" not in report
    assert report["visual_qa"]["ink_fraction"] > 0
    assert report["sha256"] == digest and svg.read_bytes() == content


@pytest.mark.parametrize("width,accepted", [("134.533333px", True), ("134.8px", False)])
def test_svg_actual_physical_canvas_uses_the_same_one_point_bound(tmp_path, width, accepted):
    root = _real_artifacts(tmp_path / "actual")
    svg = root / "a.svg"
    svg.write_text(svg.read_text().replace('width="100pt"', f'width="{width}"'))
    before = svg.read_bytes()
    if accepted:
        assert len(run_qa(root)["svgs"]) == 1
    else:
        with pytest.raises(ValueError, match="same native figure canvas"):
            run_qa(root)
    assert svg.read_bytes() == before


@pytest.mark.parametrize("stylesheet", [False, True])
def test_svg_css_dependent_dimensions_are_explicitly_unsupported_in_native_qa(tmp_path, stylesheet):
    root = _real_artifacts(tmp_path / "actual")
    svg = root / "a.svg"
    value = svg.read_text()
    if stylesheet:
        value = value.replace("<path", "<style>svg { width: 200pt; }</style><path")
    else:
        value = value.replace('width="100pt"', 'width="100pt" style="width: 200pt"')
    svg.write_text(value)
    before = svg.read_bytes()
    with pytest.raises(ValueError, match="Stylesheet-dependent"):
        run_qa(root)
    assert svg.read_bytes() == before
