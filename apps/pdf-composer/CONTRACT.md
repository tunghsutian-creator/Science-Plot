# Independent Figure Assembly contract

This app imports existing PDF pages as indivisible figures. Its local browser
workbench targets Microsoft Edge; Safari compatibility is not a new requirement.
It does not import
SciPlot, Veusz, data models, AI or scientific editors. Its owned verification is
the package's type/lint/unit/browser tests and macOS native integration tests;
Research Plots' full suite is outside this independent application change.

`src/core/types.ts` is the shared version-1 contract. Physical dimensions use PDF
points (72/inch), grid containers use fixed 60 × 55 mm cells including source
whitespace, with no additional exterior margin. Layout never reflows a source.
PDF pages use their visible CropBox intersected with MediaBox and intrinsic
rotation. A panel is centered at scale 1 unless the user explicitly changes its
uniform scale. Oversize pages refuse placement/export and offer merge or explicit
scale; no implicit crop, stretch or shrink.

Every cell belongs to exactly one rectangular panel, including empty panels.
Merge accepts a complete contiguous rectangle; at most one selected panel may
contain a source. Split preserves that source in the top-left cell at its exact
scale and refuses if it cannot fit. Move/swap exchanges sources between containers
and retains their scales, refusing an impossible result. Structural changes are
atomic and undoable. Escape cancels drags; selection is transient.

Portable `.figureassembly` files are closed validated JSON containing original
base64 bytes, SHA256, selected page and all layout/scale/label state. Original
bytes are immutable, TIFF additionally carries native lossless PNG decoding.
No absolute source paths or external assets are required after save. Unknown
schema, corrupted hashes, invalid geometry or duplicate identifiers fail closed.
Native save uses a content token to refuse overwriting a concurrently changed
file and atomic same-directory replacement. Cancel never mutates editor state.
Browser save starts a local download. It cannot acknowledge Edge's final file
write or download cancellation and therefore does not mark a dirty document
clean. A successfully reopened validated project is clean. Browser new/open/drop
replacement requires explicit discard when dirty, and beforeunload guards browser
navigation. Original project/source bytes never leave the local browser.

PDF export copies original content streams and resource graphs into page Form
XObjects. No screenshot or browser print route. Unsupported page state (including
annotations whose appearances cannot be retained) refuses explicitly. Existing
fonts/text/vector/transparency remain source-owned. Only new panel letters are
added as real text with a bundled licensed font. Preview rasters are disposable
and do not enter PDF export. PNG/TIFF exports are explicit auxiliary raster
formats at chosen DPI, with effective source resolution shown.
Edge previews use the bundled PDFium WASM renderer at the local application
origin, without a native bridge or remote rendering endpoint. PDFium does not
own composition, preflight, original bytes or exported publication resources.
Browser export supports PDF; native TIFF verification and native PNG/TIFF export
remain explicit native-only boundaries.

## Module ownership and APIs

- Integration owns package configuration, `src/core`, portable storage/history,
  shared contract, final tests, documentation and CI.
- Engine owns `src/pdf/` and `tests/pdf*.test.ts`. Proposed exports:
  `inspectSource(file: ImportedFile): Promise<SourceAsset>`;
  `composePdf(document: AssemblyDocument, labelFont: Uint8Array, verifyTiff?: TiffVerifier): Promise<ExportResult>`.
- Frontend owns React screen/components/styles and `src/bridge.ts` adapter;
  core helpers are imported from `src/core/document.ts`, `history.ts`, `storage.ts`.
- Desktop owns `native/`, macOS packaging scripts, native bridge tests.

The native web bridge is JSON messages on `window.webkit.messageHandlers.assembly`:
request `{id,method,params}`, response via
`window.__assemblyReply({id,result})` or `{id,error:{message,code}}`.
Methods and named parameters match `NativeBridge`: `importFiles {}`;
`openProject {}`; `saveProject {text,name,token?}`;
`saveExport {bytesBase64,name,format,dpi}`;
`previewPdf {bytesBase64,pageIndex,maxPixels}` returning PNG data URI;
`verifyTiff {bytesBase64,normalizedPngBase64}` returns null after decoding and
comparing the actual pixels of the original TIFF and supplied PNG; a mismatch
refuses. TIFF source admission, project load/save and export require this native
port. Type/hash/header checks alone cannot establish decoding identity.
`setDocumentState {title,dirty}`. Native menu sends
`window.dispatchEvent(new CustomEvent('assembly-menu',{detail:action}))`.
All resources are bundled locally; remote navigation and network access are
disabled. No account, server, automatic update or model API is required.
The Edge route uses local file inputs, drag/drop and downloads instead of the
WebKit bridge. Its development/preview HTTP server only serves local application
assets. It has no upload/API endpoint and no telemetry/model request. SVG
displacement is restricted to compact glass control groups; foreground text/icons
remain clear, and the wide source tray uses bounded border/shadow layering.

Core helpers: `createDocument(rows=2,columns=3)`, `validateDocument(doc)`,
`placeSource(doc,panelId,asset,pageIndex,scale=1)`, `clearPanel`, `mergePanels`,
`splitPanel`, `swapPanels`, `setPanelScale`, `resizeGrid`, `toggleLabels`,
`panelSizePt`, `requiredScale`, all immutable. History offers `createHistory`,
`commit`, `undo`, `redo` and `present/past/future` fields. Portable storage offers
async `serializeProject(doc,verifyTiff?)` and `parseProject(text,verifyTiff?)`
validating byte hashes, independently inspecting original source type/page geometry,
and comparing TIFF decoding pixels through the required native verifier.
