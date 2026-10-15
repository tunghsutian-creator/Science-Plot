# Figure Assembly

A standalone, offline macOS document tool for arranging existing scientific PDF
pages. It runs from a double-clickable app bundle and needs no account, model,
Python, Veusz, Research Plots installation or local web server.

## Use

Open **Figure Assembly.app**, then **Import** your PDFs. Select a cell and choose
a source in the left rail. Multipage PDFs always ask which page to place.
The presets are 2 × 2, 3 × 2, 2 × 3 and 3 × 3 (columns × rows), with custom
counts from 1 to 12. Each cell is exactly **60 × 55 mm**, including the source's
existing white space. There is no extra exterior margin or intercell spacing.

A PDF page is an indivisible original. It is centered at **100% of its physical
size**. An oversized page asks you to merge cells or explicitly choose a uniform
whole-page scale; the scale is shown. **Fit whole page to cell** is one explicit
click and stores the exact width/height fit ratio. For example a 156 pt page is
55.033 mm high and fits a 55 mm cell at approximately **99.94%**, rather than
being labelled 100%. **Keep original size** retains the source and current
placement so you can merge cells and place it at 100% instead.
The app never crops, stretches, edits
internal labels/curves or reflows a plot. The footer's **View** zoom changes only
the screen magnification; it never changes the stored page scale or export.
Screen 100% uses 96 CSS pixels per inch, not a calibrated monitor ruler.

Shift-click a rectangle of cells and choose **Merge**. A merge may contain at
most one existing figure, so no source is discarded. **Split** returns a merged
container to cells; it refuses a page that cannot fit until you explicitly scale
it. Drag a whole figure to swap contents, press Escape to cancel, or use the
**Move** dialog as a keyboard alternative. Arrow keys move cell selection;
Shift-arrow extends it. **Replace**, **Clear**, merges, swaps and scale changes
are undoable. Panel letters follow occupied cells in reading order and can be
turned off with **Labels**.

Save a `.figureassembly` project. It embeds the original source bytes, hashes,
selected pages, layout, scales and letters. Copy that one file elsewhere and use
**Open project** to keep editing; the old source paths are unnecessary. Existing
file changes are detected before overwrite. Cancelled or failed saves leave the
current document open. Keep your originals as usual; an embedded project is not
a scientific provenance audit or a backup system.

**Export PDF** copies original PDF content/resources as vector page objects.
Preview pixels and browser print are never used for PDF export. Existing text,
fonts, vector paths and supported transparency remain source-owned; new letters
are real text with embedded Noto Sans. Rasterized/outlined input stays rasterized/
outlined. Export options also provide PNG and TIFF at explicit DPI. Imported
PNG/JPEG/TIFF are auxiliary raster sources: effective resolution is shown, and an
unknown original DPI is explicitly recorded as a 300 dpi assumption.

Shortcuts: ⌘I import, ⌘O open, ⌘S save, ⇧⌘S save as, ⌘E export PDF,
⌘Z undo, ⇧⌘Z redo, ⌘N new layout. Text inputs retain their own undo behavior.

## Supported fidelity boundary

Visible PDF size is CropBox intersected with MediaBox, including its white space,
with intrinsic 0/90/180/270° rotation and nonzero page origins preserved. Subset
fonts, Greek/superscript text, thin vector paths and ordinary transparency have
dedicated controls. Only proven isolated RGB page transparency groups are accepted.

Annotations (including links and visible annotation appearances), forms, optional
content layers, tagged-structure catalogs, output intents, active actions,
nonstandard UserUnit, encrypted/damaged PDFs and unproven page groups are refused
with a reason. Make a static PDF in the original application when appropriate;
the compositor does not silently flatten or discard unsupported appearances.
This is a bounded static-page compositor, not a claim of arbitrary PDF/PDF-A,
accessibility-tag or journal compliance.

TIFF support is limited to upright, single-image, 8-bit RGB/grayscale sources
whose pixels can be verified by the native decoder. The portable project keeps
the original TIFF plus its PNG decoding. Import, save, reopen and export all
re-decode and compare the original/cache pixels. A different same-size image is
refused. Unsupported orientation, bit depth, frame count or color profiles are
refused rather than silently changed. JPEG/PNG profile restrictions are explained
by the import error. Font substitution across other machines and print/journal
acceptance still require separate review.

Limits: 64 MiB per original source, 128 MiB total stored source/cache bytes,
100 sources, 1,000 pages per PDF, 12 rows/columns; auxiliary raster export is
bounded to 64 million pixels at 72–1,200 dpi. Very large or unsupported inputs
produce an explicit error. No network resource, telemetry or model API is used.
Development AI tokens and billed fees remain **unknown** unless an external
client supplies real counters; byte counts are not tokens.

## Build and verify

Developers need Node 26 and Xcode Command Line Tools on macOS:

```sh
cd apps/pdf-composer
npm ci --ignore-scripts
npm run check
npx playwright install chromium
npm run test:browser
npm run build:mac
bash tests/native-tests.sh
bash tests/native-ui.sh
```

The bundle is `release/Figure Assembly.app`. Build output is ignored and is never
committed. The app uses only bundled JS/font resources and Apple system frameworks.
The native build is local and unsigned; signing, notarization, distribution to
other Macs and Gatekeeper changes are not performed by this build.

Tests cover geometry/history/portable integrity, actual vector/font resources,
explicit refusal controls, rendered browser interactions, native save conflicts,
original TIFF pixels, physical raster exports and the actual offline WebKit UI.
Synthetic fixtures are generated locally. Private scientific PDFs stay under
ignored `.tmp_verify/` and are excluded from public Git/CI artifacts.
The dedicated **Independent PDF compositor** workflow owns this app's CI.
Research Plots' scientific suite and its incomplete private access-capture audit
remain separate; this app's PASS cannot close those historical limitations.

Code inherits the repository GPLv2 license. Runtime PDF libraries use MIT/Zlib/
0BSD licenses and the bundled font uses SIL OFL 1.1. Build-generated notices
are included in the app. PyMuPDF is not an application dependency; any local
independent development comparison using it is evidence only.
