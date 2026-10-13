"""The font preflight is a metadata-only observation, never a render seal."""

import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

from sciplot_core.veusz_worker import cli, font_evidence, operations


class FakeDocument:
    def __init__(self, values):
        self.values = values

    def resolveSettingPath(self, _root, path):
        if path not in self.values:
            raise ValueError(path)
        return SimpleNamespace(get=lambda: self.values[path])


def test_font_preflight_separates_native_requests_from_screen_and_file_identity():
    document = FakeDocument({
        "/page/axis/Label/font": "Arial", "/page/axis/Label/style": "Italic",
        "/page/axis/Label/bold": False, "/page/axis/Label/italic": True,
        "/page/axis/TickLabels/font": "Arial",
        "/page/axis2/Label/font": "Arial", "/page/axis2/Label/style": "Italic",
        "/page/axis2/Label/bold": False, "/page/axis2/Label/italic": True,
    })
    widgets = {
        "/page/axis": {"settings": {
            "Label/font": "raw reference, not the effective family",
            "TickLabels/font": "Arial", "Line/color": "black",
        }},
        "/page/axis2": {"settings": {"Label/font": "Arial"}},
    }
    queries = []

    def match(requested):
        queries.append(requested.copy())
        return {"status": "observed", "family": "Liberation Sans", "style_name": "Italic"}

    evidence = font_evidence.collect_font_preflight(document, widgets, screen_match=match)
    assert evidence["scope"] == "saved_native_settings_and_qt_screen_queries_only"
    assert evidence["requests"][0] == {
        "setting_path": "/page/axis/Label/font",
        "requested": {"status": "observed", "family": "Arial", "style": "Italic", "bold": False, "italic": True},
        "qt_screen_match": {"status": "observed", "family": "Liberation Sans", "style_name": "Italic"},
    }
    assert len(evidence["requests"]) == 3
    assert len(queries) == 2  # Identical requests share a query; different styles do not.
    assert evidence["native_paint_font"]["status"] == "unobserved"
    assert evidence["resolved_font_file"]["status"] == "unobserved"
    assert evidence["cross_environment_portability"] == "unestablished"


def test_malformed_or_unresolvable_family_is_not_sent_to_qt():
    document = FakeDocument({"/page/label/Text/font": 3,
                             "/page/axis/Label/font": "x" * 257})
    widgets = {"/page/label": {"settings": {"Text/font": 3}},
               "/page/axis": {"settings": {"Label/font": "x" * 257}},
               "/page/missing": {"settings": {"Text/font": "Arial"}}}

    def forbidden(_request):
        raise AssertionError("Invalid font reached Qt")

    evidence = font_evidence.collect_font_preflight(document, widgets, screen_match=forbidden)
    assert len(evidence["requests"]) == 3
    assert all(item["requested"]["status"] == "unobserved" for item in evidence["requests"])
    assert all(item["qt_screen_match"]["status"] == "unobserved" for item in evidence["requests"])


def test_failed_screen_query_becomes_unobserved_without_aborting_inspection():
    document = FakeDocument({"/page/label/Text/font": "Arial"})
    widgets = {"/page/label": {"settings": {"Text/font": "Arial"}}}

    def failed(_request):
        raise RuntimeError("Qt match failed")

    evidence = font_evidence.collect_font_preflight(document, widgets, screen_match=failed)
    assert evidence["requests"][0]["requested"]["family"] == "Arial"
    assert evidence["requests"][0]["qt_screen_match"] == {
        "status": "unobserved", "reason": "qt_screen_font_query_failed",
    }
    assert evidence["resolved_font_file"]["status"] == "unobserved"


def test_no_gui_application_never_constructs_qt_font(monkeypatch):
    class NoApp:
        @staticmethod
        def instance():
            return None

    def forbidden(*_args):
        raise AssertionError("Qt font construction requires an existing GUI app")

    qt_gui = ModuleType("PyQt6.QtGui")
    qt_gui.QGuiApplication = NoApp
    qt_gui.QFont = forbidden
    qt_gui.QFontInfo = forbidden
    monkeypatch.setitem(sys.modules, "PyQt6.QtGui", qt_gui)
    result = font_evidence._qt_screen_match({"family": "Arial"})
    assert result == {"status": "unobserved", "reason": "qt_gui_application_unavailable"}


def test_qt_screen_match_reports_resolved_style_without_claiming_render_or_file(monkeypatch):
    class GuiApp:
        @staticmethod
        def instance():
            return GuiApp()

    class Font:
        def __init__(self, family):
            self.family = family
            self.style = None
            self.bold = None
            self.italic = None

        def setStyleName(self, value):
            self.style = value

        def setBold(self, value):
            self.bold = value

        def setItalic(self, value):
            self.italic = value

    class Info:
        def __init__(self, font):
            assert (font.family, font.style, font.bold, font.italic) == (
                "Arial", "Bold", True, False,
            )

        def family(self):
            return "Other screen family"

        def styleName(self):
            return "Other style"

        def weight(self):
            return 700

        def italic(self):
            return False

        def exactMatch(self):
            return False

    qt_gui = ModuleType("PyQt6.QtGui")
    qt_gui.QGuiApplication = GuiApp
    qt_gui.QFont = Font
    qt_gui.QFontInfo = Info
    monkeypatch.setitem(sys.modules, "PyQt6.QtGui", qt_gui)
    result = font_evidence._qt_screen_match({"family": "Arial", "style": "Bold",
                                              "bold": True, "italic": False})
    assert result == {"status": "observed", "query": "QFontInfo(QFont)",
                      "family": "Other screen family", "style_name": "Other style",
                      "weight": 700, "italic": False, "exact_match": False}


def test_inspection_default_response_is_unchanged_and_opt_in_adds_field(tmp_path, monkeypatch):
    path = tmp_path / "example.vsz"
    path.write_text("# exact native document\n")
    node = SimpleNamespace(path="/page/label", name="label", typename="label", settings=None)

    class Document:
        def walkNodes(self, collect, **_kwargs):
            collect(node.path, node)

    @contextmanager
    def loaded(_path):
        yield Document()

    monkeypatch.setattr("sciplot_core.veusz_worker.document_edit.loaded_native_document", loaded)
    monkeypatch.setattr("sciplot_core.native_settings.editable_fields", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(operations, "_settings_snapshot", lambda _settings: {"Text/font": "Arial"})
    calls = []

    def preflight(_document, widgets):
        calls.append(widgets)
        return {"kind": "sciplot_font_preflight"}

    monkeypatch.setattr(font_evidence, "collect_font_preflight", preflight)
    normal = operations.inspect_document_state(Path(path))
    assert "font_evidence" not in normal
    assert calls == []
    opted = operations.inspect_document_state(Path(path), include_font_evidence=True)
    assert opted["font_evidence"] == {"kind": "sciplot_font_preflight"}
    assert len(calls) == 1
    assert {key: value for key, value in opted.items() if key != "font_evidence"} == normal


def test_worker_cli_font_evidence_flag_is_opt_in(monkeypatch, capsys):
    calls = []

    def inspect(path, *, include_font_evidence=False):
        calls.append((path, include_font_evidence))
        return {"status": "passed"}

    monkeypatch.setattr(cli, "inspect_document_state", inspect)
    cli.main(["inspect-document-state", "example.vsz"])
    cli.main(["inspect-document-state", "example.vsz", "--font-evidence"])
    assert calls == [(Path("example.vsz"), False), (Path("example.vsz"), True)]
    assert capsys.readouterr().out.count('"status": "passed"') == 2
