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
captures have matching structure and zero changed raster pixels. Their strict
environment assertions initially rejected the changed Python/binary and package
identities below. An isolated environment subsequently reproduced all six
recorded identities and passed all four unchanged golden test nodes, including
legacy replay and Managed rebuild. Their immutable baselines were retained.
This is bounded Mac evidence, not established cross-environment font portability.

The measured environment differences are limited to these fields; platform,
requested Arial font-file hashes, Qt module hashes and raster pixels match.

| Field | Recorded golden | Initial current Mac verification |
| --- | --- | --- |
| `python` | 3.14.7 | 3.14.8 |
| `python_binary_sha256` | `87d4df53fd91304be5bac391fb204643c36b7df2023c04a0953bcbc7d4fdf634` | `1b5cb11d163e5ba34e2a05fc533c0ed89574d4425f9749a9d89405f651980e0d` |
| `packages/Pillow` | 12.2.0 | 12.3.0 |
| `packages/PyMuPDF` | 1.27.2.3 | 1.28.2 |
| `packages/PyQt6-Qt6` | 6.11.1 | 6.11.2 |
| `packages/PyQt6-sip` | 13.11.1 | 13.13.0 |

The isolated recovery uses the official Homebrew Python 3.14.7 arm64 Tahoe
bottle from [the fixed formula revision](https://github.com/Homebrew/homebrew-core/blob/84625c34e39e59cfe3ee17f1c0f562628ef4e88b/Formula/p/python@3.14.rb),
archive SHA256 `9747ec7c458569bb6c03e5b9e1f5fcb7552f4955794b8164e21d70e6b2839e08`.
Homebrew's ordinary prefix relocation and ad-hoc signing reproduce the exact
recorded launcher hash. Python.app, framework and standard library load from
the task copy; the four older packages remain available in the original local
environment and were copied into an independent venv. The system installation,
original venv and golden files were not changed. Actual Qt module hashes, Arial
file hashes and platform identity also match. Other platform or glyph-resource
portability still requires its own evidence.

For an interpreter outside the system Cellar, macOS protected shell entry points
can clear inherited `DYLD_FRAMEWORK_PATH`. The isolated interpreter wrapper must
restore its own framework path after entering the shell, before invoking the
unchanged Python binary. Direct Python golden tests alone do not establish that
the public CLI and MCP launchers can start; those paths were separately exercised.

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
then compare those resources with native pixels and PDF resources. The restored Mac
environment passes all four immutable native golden nodes with matching local
Arial observations. Those passes establish the pinned Mac comparison; selected
font-file/glyph identity across other target environments remains unverified.
