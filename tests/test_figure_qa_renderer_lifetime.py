"""Native text measurement must release its painter before returning."""

import gc
from types import SimpleNamespace
from weakref import ref

from sciplot_core import plot_layout
from sciplot_core.plot_backends import figure_qa


def test_native_text_measurement_does_not_retain_renderer_until_gc(monkeypatch):
    render_refs = []
    recorded = []

    class Renderer:
        def __init__(self, painter, *_args, **_kwargs):
            self.painter = painter

        def render(self):
            return "painted"

        def getBounds(self):
            return (10, 20, 30, 40)

    utils = SimpleNamespace(Renderer=Renderer)

    class PaintHelper:
        def __init__(self, _document, _page_size, *, dpi):
            assert dpi == (150, 150)

    class Document:
        def pageSize(self, _page, *, dpi, integer):
            assert dpi == (150, 150) and integer is False
            return (100, 100)

        def paintTo(self, _helper, _page):
            painter = SimpleNamespace(widget=SimpleNamespace(path="/page/label"))
            renderer = utils.Renderer(painter, None, 0, 0, "Label")
            assert renderer.render() == "painted"
            render_refs.append(ref(renderer))

    def check(_layout, observations, *, expected_text_ids, data_points):
        recorded.extend(observations)
        assert expected_text_ids == ["label:title"]
        assert data_points == []
        return {"status": "passed"}

    monkeypatch.setattr(figure_qa, "drawing_plan", lambda _ir: [{
        "path": "/page/label", "type": "label", "semantic_id": "label:title",
        "role": "title", "view_id": "view:A", "allowed_bounds_mm": [0, 0, 100, 100],
    }])
    monkeypatch.setattr(figure_qa, "import_module", lambda name: {
        "veusz.utils": utils,
        "veusz.document": SimpleNamespace(PaintHelper=PaintHelper),
    }[name])
    monkeypatch.setattr(plot_layout, "native_publication_qa", check)

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        result = figure_qa.native_publication_qa(
            {"layout": {}, "scales": [], "views": []}, Document()
        )
        assert utils.Renderer is Renderer
        assert result["status"] == "passed"
        assert result["renderer"] == "veusz.native-text-bounds"
        assert result["observations"] == recorded
        assert len(recorded) == 1
        assert recorded[0]["semantic_id"] == "label:title"
        assert recorded[0]["bounds_mm"] == [
            10 * 25.4 / 150, 20 * 25.4 / 150,
            20 * 25.4 / 150, 20 * 25.4 / 150,
        ]
        assert len(render_refs) == 1
        assert render_refs[0]() is None
    finally:
        if was_enabled:
            gc.enable()
