"""Typeset missing Liberation Sans negative exponents with native Veusz parts."""

from __future__ import annotations

from importlib import import_module
import math
import re
from typing import Any
import unicodedata


_SUPERSCRIPT_RUN = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_NEGATIVE_EXPONENT = re.compile(r"⁻[⁰¹²³⁴⁵⁶⁷⁸⁹]+\Z")
_PLAIN_EXPONENT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789−")
_SCRIPT_DEPTH = "_sciplot_native_script_depth"
_MINIMUM_PARENT_SIZE_PT = 7.0


def _exponent_runs(text: str) -> list[tuple[bool, str]]:
    """Keep every non-exponent character literal, including malformed runs."""
    result: list[tuple[bool, str]] = []
    start = 0
    for match in _SUPERSCRIPT_RUN.finditer(text):
        if not _NEGATIVE_EXPONENT.fullmatch(match.group()):
            continue
        neighbours = text[max(0, match.start() - 1):match.start()] + text[
            match.end():match.end() + 1]
        if any(unicodedata.decomposition(char).startswith("<super>")
               for char in neighbours):
            continue
        if match.start() > start:
            result.append((False, text[start:match.start()]))
        result.append((True, match.group().translate(_PLAIN_EXPONENT)))
        start = match.end()
    if start < len(text):
        result.append((False, text[start:]))
    return result


def _supported_face(raw: Any, runs: list[tuple[bool, str]]) -> bool:
    """Inspect the actual primary face; Qt fallback coverage is insufficient."""
    return bool(
        raw.isValid()
        and raw.familyName() == "Liberation Sans"
        and not raw.supportsCharacter(0x207B)
        and all(raw.supportsCharacter(ord(char))
                for is_script, text in runs if is_script for char in text)
    )


def ensure_veusz_scientific_text() -> None:
    """Install a narrow, idempotent native text adapter without editing labels.

    Only a complete negative numeric superscript run in ordinary text changes,
    and only when the actual Liberation Sans face lacks U+207B. Native parts own
    both measurement and painting, script positioning, rotation and font restore.
    Existing TeX scripts, small/pixel-sized fonts, other faces, and covered glyphs
    retain upstream rendering. Saved VSZ/spec strings and scientific data stay intact.
    """
    native: Any = import_module("veusz.utils.textrender")
    qt: Any = import_module("veusz.qtall")
    if getattr(native, "_sciplot_scientific_text", False):
        return

    original_text = native.PartText.render

    def render_text(part: Any, state: Any) -> None:
        size = float(state.font.pointSizeF())
        if ("⁻" not in part.text or int(getattr(state, _SCRIPT_DEPTH, 0)) != 0
                or not math.isfinite(size) or size < _MINIMUM_PARENT_SIZE_PT):
            original_text(part, state)
            return
        runs = _exponent_runs(part.text)
        if (not any(is_script for is_script, _ in runs)
                or not _supported_face(qt.QRawFont.fromFont(state.font), runs)):
            original_text(part, state)
            return
        for is_script, text in runs:
            leaf = native.PartText(text)
            if is_script:
                # Native 0.6 scaling is nominally >=4.2pt at this entry size;
                # PDF device quantization is checked against the existing 4pt QA.
                # Smaller labels retain their existing Unicode glyph typography.
                native.PartSuperScript([leaf]).render(state)
            else:
                original_text(leaf, state)

    def preserve_script_context(original: Any) -> Any:
        def render_script(part: Any, state: Any) -> None:
            depth = getattr(state, _SCRIPT_DEPTH, 0)
            setattr(state, _SCRIPT_DEPTH, depth + 1)
            try:
                original(part, state)
            finally:
                setattr(state, _SCRIPT_DEPTH, depth)
        return render_script

    native.PartText.render = render_text
    for kind in (native.PartSuperScript, native.PartSubScript):
        kind.render = preserve_script_context(kind.render)
    native._sciplot_scientific_text = True
