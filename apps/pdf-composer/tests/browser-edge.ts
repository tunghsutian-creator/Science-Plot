import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, join, resolve, sep } from 'node:path';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';
import fontkit from '@pdf-lib/fontkit';
import UPNG from '@pdf-lib/upng';
import { decodePDFRawStream, PDFDict, PDFDocument, PDFName, PDFRawStream, rgb } from 'pdf-lib';
import { chromium, type Download, type Locator } from 'playwright';
import type { AssemblyDocument } from '../src/core/types';

// This suite exercises the actual browser adapter. It never installs a native
// WebKit bridge or replaces the PDF preview, importer, saver or PDF engine.
const out = resolve(process.env.FIGURE_ASSEMBLY_EDGE_OUT ?? 'test-results/edge');
const dist = resolve(process.env.FIGURE_ASSEMBLY_EDGE_DIST ?? 'dist');
const executablePath = process.env.FIGURE_ASSEMBLY_EDGE_EXECUTABLE;
const domDiagnostic = process.env.FIGURE_ASSEMBLY_EDGE_DOM_ONLY === '1';
await mkdir(out, { recursive: true });
if (executablePath) await access(executablePath);
await access(join(dist, 'index.html')).catch(() => { throw new Error('Build the app before running tests/browser-edge.ts.'); });
const fontBytes = await readFile(new URL('../assets/NotoSans-Regular.ttf', import.meta.url));
const sha256 = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const mm = 72 / 25.4;

interface Fixture { name: string; path: string; bytes: Uint8Array; sha256: string }
async function fixture(name: string, pages: [number, number][], color = rgb(0.05, 0.18, 0.75)): Promise<Fixture> {
  const pdf = await PDFDocument.create();
  pdf.registerFontkit(fontkit);
  const font = await pdf.embedFont(fontBytes, { subset: true });
  pdf.setCreationDate(new Date('2026-10-16T00:00:00Z'));
  pdf.setModificationDate(new Date('2026-10-16T00:00:00Z'));
  for (const [index, [width, height]] of pages.entries()) {
    const page = pdf.addPage([width * mm, height * mm]);
    const left = 21, bottom = 24, right = width * mm - 8, top = height * mm - 15;
    page.drawLine({ start: { x: left, y: bottom }, end: { x: right, y: bottom }, thickness: 0.35 });
    page.drawLine({ start: { x: left, y: bottom }, end: { x: left, y: top }, thickness: 0.35 });
    page.drawText(`Synthetic ${name.replace('.pdf', '')} · page ${index + 1}`, { x: left, y: top + 4, size: 5.8, font });
    page.drawText('η / Pa s     ω / rad s⁻¹', { x: left, y: 8, size: 5.8, font });
    for (let sample = 0; sample < 2; sample++) {
      let prior = { x: left, y: bottom + 4 };
      for (let step = 1; step <= 40; step++) {
        const x = left + (right - left) * step / 40;
        const y = bottom + (top - bottom) * (0.12 + (sample ? 0.52 : 0.74) * Math.exp(-Math.pow((step / 40 - 0.25) / 0.19, 2)));
        page.drawLine({ start: prior, end: { x, y }, color: sample ? color : rgb(0.05, 0.05, 0.06), thickness: 0.35 });
        prior = { x, y };
      }
    }
  }
  const bytes = await pdf.save();
  const path = join(out, 'fixtures', name);
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, bytes);
  return { name, path, bytes, sha256: sha256(bytes) };
}

const multipage = await fixture('two-pages.pdf', [[60, 55], [40, 35]]);
const oversized = await fixture('large-page.pdf', [[90, 55]]);
const rounded = await fixture('rounded-standard.pdf', [[170 / mm, 156 / mm]]);
const ordinary = await Promise.all(['UV-vis', 'XRD', 'NMR', 'Spectrum', 'Control', 'Repeat', 'Reference', 'Long-original-name'].map((name) => fixture(`${name}.pdf`, [[55, 50]])));

const mime: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.wasm': 'application/wasm', '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.png': 'image/png' };
const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://localhost').pathname);
    if (pathname === '/favicon.ico') { response.writeHead(204).end(); return; }
    const path = resolve(dist, `.${pathname === '/' ? '/index.html' : pathname}`);
    if (path !== dist && !path.startsWith(`${dist}${sep}`)) { response.writeHead(403).end(); return; }
    response.setHeader('Content-Type', mime[extname(path)] ?? 'application/octet-stream');
    response.end(await readFile(path));
  } catch { response.writeHead(404).end(); }
});
server.listen(0, '127.0.0.1');
await once(server, 'listening');
const address = server.address();
assert.ok(address && typeof address !== 'string');
const origin = `http://127.0.0.1:${address.port}`;
console.log('Edge acceptance: launching actual Microsoft Edge.');
const browser = await chromium.launch({ ...(executablePath ? { executablePath } : { channel: 'msedge' }), headless: true });
console.log('Edge acceptance: browser launched.');
const deadline = setTimeout(() => { console.error('Edge acceptance exceeded its bounded 120-second deadline.'); void browser.close(); }, 120000);
const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1463, height: 1075 }, deviceScaleFactor: 1,
  ...(domDiagnostic ? { reducedMotion: 'reduce' as const } : {}) });
const page = await context.newPage();
console.log('Edge acceptance: page created.');
page.setDefaultTimeout(15000);
const commandKey = process.platform === 'darwin' ? 'Meta' : 'Control';
const errors: string[] = [], warnings: string[] = [], externalRequests: string[] = [], checks: string[] = [], screenshots: string[] = [];
const requests: { method: string; pathname: string; body: boolean }[] = [];
let glassProof: unknown, privateAcceptance: unknown = { status: 'not supplied', scope: 'Synthetic controls do not certify original-data acceptance.' };
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); else if (message.type() === 'warning') warnings.push(message.text()); });
await context.route('**/*', async (route) => {
  const url = route.request().url();
  if (/^https?:/.test(url)) requests.push({ method: route.request().method(), pathname: new URL(url).pathname, body: route.request().postData() !== null });
  if (/^https?:/.test(url) && new URL(url).origin !== origin) { externalRequests.push(url); await route.abort(); }
  else await route.continue();
});
const cell = (row: number, column: number) => page.locator(`[data-row="${row}"][data-column="${column}"]`);
const occupied = async (row: number, column: number) => Boolean(await cell(row, column).getAttribute('data-asset-id'));
const idle = () => page.locator('.app-shell[aria-busy="false"]').waitFor();
async function shot(name: string) {
  console.log(`Edge acceptance: screenshot ${name}.`);
  if (domDiagnostic) return;
  await page.screenshot({ path: join(out, name), animations: 'disabled', timeout: 10000 });
  screenshots.push(name);
}
async function importPicker(files: Fixture[]) {
  const choice = page.waitForEvent('filechooser');
  await page.keyboard.press(`${commandKey}+i`);
  await (await choice).setFiles(files.map((file) => file.path));
  await idle();
}
async function sourceDrag(name: string, target: Locator) { await page.getByRole('button', { name: `Place ${name}`, exact: true }).dragTo(target); }
async function panelAction(name: string) {
  const button = page.getByRole('button', { name, exact: true });
  if (await button.isVisible()) await button.click();
  else {
    await page.locator('.figure-panel.is-selected').first().click({ button: 'right' });
    await page.getByRole('menuitem', { name: name === 'Split' ? 'Split cells' : 'Move / swap…', exact: true }).click();
  }
}
async function externalDrop(file: { name: string; bytes: Uint8Array }, target: Locator) {
  const transfer = await page.evaluateHandle(({ name, bytes }) => {
    const data = new DataTransfer();
    data.items.add(new File([new Uint8Array(bytes)], name, { type: name.endsWith('.pdf') ? 'application/pdf' : 'application/json' }));
    return data;
  }, { name: file.name, bytes: Array.from(file.bytes) });
  await target.dispatchEvent('dragenter', { dataTransfer: transfer });
  await target.dispatchEvent('dragover', { dataTransfer: transfer });
  await target.dispatchEvent('drop', { dataTransfer: transfer });
  await transfer.dispose();
  await idle();
}
async function download(action: () => Promise<unknown>, name: string): Promise<Uint8Array> {
  const pending = page.waitForEvent('download');
  await action();
  const value: Download = await pending;
  const path = join(out, name);
  await value.saveAs(path);
  assert.equal(await value.failure(), null);
  return readFile(path);
}
async function savedProject(name: string): Promise<{ bytes: Uint8Array; document: AssemblyDocument }> {
  const bytes = await download(() => page.getByRole('button', { name: 'Save project', exact: true }).click(), name);
  await idle();
  return { bytes, document: JSON.parse(new TextDecoder().decode(bytes)) as AssemblyDocument };
}
async function assertPreview(locator: Locator) {
  await locator.locator('img.page-preview').first().waitFor();
  const preview = await locator.locator('img.page-preview').first().evaluate(async (image) => {
    const element = image as HTMLImageElement;
    await element.decode();
    return { src: element.currentSrc, width: element.naturalWidth, height: element.naturalHeight };
  });
  assert.match(preview.src, /^data:image\/png;base64,/);
  const png = UPNG.decode(Uint8Array.from(Buffer.from(preview.src.split(',')[1], 'base64')).buffer);
  const pixels = new Uint8Array(UPNG.toRGBA8(png)[0]);
  let nonwhite = 0;
  for (let index = 0; index < pixels.length; index += 4) if (pixels[index + 3] > 0 && Math.min(pixels[index], pixels[index + 1], pixels[index + 2]) < 200) nonwhite++;
  const ink = { width: preview.width, height: preview.height, nonwhite };
  assert.ok(ink.width > 20 && ink.height > 20 && ink.nonwhite > 20, `Real PDF preview must contain visible ink: ${JSON.stringify(ink)}`);
}
async function fonts(pdf: PDFDocument): Promise<string[]> {
  const hashes: string[] = [];
  for (const [, value] of pdf.context.enumerateIndirectObjects()) {
    if (!(value instanceof PDFDict) || String(value.get(PDFName.of('Type'))) !== '/FontDescriptor') continue;
    for (const key of ['FontFile', 'FontFile2', 'FontFile3']) {
      const ref = value.get(PDFName.of(key)), stream = ref ? pdf.context.lookup(ref) : null;
      if (stream instanceof PDFRawStream) hashes.push(sha256(stream.getContents()));
    }
  }
  return hashes;
}
async function checkExport(bytes: Uint8Array, document: AssemblyDocument) {
  const pdf = await PDFDocument.load(bytes);
  assert.equal(pdf.getPageCount(), 1);
  const outputPage = pdf.getPage(0);
  assert.ok(Math.abs(outputPage.getWidth() - document.grid.columns * 60 * mm) < 1e-8);
  assert.ok(Math.abs(outputPage.getHeight() - document.grid.rows * 55 * mm) < 1e-8);
  const objects = outputPage.node.Resources()?.lookup(PDFName.of('XObject'), PDFDict);
  assert.ok(objects);
  const forms = objects.values().map((ref) => pdf.context.lookup(ref)).filter((value): value is PDFRawStream => value instanceof PDFRawStream && String(value.dict.get(PDFName.of('Subtype'))) === '/Form');
  const populated = document.panels.filter((panel) => panel.assetId);
  assert.equal(forms.length, populated.length);
  const outputFonts = await fonts(pdf);
  for (const panel of populated) {
    const source = document.assets.find((asset) => asset.id === panel.assetId)!;
    const oldFonts = await fonts(await PDFDocument.load(Buffer.from(source.bytesBase64, 'base64')));
    assert.ok(oldFonts.length > 0);
    assert.ok(oldFonts.every((hash) => outputFonts.includes(hash)), 'Each embedded source font byte stream survives export.');
  }
  const streams = forms.map((form) => new TextDecoder().decode(decodePDFRawStream(form).decode()));
  assert.ok(streams.every((content) => /0\.35 w/.test(content) && /BT/.test(content) && /\bl\b/.test(content)), 'Source vector paths and real text operators survive as Form content.');
  assert.ok(!streams.some((content) => /\/Image\b/.test(content)), 'The vector fixtures must not be replaced by image content.');
}

async function proveRefraction() {
  const diagnostic = await context.newPage();
  try {
    await diagnostic.goto(origin);
    const group = diagnostic.locator('.grid-group');
    await group.locator('.glass-backdrop[data-lg-active]').waitFor();
    const state = await diagnostic.evaluate(() => {
      const backdrop = document.querySelector('.grid-group > .glass-backdrop')!;
      const foreground = document.querySelector('.grid-group > .glass-foreground')!;
      const tray = document.querySelector('.source-tray-shell > .glass-backdrop')!;
      return { backdrop: getComputedStyle(backdrop).backdropFilter, foreground: getComputedStyle(foreground).filter,
        foregroundBackdrop: getComputedStyle(foreground).backdropFilter, tray: getComputedStyle(tray).backdropFilter,
        scales: Array.from(document.querySelectorAll('feDisplacementMap')).map((element) => Number(element.getAttribute('scale'))),
        passes: document.querySelectorAll('.grid-group [data-lg-active]').length };
    });
    assert.match(state.backdrop, /url\(/);
    assert.ok(state.scales.length >= 3 && state.scales.every((scale) => scale !== 0));
    assert.equal(state.foreground, 'none'); assert.equal(state.foregroundBackdrop, 'none');
    assert.doesNotMatch(state.tray, /url\(/, 'Wide tray must not carry the small-group displacement filter.');
    // Diagnostic-only substrate in a disposable page, never in product captures.
    // It is an earlier sibling of the actual production backdrop, preserving
    // that exact engine/filter/clear-foreground stack.
    await group.evaluate((element) => {
      const pattern = document.createElement('div');
      pattern.setAttribute('data-edge-refraction-diagnostic', '');
      pattern.style.cssText = 'position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(90deg,#444 0 1px,#fff 1px 5px);border-radius:inherit';
      element.prepend(pattern);
    });
    await diagnostic.waitForTimeout(200);
    const active = await group.screenshot({ path: join(out, 'glass-diagnostic-active.png'), animations: 'disabled' });
    const stable = await group.screenshot({ animations: 'disabled' });
    assert.equal(sha256(active), sha256(stable), 'Refraction comparison must use a stable scene.');
    await diagnostic.evaluate(() => document.querySelectorAll('feDisplacementMap').forEach((element) => element.setAttribute('scale', '0')));
    const zero = await group.screenshot({ path: join(out, 'glass-diagnostic-scale-zero.png'), animations: 'disabled' });
    assert.notEqual(sha256(active), sha256(zero), 'Actual Edge pixels must change when only SVG displacement is set to zero.');
    return { ...state, activeSha256: sha256(active), zeroScaleSha256: sha256(zero),
      evidence: ['glass-diagnostic-active.png', 'glass-diagnostic-scale-zero.png'],
      scope: 'Separate diagnostic page with temporary achromatic stripes; same production SVG filter. Normal workbench screenshots retain pure-white background.' };
  } finally { await diagnostic.close(); }
}

async function privateProjectAcceptance(path: string) {
  const original = await readFile(path), originalHash = sha256(original);
  const expected = JSON.parse(original.toString('utf8')) as AssemblyDocument;
  for (const asset of expected.assets) assert.equal(sha256(Buffer.from(asset.bytesBase64, 'base64')), asset.sha256);
  await page.setViewportSize({ width: 1463, height: 1075 });
  await page.keyboard.press(`${commandKey}+n`);
  await externalDrop({ name: 'Original-data.figureassembly', bytes: original }, page.locator('.workspace'));
  assert.equal(await page.locator('.source-item').count(), expected.assets.length);
  assert.equal(await page.locator('.has-source').count(), expected.panels.filter((panel) => panel.assetId).length);
  for (const panel of expected.panels.filter((panel) => panel.assetId)) await assertPreview(cell(panel.row, panel.column));
  await cell(0, 0).click();
  const dismiss = page.getByRole('button', { name: 'Dismiss message', exact: true });
  if (await dismiss.isVisible()) await dismiss.click();
  await shot('04-private-edge-1463x1075.png');
  if (!domDiagnostic) {
    await page.locator('.toolbar').screenshot({ path: join(out, 'private-toolbar.png'), animations: 'disabled', timeout: 10000 });
    await page.locator('.source-tray-shell').screenshot({ path: join(out, 'private-source-tray.png'), animations: 'disabled', timeout: 10000 });
  }
  const saved = await savedProject('private-reopened.figureassembly');
  assert.deepEqual(saved.document, expected);
  const exported = await download(() => page.getByRole('button', { name: 'Export PDF', exact: true }).click(), 'private-publication.pdf');
  const pdf = await PDFDocument.load(exported);
  assert.equal(pdf.getPageCount(), 1);
  assert.ok(Math.abs(pdf.getPage(0).getWidth() - expected.grid.columns * 60 * mm) < 1e-8);
  assert.ok(Math.abs(pdf.getPage(0).getHeight() - expected.grid.rows * 55 * mm) < 1e-8);
  const outputFonts = await fonts(pdf);
  for (const panel of expected.panels.filter((panel) => panel.assetId)) {
    const asset = expected.assets.find((asset) => asset.id === panel.assetId)!;
    const oldFonts = await fonts(await PDFDocument.load(Buffer.from(asset.bytesBase64, 'base64')));
    assert.ok(oldFonts.every((hash) => outputFonts.includes(hash)), 'Original-data font resources remain byte-identical.');
  }
  assert.equal(sha256(await readFile(path)), originalHash, 'Authorized original project is untouched.');
  return { status: 'passed', originalProjectSha256: originalHash, assetCount: expected.assets.length,
    sourceHashes: expected.assets.map(({ sha256 }) => sha256), exportSha256: sha256(exported),
    screenshots: domDiagnostic ? [] : ['04-private-edge-1463x1075.png', 'private-toolbar.png', 'private-source-tray.png'],
    scope: 'Actual authorized portable project opened, previews inspected for ink, original bytes+hashes and exact layout preserved on real download, publication dimensions/font resources verified. No raw package or PDF uploaded.' };
}

async function fileDeliverySmoke() {
  const direct = await context.newPage();
  direct.on('pageerror', (error) => errors.push(`file delivery: ${error.message}`));
  try {
    await direct.goto(pathToFileURL(join(dist, 'index.html')).href);
    await direct.getByRole('button', { name: 'Export PDF', exact: true }).waitFor();
    const choice = direct.waitForEvent('filechooser');
    await direct.keyboard.press(`${commandKey}+i`);
    await (await choice).setFiles(ordinary[0].path);
    await direct.locator('.app-shell[aria-busy="false"]').waitFor();
    await assertPreview(direct.getByRole('button', { name: `Place ${ordinary[0].name}`, exact: true }));
    if (!domDiagnostic) await direct.screenshot({ path: join(out, 'file-delivery-edge.png'), animations: 'disabled', timeout: 10000 });
    return { status: 'passed', sourceSha256: ordinary[0].sha256, scope: 'Actual built file:// entry imports original PDF and renders nonwhite bundled PDFium preview, with no local HTTP server or remote renderer.' };
  } finally { await direct.close(); }
}

try {
  await page.goto('about:blank');
  if (!domDiagnostic) {
    await page.screenshot({ path: join(out, 'edge-about-blank.png'), timeout: 5000 });
    console.log('Edge acceptance: about:blank screenshot succeeded.');
  }
  await page.goto(origin);
  console.log('Edge acceptance: built page navigated.');
  assert.match(await page.title(), /Figure Assembly/);
  console.log('Edge acceptance: title read.');
  const agent = await page.evaluate(() => navigator.userAgent);
  console.log('Edge acceptance: user agent read.');
  assert.match(agent, /Edg\//, 'This acceptance must use actual Microsoft Edge.');
  assert.equal(await page.evaluate(() => Boolean(window.webkit?.messageHandlers?.assembly)), false);
  await page.getByRole('button', { name: 'Export PDF', exact: true }).waitFor();
  assert.equal(await page.locator('[data-panel-id]').count(), 6);
  assert.equal(await page.locator('.source-item').count(), 0);
  assert.equal(await page.locator('footer.status-bar, .source-rail').count(), 0);
  assert.equal(await page.locator('vite-error-overlay, nextjs-portal').count(), 0);
  console.log('Edge acceptance: identity/blank checks passed; fonts:', await page.evaluate(() => document.fonts.status));
  await shot('01-empty-edge-1463x1075.png');
  checks.push('Actual Microsoft Edge, no native bridge, meaningful blank3×2 app, no framework overlay, no old left rail/footer.');
  if (!domDiagnostic) {
    glassProof = await proveRefraction();
    checks.push('Actual Edge SVG displacement changes diagnostic pixels; compact groups have nonzero maps and clear foreground, wide tray has no displacement URL.');
  } else glassProof = { status: 'blocked', reason: 'Explicit DOM-only diagnosis while actual Edge about:blank screenshots time out; pixel refraction proof remains required.' };

  await importPicker([multipage, oversized, rounded, ...ordinary]);
  assert.equal(await page.locator('.source-item').count(), 11);
  await assertPreview(page.getByRole('button', { name: `Place ${ordinary[0].name}`, exact: true }));
  checks.push('Real file picker imports11 original PDFs; bundled PDFium renders nonwhite thumbnail pixels without native preview emulation.');

  await page.getByRole('button', { name: 'Choose grid template' }).click();
  await page.getByRole('button', { name: '2 × 2', exact: true }).click();
  await page.getByRole('button', { name: 'Apply grid', exact: true }).click();
  assert.equal(await page.locator('[data-panel-id]').count(), 4);
  await cell(0, 0).click();
  await page.getByRole('button', { name: `Place ${multipage.name}`, exact: true }).click();
  await page.getByRole('heading', { name: 'Choose a page' }).waitFor();
  await page.getByRole('button', { name: /^Page 2,/ }).click();
  await page.getByRole('button', { name: 'Place page 2' }).click();
  assert.match(await cell(0, 0).getAttribute('aria-label') ?? '', /page 2/);
  await assertPreview(cell(0, 0));
  checks.push('Explicit multipage choice places page2 at original physical size; actual canvas preview contains ink.');

  await cell(0, 1).click({ modifiers: ['Shift'] });
  await page.getByRole('button', { name: 'Merge', exact: true }).click();
  assert.equal(await page.locator('[data-panel-id]').count(), 3);
  await panelAction('Split');
  assert.equal(await page.locator('[data-panel-id]').count(), 4);
  assert.equal(await occupied(0, 0), true);
  await sourceDrag(ordinary[0].name, cell(0, 1));
  assert.equal(await occupied(0, 1), true);
  await cell(0, 0).click(); await cell(0, 1).click({ modifiers: ['Shift'] });
  await page.getByRole('button', { name: 'Merge', exact: true }).click();
  assert.equal(await page.locator('[data-panel-id]').count(), 4);
  assert.match(await page.getByRole('alert').innerText(), /one|source|figure/i);
  checks.push('Adjacent rectangle merge/split retains source; merging two occupied cells refuses atomically. Tray drag places the complete source.');

  await externalDrop(ordinary[1], cell(1, 0));
  assert.equal(await occupied(1, 0), true);
  await assertPreview(cell(1, 0));
  await cell(1, 1).click();
  await page.getByRole('button', { name: `Place ${rounded.name}`, exact: true }).click();
  await page.getByRole('heading', { name: 'This page needs more room' }).waitFor();
  await page.getByRole('button', { name: 'Keep original size', exact: true }).click();
  assert.equal(await occupied(1, 1), false);
  await page.getByRole('button', { name: `Place ${rounded.name}`, exact: true }).click();
  await page.getByRole('button', { name: 'Fit whole page to cell (≈99.94%)', exact: true }).click();
  assert.equal(await occupied(1, 1), true);
  await page.getByRole('button', { name: 'Labels', exact: true }).click();
  assert.equal(await page.locator('.panel-letter').count(), 0);
  await page.getByRole('button', { name: 'Labels', exact: true }).click();
  assert.equal(await page.locator('.panel-letter').count(), 4);
  checks.push('External real PDF drop places a whole page; oversized original choice preserves empty cell; explicit≈99.94%fit and panel letters work.');

  const tray = await page.locator('.source-list').evaluate((element) => ({ width: element.clientWidth, scroll: element.scrollWidth }));
  assert.ok(tray.scroll > tray.width, 'Fixture count forces real horizontal tray overflow.');
  await page.locator('.source-list').evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  assert.ok(await page.locator('.source-list').evaluate((element) => element.scrollLeft) > 0);
  assert.ok(await page.getByRole('button', { name: /Import PDFs|Import sources|Import files/ }).isVisible());
  await page.locator('.source-list').evaluate((element) => { element.scrollLeft = 0; });
  await page.getByLabel('Canvas zoom').selectOption('125');
  await page.getByLabel('Canvas zoom').selectOption('fit');
  await shot('02-populated-edge-1463x1075.png');
  const metrics = await page.evaluate(() => {
    const paper = document.querySelector('.paper')!.getBoundingClientRect();
    const bar = document.querySelector('.selection-bar')!.getBoundingClientRect();
    const toolbar = document.querySelector('.toolbar')!.getBoundingClientRect();
    const tray = document.querySelector('.source-tray')!.getBoundingClientRect();
    return { paper: paper.toJSON(), bar: bar.toJSON(), toolbar: toolbar.toJSON(), tray: tray.toJSON(), bodyWidth: document.body.scrollWidth, innerWidth };
  });
  assert.equal(metrics.bodyWidth, metrics.innerWidth);
  assert.ok(metrics.bar.bottom <= metrics.paper.top || metrics.bar.top >= metrics.paper.bottom, 'Selected controls must not cover the figure.');
  assert.ok(metrics.toolbar.bottom < metrics.paper.top && metrics.paper.bottom <= metrics.tray.top, 'Paper stays between toolbar and horizontal tray.');
  await writeFile(join(out, 'desktop-layout.json'), JSON.stringify(metrics, null, 2));
  checks.push('Horizontal tray scrolls while import remains visible; top zoom changes only the view; no selection-bar/paper overlap at approved1463×1075viewport.');

  await page.keyboard.press(`${commandKey}+n`);
  await page.getByRole('heading', { name: 'Keep your changes?' }).waitFor();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  assert.equal(await page.locator('.has-source').count(), 4);
  let beforeUnload = false;
  const rejectLeave = async (dialog: import('playwright').Dialog) => { assert.equal(dialog.type(), 'beforeunload'); beforeUnload = true; await dialog.dismiss(); };
  page.on('dialog', rejectLeave);
  await page.goto(`${origin}/?unsaved-leave-check`).catch((error: unknown) => { assert.match(String(error), /ERR_ABORTED|net::ERR_ABORTED/); });
  page.off('dialog', rejectLeave);
  assert.equal(beforeUnload, true, 'Real browser navigation prompts for dirty document.');
  assert.equal(await page.locator('.has-source').count(), 4);
  checks.push('New-project cancellation and actual Edge beforeunload dismissal retain the dirty document.');

  const saved = await savedProject('saved.figureassembly');
  assert.equal(await page.getByLabel('Unsaved changes', { exact: true }).count(), 1, 'Download initiation cannot acknowledge a completed disk write.');
  for (const file of [multipage, oversized, rounded, ...ordinary]) {
    const source = saved.document.assets.find((asset) => asset.name === file.name)!;
    assert.ok(source);
    assert.equal(source.bytesBase64, Buffer.from(file.bytes).toString('base64'));
    assert.equal(source.sha256, file.sha256);
  }
  const fitted = saved.document.panels.find((panel) => panel.row === 1 && panel.column === 1)!;
  assert.ok(Math.abs(fitted.scale - 55 * mm / 156) < 1e-14);
  assert.equal(saved.document.panels.find((panel) => panel.row === 0 && panel.column === 0)!.pageIndex, 1);
  await page.getByLabel('Canvas zoom').selectOption('150');
  const zoomed = await savedProject('zoom-only.figureassembly');
  assert.deepEqual(zoomed.document, saved.document, 'Screen zoom must not alter the portable layout or physical scale.');
  await page.getByLabel('Canvas zoom').selectOption('fit');
  checks.push('Real project download embeds exact original bytes+SHA256, explicit page selection, exact fit ratio; zoom does not alter saved layout.');

  const exported = await download(() => page.getByRole('button', { name: 'Export PDF', exact: true }).click(), 'publication.pdf');
  await idle(); await checkExport(exported, saved.document);
  checks.push('Real publication PDF download has exact120×110mmmedia, one Form per complete source, original font byte streams, text operators and thin vector paths.');

  await page.keyboard.press(`${commandKey}+n`);
  await page.getByRole('heading', { name: 'Keep your changes?' }).waitFor();
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  assert.equal(await page.locator('.source-item').count(), 0);
  await externalDrop({ name: 'saved.figureassembly', bytes: saved.bytes }, page.locator('.workspace'));
  assert.equal(await page.locator('.has-source').count(), 4);
  await assertPreview(cell(0, 0));
  const reopened = await savedProject('reopened.figureassembly');
  assert.deepEqual(reopened.document, saved.document);
  await page.getByRole('button', { name: 'Labels', exact: true }).click();
  await externalDrop({ name: 'saved.figureassembly', bytes: saved.bytes }, page.locator('.source-tray'));
  await page.getByRole('heading', { name: 'Keep your changes?' }).waitFor();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  assert.equal(await page.locator('.panel-letter').count(), 0);
  await externalDrop({ name: 'saved.figureassembly', bytes: saved.bytes }, page.locator('.source-tray'));
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  assert.equal(await page.locator('.panel-letter').count(), 4);
  checks.push('Downloaded project reopens from external drop without original paths; dirty project-drop Cancel retains edits, explicit discard restores the package.');

  for (const viewport of [{ width: 1000, height: 700 }, { width: 600, height: 800 }]) {
    await page.setViewportSize(viewport);
    await page.getByLabel('Canvas zoom').selectOption('fit');
    const sizing = await page.evaluate(() => ({ width: innerWidth, body: document.body.scrollWidth,
      exportRight: Array.from(document.querySelectorAll('button')).find((button) => button.textContent?.includes('Export PDF'))!.getBoundingClientRect().right }));
    assert.equal(sizing.body, sizing.width); assert.ok(sizing.exportRight <= sizing.width);
    await shot(`03-edge-${viewport.width}x${viewport.height}.png`);
  }
  checks.push('1000×700and600×800viewports retain primary export without horizontal page overflow.');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const reducedMotion = await page.evaluate(() => ({ enabled: matchMedia('(prefers-reduced-motion: reduce)').matches,
    transitions: Array.from(document.querySelectorAll('.toolbar-control,.button')).map((element) => getComputedStyle(element).transitionDuration) }));
  assert.equal(reducedMotion.enabled, true);
  assert.ok(reducedMotion.transitions.length > 0);
  assert.ok(reducedMotion.transitions.every((duration) => duration.split(',').every((value) => Number.parseFloat(value) <= 0.02)), 'Reduced motion disables animated button travel.');
  await writeFile(join(out, 'reduced-motion.json'), JSON.stringify(reducedMotion, null, 2));
  checks.push('Actual Edge reduced-motion media preference disables animated controls.');
  if (!domDiagnostic) await page.emulateMedia({ reducedMotion: 'no-preference' });
  if (process.env.FIGURE_ASSEMBLY_PRIVATE_PROJECT) {
    privateAcceptance = await privateProjectAcceptance(process.env.FIGURE_ASSEMBLY_PRIVATE_PROJECT);
    checks.push('Authorized original-data portable project opens in real Edge, previews render, exact originals/layout survive download, publication size/fonts retained.');
  }
  const fileDelivery = await fileDeliverySmoke();
  checks.push('Built file:// delivery independently imports an original PDF and renders bundled PDFium preview without a local server.');
  assert.deepEqual(externalRequests, []);
  assert.ok(requests.every((request) => /^(GET|HEAD)$/.test(request.method) && !request.body), 'No application data upload, including to the loopback server.');
  assert.deepEqual(errors, []);
  const status = domDiagnostic ? 'blocked' : 'passed';
  const result = { status, screenshotGate: domDiagnostic ? 'blocked: explicit DOM-only diagnosis does not satisfy screenshot acceptance' : 'passed', browser: 'Actual Microsoft Edge; Browser plugin not available; regular Playwright fallback', executablePath,
    version: browser.version(), userAgent: agent, origin, viewport: { width: 1463, height: 1075 }, nativeBridge: false,
    checks, errors, warnings, externalRequests, requests, screenshots, glassProof, privateAcceptance, fileDelivery,
    diagnosticPreference: domDiagnostic ? 'reduced motion; SVG engine accessibility gate is off, normal-motion visual acceptance remains BLOCKED' : null,
    sourceHashes: [multipage, oversized, rounded, ...ordinary].map(({ name, sha256 }) => ({ name, sha256 })),
    exportSha256: sha256(exported), projectSha256: sha256(saved.bytes) };
  await writeFile(join(out, 'result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ status, checks: checks.length, output: out, version: browser.version() }));
  if (domDiagnostic) process.exitCode = 2;
} catch (error) {
  await shot('failure.png').catch(() => undefined);
  await writeFile(join(out, 'result.json'), JSON.stringify({ status: 'failed', completed: checks, error: String(error), errors, warnings, externalRequests, screenshots }, null, 2));
  throw error;
} finally {
  clearTimeout(deadline);
  await browser.close();
  await new Promise<void>((done) => server.close(() => done()));
}
