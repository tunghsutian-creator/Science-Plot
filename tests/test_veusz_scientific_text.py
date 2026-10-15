"""Closed lexical/font boundaries for the native missing-glyph typesetter."""

from types import SimpleNamespace

import pytest

from sciplot_core.studio_core import veusz_scientific_text as owner


@pytest.mark.parametrize(("text", "parts"), [
    ("Density (g cm⁻³)", [(False, "Density (g cm"), (True, "−3"), (False, ")")]),
    ("m⁻¹² s⁻²", [(False, "m"), (True, "−12"), (False, " s"), (True, "−2")]),
    ("−1 -2 1–2 m² s⁺¹ x₋₁", [(False, "−1 -2 1–2 m² s⁺¹ x₋₁")]),
    ("x⁻¹²⁺ y⁻¹⁻² z⁻ a⁻¹ᵃ b⁻¹⁽²⁾", [(False, "x⁻¹²⁺ y⁻¹⁻² z⁻ a⁻¹ᵃ b⁻¹⁽²⁾")]),
    ("", []),
])
def test_only_complete_negative_numeric_exponents_are_split(text, parts):
    assert owner._exponent_runs(text) == parts


class Face:
    def __init__(self, family="Liberation Sans", missing=(0x207B,), valid=True):
        self.family, self.missing, self.valid = family, missing, valid

    def isValid(self):
        return self.valid

    def familyName(self):
        return self.family

    def supportsCharacter(self, codepoint):
        return codepoint not in self.missing


@pytest.mark.parametrize(("face", "supported"), [
    (Face(), True), (Face("Arial"), False), (Face("Helvetica"), False),
    (Face(missing=()), False), (Face(missing=(0x207B, 0x2212)), False),
    (Face(missing=(0x207B, ord("2"))), False), (Face(valid=False), False),
])
def test_actual_primary_face_must_need_and_support_the_exact_replacement(face, supported):
    assert owner._supported_face(face, [(True, "−12")]) is supported


@pytest.fixture
def native(monkeypatch):
    """Record which native primitives are chosen; geometry is tested in real Qt."""
    class Text:
        def __init__(self, text):
            self.text = text

        def render(self, state):
            state.calls.append(("text", self.text, state.actually_render))

    class Script:
        def __init__(self, children):
            self.children = children

        def render(self, state):
            state.calls.append(("script",))
            for child in self.children:
                child.render(state)

    class Subscript(Script):
        pass

    runtime = SimpleNamespace(PartText=Text, PartSuperScript=Script, PartSubScript=Subscript)
    qt = SimpleNamespace(QRawFont=SimpleNamespace(fromFont=lambda font: font.face))
    monkeypatch.setattr(owner, "import_module", lambda name: qt if name == "veusz.qtall" else runtime)
    owner.ensure_veusz_scientific_text()
    return runtime


def state(size=7, face=None, paint=True):
    return SimpleNamespace(font=SimpleNamespace(pointSizeF=lambda: size, face=face or Face()),
                           actually_render=paint, calls=[])


@pytest.mark.parametrize("paint", [True, False])
def test_measurement_and_paint_use_the_same_native_script_parts(native, paint):
    current = state(paint=paint)
    original = native.PartText("g cm⁻³) -1 −2")
    original.render(current)
    assert current.calls == [("text", "g cm", paint), ("script",),
                             ("text", "−3", paint), ("text", ") -1 −2", paint)]
    assert original.text == "g cm⁻³) -1 −2"
    assert getattr(current, owner._SCRIPT_DEPTH) == 0


@pytest.mark.parametrize("size", [-1, 4, 5, 6, 6.99, float("nan"), float("inf")])
def test_pixel_small_and_nonfinite_fonts_keep_upstream_rendering(native, size):
    current = state(size=size)
    native.PartText("cm⁻³").render(current)
    assert current.calls == [("text", "cm⁻³", True)]


@pytest.mark.parametrize("kind", ["PartSuperScript", "PartSubScript"])
def test_existing_tex_scripts_are_never_double_raised_or_resized(native, kind):
    current = state()
    getattr(native, kind)([native.PartText("⁻²")]).render(current)
    assert current.calls == [("script",), ("text", "⁻²", True)]
    native.PartText("cm⁻³").render(current)
    assert current.calls[-2:] == [("script",), ("text", "−3", True)]


def test_covered_primary_font_and_other_families_keep_original_text(native):
    for face in (Face(missing=()), Face("Arial"), Face("Helvetica")):
        current = state(face=face)
        native.PartText("cm⁻³").render(current)
        assert current.calls == [("text", "cm⁻³", True)]


def test_installation_is_idempotent(native):
    methods = native.PartText.render, native.PartSuperScript.render, native.PartSubScript.render
    owner.ensure_veusz_scientific_text()
    assert methods == (native.PartText.render, native.PartSuperScript.render, native.PartSubScript.render)


def test_existing_script_context_restores_after_upstream_error(native):
    class Broken:
        def render(self, _state):
            raise RuntimeError("upstream")

    current = state()
    with pytest.raises(RuntimeError, match="upstream"):
        native.PartSuperScript([Broken()]).render(current)
    assert getattr(current, owner._SCRIPT_DEPTH) == 0
