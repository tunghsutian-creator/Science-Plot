# Font portability evidence

## 2026-10-13 Mac observation

A locally compiled Veusz Figure export on macOS 27.0.1 arm64, Python 3.14.8,
PyQt6 6.11.0 / Qt 6.11.2 passed native scientific and publication QA. The
delivered 300 dpi TIFF was visually inspected. Ten synchronous text draws on
the RecordPaintDevice requested and resolved Arial; the exported PDF contains
an embedded Type0 ArialMT font resource. Saved native settings also produced
44 successful Qt screen matches: 10 Arial and 34 Times New Roman.

Record-device observations and PDF resource names do not prove the system file
used for every glyph. Resolved whole-font-file and fallback-glyph identities
remain unobserved. Historical mechanical and both rheology accepted-profile
captures have matching structure and zero changed raster pixels, but their
strict environment assertions reject changed Python/binary, OS and package
identities. Their immutable baselines were retained. This is bounded Mac
evidence, not established cross-environment font portability.

## Observation boundary

The managed render recipe records requested font configuration, but currently
does **not** know which system font file the Veusz/Qt renderer used. Its
`fonts.coverage` value remains
`requested_configuration_only_resolved_font_files_unobserved`. Font-file bytes
are not a cache input, and the read-only preflight below does not change that.

For a saved native document, the internal worker can optionally produce a font
preflight alongside its ordinary inspection:

`python -m sciplot_core.veusz_worker inspect-document-state figure.vsz --font-evidence`

The extra `font_evidence` field records each effective `/font` setting that
Veusz can resolve, plus associated style/bold/italic settings where available.
It queries `QFontInfo(QFont(...))` using the **already-running** Qt GUI
application. A successful query is labeled `qt_screen_match`, including the
matched screen family, style name, weight, italic flag, and `exact_match`.
Missing Qt, no GUI application, an unresolved/malformed setting, or a failed
query becomes `unobserved` with a reason; it must not break inspection. The
field is opt-in and is not included in normal document inspection, a build key,
or a publication receipt.

This is **screen-match preflight only**. It does not render text, inspect a PDF
printer/paint device, observe glyph-by-glyph fallback, or identify the font
file used for a native export. `native_paint_font` and `resolved_font_file`
therefore remain `unobserved`, even when the screen query succeeds. Cross-
environment portability stays `unestablished`. No candidate font filename,
Matplotlib lookup, or installed-family list is treated as the file selected by
Qt. The historical golden-profile environment separately hashes explicitly
provided Arial files and records `QFontInfo` families; those two observations
do not establish that the hashed files supplied every rendered glyph.

This distinction follows Qt's own documentation: `QFontInfo(QFont)` describes
a screen-compatible match and may be inaccurate for printer fonts, while
`QPainter::fontInfo()` applies to the current paint device. `QFontDatabase`
offers installed families, not a public selected-file path. `QRawFont` can
expose selected sfnt tables for a preferred writing-system face, which is not
a whole font-file identity or proof of fallback glyph selection. See
[QFontInfo](https://doc.qt.io/qt-6/qfontinfo.html),
[QFontDatabase](https://doc.qt.io/qt-6/qfontdatabase.html), and
[QRawFont](https://doc.qt.io/qt-6/qrawfont.html).

Before claiming font-resource portability, capture actual native export
device/glyph evidence and resolved font-file bytes on each target environment,
then compare those resources with native pixels and PDF resources. The current
cloud checkout cannot perform that acceptance: it lacks the compiled vendored
Veusz Qt helpers and the macOS Arial font corpus used by the pinned golden
profiles.
