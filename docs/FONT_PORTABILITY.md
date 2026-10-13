# Font portability evidence

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
