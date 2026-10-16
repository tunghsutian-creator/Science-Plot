# Figure Assembly

A local document tool for arranging existing scientific PDF pages. The browser
workbench targets **Microsoft Edge**. PDF inspection, previews, project parsing
and publication PDF export run on your computer with bundled code and a bundled
PDFium WebAssembly renderer. Files are not uploaded. No account, model API,
Python, Veusz or Research Plots runtime is required.

The existing double-clickable macOS app remains a separate native delivery. Its
file dialogs, conflict-aware saves, TIFF verification and auxiliary raster exports
use Apple system frameworks. The new SVG glass appearance is verified in Edge;
Safari/WebKit visual parity is outside this browser workbench's scope.

## Use

Open the local workbench in Edge, then choose **Import PDFs** in the bottom
source tray or drop files there. Select a cell and choose a source, or drag its
thumbnail into a cell. Dropping one external PDF into a cell imports and places
that whole page. Multipage PDFs always ask which page to place.
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
internal labels/curves or reflows a plot. The top toolbar's **Canvas zoom** changes
only screen magnification; it never changes stored page scale or export.
Screen 100% uses 96 CSS pixels per inch, not a calibrated monitor ruler.

Shift-click a rectangle of cells and choose **Merge**. A merge may contain at
most one existing figure, so no source is discarded. **Split** returns a merged
container to cells; it refuses a page that cannot fit until you explicitly scale
it. Drag a whole figure to swap contents, press Escape to cancel, or use the
**Move** dialog as a keyboard alternative. Arrow keys move cell selection;
Shift-arrow extends it. **Replace**, **Clear**, merges, swaps and scale changes
are undoable. Panel letters follow occupied cells in reading order and can be
turned off with **Labels**.

Choose **Save project** to download a `.figureassembly` project. It embeds the original source bytes, hashes,
selected pages, layout, scales and letters. Copy that one file elsewhere and use
**Open project** from the document menu, or drop the package into the workbench,
to keep editing; the old source paths are unnecessary. Browser download initiation
cannot confirm completion or cancellation in Edge's download UI, so a download
keeps the document's unsaved marker and leave protection active. Reopening a
successfully downloaded package establishes the saved state. New/open/project-drop
operations ask before discarding edits; cancel retains the document.
The native app additionally detects existing file changes before overwriting and
clears its unsaved marker only after a confirmed save. Keep your originals as
usual; an embedded project is not a scientific provenance audit or backup system.

**Export PDF** copies original PDF content/resources as vector page objects.
Preview pixels and browser print are never used for PDF export. Existing text,
fonts, vector paths and supported transparency remain source-owned; new letters
are real text with embedded Noto Sans. Rasterized/outlined input stays rasterized/
outlined. Browser PDF previews are disposable local rasters; they never become
publication PDF content. The macOS app's export options additionally provide PNG
and TIFF at explicit DPI. Imported
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

TIFF support is native-only and limited to upright, single-image, 8-bit RGB/grayscale sources
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

Developers need Node 26. For the browser workbench, install dependencies without
running package install scripts, start the local server, then open its printed
`http://127.0.0.1:5173` address in Edge:

```sh
cd apps/pdf-composer
npm ci --ignore-scripts
npm run dev
```

For a production build, use `npm run build` and serve `dist/` over a local HTTP
server (`npm exec vite preview -- --host 127.0.0.1`). PDFium's bundled WASM is
loaded from that same local origin; opening `dist/index.html` directly with a
`file:` URL is also supported by the self-contained build and checked separately.
No public deployment is required.

Package checks and actual Edge acceptance:

```sh
cd apps/pdf-composer
npm run check
npx playwright install chromium
npm run test:browser
node --import tsx tests/browser-edge.ts
```

The Edge test requires an installed Microsoft Edge executable; it does not claim
that Playwright Chromium is Edge. Override its default Mac executable with
`FIGURE_ASSEMBLY_EDGE_EXECUTABLE` if needed; otherwise Playwright uses its
`msedge` channel on the current platform. Send evidence outside the repository with
`FIGURE_ASSEMBLY_EDGE_OUT`. It starts a loopback static server, uses actual file
inputs/downloads, checks PDF preview ink and publication PDF resources, and
refuses unexpected external requests. The older browser harness separately tests
the native bridge contract with explicit PDFKit-preview refusal.

Building the native delivery additionally needs Xcode Command Line Tools:

```sh
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
Synthetic fixtures are generated locally. Optional local original-data Edge
acceptance uses `FIGURE_ASSEMBLY_PRIVATE_PROJECT` pointing to an already authorized
portable project; it keeps packages, exports and hashes in the chosen ignored or
external evidence directory. Private scientific PDFs stay under
ignored `.tmp_verify/` and are excluded from public Git/CI artifacts.
The dedicated **Independent PDF compositor** workflow owns this app's CI.
Research Plots' scientific suite and its incomplete private access-capture audit
remain separate; this app's PASS cannot close those historical limitations.

Code inherits the repository GPLv2 license. The PDF composition libraries use
MIT/Zlib/0BSD licenses, the PDFium wrapper uses MIT with PDFium's complete upstream
license notice retained, the pinned liquid-glass engine uses MIT, and the bundled
font uses SIL OFL 1.1. Build-generated notices are included in the app. PyMuPDF is not an application dependency; any local
independent development comparison using it is evidence only.
