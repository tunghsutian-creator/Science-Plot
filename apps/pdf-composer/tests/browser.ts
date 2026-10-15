import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';
import { PDFDocument, rgb } from 'pdf-lib';
import type { ImportedFile, OpenedProject } from '../src/core/types';

interface Harness {
  imports: ImportedFile[][]; open: OpenedProject | null; cancelSave: boolean;
  saved: string[]; exports: { bytesBase64: string; name: string; format: string; dpi: number }[];
  states: { title: string; dirty: boolean }[];
}
declare global { interface Window { __figureBrowser: Harness } }

const out = resolve('test-results/browser');
await mkdir(out, { recursive: true });
const entry = resolve('dist/index.html');
await readFile(entry).catch(() => { throw new Error('Run npm run build before npm run test:browser.'); });

async function pdf(name: string, sizes: [number, number][]): Promise<ImportedFile> {
  const document = await PDFDocument.create();
  for (const [index, [widthMm, heightMm]] of sizes.entries()) {
    const page = document.addPage([widthMm * 72 / 25.4, heightMm * 72 / 25.4]);
    page.drawText(`Synthetic browser fixture ${index + 1}`, { x: 20, y: 25, size: 7 });
    page.drawLine({ start: { x: 20, y: 40 }, end: { x: 80, y: 70 }, color: rgb(0, 0, 1), thickness: 0.4 });
  }
  return { name, bytesBase64: Buffer.from(await document.save()).toString('base64') };
}
const multipage = await pdf('two-pages.pdf', [[60, 55], [40, 35]]);
const oversized = await pdf('large-page.pdf', [[90, 55]]);
const replacement = await pdf('replacement.pdf', [[55, 50]]);
const roundedStandard = await pdf('rounded-standard.pdf', [[170 * 25.4 / 72, 156 * 25.4 / 72]]);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1505, height: 1045 }, deviceScaleFactor: 1 });
page.setDefaultTimeout(10000);
const failures: string[] = [], checks: string[] = [];
page.on('pageerror', (error) => failures.push(error.message));
await page.route(/^https?:/, (route) => route.abort());
await page.addInitScript(() => {
  window.__figureBrowser = { imports: [], open: null, cancelSave: false, saved: [], exports: [], states: [] };
  window.webkit = { messageHandlers: { assembly: { postMessage(raw: unknown) {
    const request = raw as { id: string; method: string; params: Record<string, unknown> };
    const state = window.__figureBrowser;
    let result: unknown = null;
    switch (request.method) {
      case 'importFiles': result = state.imports.shift() ?? []; break;
      case 'openProject': result = state.open; state.open = null; break;
      case 'saveProject':
        if (state.cancelSave) { state.cancelSave = false; result = { cancelled: true }; }
        else { state.saved.push(request.params.text as string); result = { cancelled: false, name: 'Browser fixture.figureassembly', token: `saved-${state.saved.length}` }; }
        break;
      case 'saveExport': state.exports.push(request.params as Harness['exports'][number]); result = { cancelled: false, name: request.params.name }; break;
      case 'setDocumentState': state.states.push(request.params as Harness['states'][number]); break;
      case 'previewPdf':
        queueMicrotask(() => window.__assemblyReply?.({ id: request.id, error: { code: 'browser_preview_not_emulated', message: 'PDFKit previews are checked by the native application test.' } }));
        return;
      case 'verifyTiff': throw new Error('This browser test never emulates native TIFF pixel verification.');
      default: throw new Error(`Unknown bridge method: ${request.method}`);
    }
    queueMicrotask(() => window.__assemblyReply?.({ id: request.id, result }));
  } } } };
});

const cell = (row: number, column: number) => page.locator(`[data-row="${row}"][data-column="${column}"]`);
const occupied = async (row: number, column: number) => Boolean(await cell(row, column).getAttribute('data-asset-id'));
const command = async (action: string) => page.evaluate(async (detail) => {
  window.dispatchEvent(new CustomEvent('assembly-menu', { detail }));
  // Native menu messages arrive outside React events; observe the next painted
  // state before asserting, rather than reading the previous commit immediately.
  await new Promise<void>((complete) => requestAnimationFrame(() => requestAnimationFrame(() => complete())));
}, action);
const queueImport = async (file: ImportedFile) => page.evaluate((value) => { window.__figureBrowser.imports.push([value]); }, file);
const waitIdle = () => page.locator('.app-shell[aria-busy="false"]').waitFor();

try {
  await page.goto(pathToFileURL(entry).href);
  await page.getByRole('button', { name: 'Export PDF', exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  assert.equal(await page.locator('[data-panel-id]').count(), 6);
  assert.equal(await page.locator('.source-item').count(), 0);
  await page.screenshot({ path: resolve(out, 'blank-desktop.png') });
  checks.push('Blank 3 × 2 start, no synthetic data seeded into the application.');

  await queueImport(multipage); await command('import'); await waitIdle();
  await page.getByRole('button', { name: 'Place two-pages.pdf' }).click();
  await page.getByRole('heading', { name: 'Choose a page' }).waitFor();
  await page.getByRole('button', { name: /^Page 2,/ }).click();
  await page.getByRole('button', { name: 'Place page 2' }).click();
  assert.equal(await occupied(0, 0), true);
  assert.match(await cell(0, 0).getAttribute('aria-label') ?? '', /page 2/);
  checks.push('Multipage import requires an explicit page choice; selected page 2 placed at original 100%.');

  await command('undo'); assert.equal(await occupied(0, 0), false);
  await command('redo'); assert.equal(await occupied(0, 0), true);
  await cell(0, 1).click({ modifiers: ['Shift'] });
  await page.getByRole('button', { name: 'Merge', exact: true }).click();
  assert.equal(await page.locator('[data-panel-id]').count(), 5);
  assert.match(await page.locator('.scale-control').innerText(), /100%.*Original/);
  await page.getByRole('button', { name: 'Split', exact: true }).click();
  assert.equal(await page.locator('[data-panel-id]').count(), 6);
  assert.equal(await occupied(0, 0), true);
  checks.push('Shift selection merges only containers; split retains the complete source at 100%.');

  const transfer = await page.evaluateHandle(() => new DataTransfer());
  await cell(0, 0).dispatchEvent('dragstart', { dataTransfer: transfer });
  await page.keyboard.press('Escape');
  await cell(1, 2).dispatchEvent('dragover', { dataTransfer: transfer });
  await cell(1, 2).dispatchEvent('drop', { dataTransfer: transfer });
  await cell(0, 0).dispatchEvent('dragend', { dataTransfer: transfer });
  assert.equal(await occupied(0, 0), true); assert.equal(await occupied(1, 2), false);
  await transfer.dispose();
  await cell(0, 0).dragTo(cell(1, 2));
  assert.equal(await occupied(1, 2), true); assert.equal(await occupied(0, 0), false);
  await command('undo'); assert.equal(await occupied(0, 0), true);
  checks.push('Escape cancels drag without mutation; whole-source drag swap and one native-menu undo work.');

  await cell(0, 0).click();
  await page.getByRole('button', { name: 'Move', exact: true }).click();
  const option = await page.getByLabel('Destination').locator('option').filter({ hasText: 'Row 2, column 3' }).getAttribute('value');
  await page.getByLabel('Destination').selectOption(option!);
  await page.getByRole('button', { name: 'Move / swap', exact: true }).click();
  assert.equal(await occupied(1, 2), true);
  await command('undo'); assert.equal(await occupied(0, 0), true);
  checks.push('Keyboard-accessible Move / swap dialog provides the drag alternative.');

  await cell(0, 0).click(); await queueImport(oversized);
  await page.getByRole('button', { name: 'Replace', exact: true }).click(); await waitIdle();
  await page.getByRole('heading', { name: 'This page needs more room' }).waitFor();
  const priorId = await cell(0, 0).getAttribute('data-asset-id');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  assert.equal(await cell(0, 0).getAttribute('data-asset-id'), priorId);
  await page.getByRole('button', { name: 'Place large-page.pdf' }).click();
  await page.getByRole('button', { name: /^Fit whole page to cell/ }).click();
  assert.equal(await page.locator('dialog[open]').count(), 0);
  assert.match(await page.locator('.scale-control').innerText(), /66\.67%.*Explicit/);
  await command('undo'); assert.equal(await cell(0, 0).getAttribute('data-asset-id'), priorId);
  checks.push('Oversize replacement refuses automatic shrink; cancel preserves placement and explicit fit is undoable.');

  await cell(0, 0).click(); await queueImport(replacement);
  await page.getByRole('button', { name: 'Replace', exact: true }).click(); await waitIdle();
  assert.match(await cell(0, 0).getAttribute('aria-label') ?? '', /replacement\.pdf/);
  await command('undo'); assert.equal(await cell(0, 0).getAttribute('data-asset-id'), priorId);
  await page.getByRole('button', { name: 'Labels', exact: true }).click();
  assert.equal(await page.locator('.panel-letter').count(), 0);
  await page.getByRole('button', { name: 'Labels', exact: true }).click();
  checks.push('Replacement is undoable; panel letters toggle on and off.');

  await page.getByRole('button', { name: 'Choose grid template' }).click();
  await page.getByRole('button', { name: '3 × 3', exact: true }).click();
  await page.getByRole('button', { name: 'Apply grid', exact: true }).click();
  assert.equal(await page.locator('[data-panel-id]').count(), 9);
  await page.getByRole('button', { name: 'Choose grid template' }).click();
  await page.getByLabel('Columns', { exact: true }).fill('4'); await command('undo');
  assert.equal(await page.locator('[data-panel-id]').count(), 9, 'Native text undo must not undo the document.');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await command('undo'); assert.equal(await page.locator('[data-panel-id]').count(), 6);
  checks.push('Grid templates and custom inputs are atomic; native text-field undo does not change layout history.');

  await page.evaluate(() => { window.__figureBrowser.cancelSave = true; });
  await command('save'); await waitIdle();
  assert.match(await page.locator('.document-strip').innerText(), /•/);
  assert.equal(await page.evaluate(() => window.__figureBrowser.saved.length), 0);
  await command('save'); await waitIdle();
  const saved = await page.evaluate(() => window.__figureBrowser.saved.at(-1)!);
  const portable = JSON.parse(saved);
  assert.equal(portable.assets.find((asset: { name: string }) => asset.name === multipage.name).bytesBase64, multipage.bytesBase64);
  await command('new'); assert.equal(await page.locator('.source-item').count(), 0);
  await page.evaluate((text) => { window.__figureBrowser.open = { text, name: 'Reopened.figureassembly', token: 'reopened' }; }, saved);
  await command('open'); await waitIdle();
  assert.equal(await occupied(0, 0), true);
  checks.push('Save cancellation retains dirty state; portable save retains exact source bytes and reopens without source paths.');

  await page.getByRole('button', { name: 'Export PDF', exact: true }).click(); await waitIdle();
  const exported = await page.evaluate(() => window.__figureBrowser.exports.at(-1)!);
  assert.equal(exported.format, 'pdf');
  const bytes = Buffer.from(exported.bytesBase64, 'base64'), output = await PDFDocument.load(bytes);
  assert.equal(output.getPageCount(), 1);
  assert.ok(Math.abs(output.getPage(0).getWidth() - 180 * 72 / 25.4) < 0.001);
  await writeFile(resolve(out, 'synthetic-browser-export.pdf'), bytes);
  checks.push('Primary PDF export uses real engine bytes with the exact 180 × 110 mm page.');

  const image = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 2; canvas.height = 2;
    const context = canvas.getContext('2d')!; context.fillStyle = '#c33'; context.fillRect(0, 0, 2, 2);
    return { name: 'unknown-dpi.png', bytesBase64: canvas.toDataURL('image/png').split(',')[1] };
  });
  await queueImport(image); await command('import'); await waitIdle();
  await cell(0, 1).click(); await page.getByRole('button', { name: 'Place unknown-dpi.png' }).click();
  await page.getByRole('button', { name: 'Export options' }).click();
  await page.getByLabel('Format', { exact: true }).selectOption('png');
  await page.getByLabel('Raster DPI', { exact: true }).selectOption('600');
  assert.match(await page.locator('.dimension-readout').innerText(), /4252 × 2599 px/);
  assert.match(await page.locator('.resolution-list').innerText(), /300 dpi assumed/);
  await page.getByRole('button', { name: 'Export PNG', exact: true }).click(); await waitIdle();
  const rasterRequest = await page.evaluate(() => window.__figureBrowser.exports.at(-1)!);
  assert.equal(rasterRequest.format, 'png'); assert.equal(rasterRequest.dpi, 600);
  checks.push('Auxiliary raster request carries explicit DPI and shows unknown-DPI/source-resolution risk; native raster pixels are a separate gate.');

  await cell(1, 0).click(); await queueImport(roundedStandard); await command('import'); await waitIdle();
  await page.getByRole('button', { name: 'Place rounded-standard.pdf' }).click();
  assert.match(await page.locator('.source-readout').innerText(), /55\.03 mm/);
  await page.getByRole('button', { name: 'Keep original size', exact: true }).click();
  assert.equal(await occupied(1, 0), false);
  await page.getByRole('button', { name: 'Place rounded-standard.pdf' }).click();
  await page.getByRole('button', { name: 'Fit whole page to cell (≈99.94%)', exact: true }).click();
  assert.equal(await page.locator('dialog[open]').count(), 0);
  assert.match(await page.locator('.scale-control').innerText(), /99\.94%.*Explicit scale/);
  await command('save'); await waitIdle();
  const fittedProject = JSON.parse(await page.evaluate(() => window.__figureBrowser.saved.at(-1)!));
  const fittedPanel = fittedProject.panels.find((panel: { row: number; column: number }) => panel.row === 1 && panel.column === 0);
  const exactScale = (55 * (72 / 25.4)) / 156;
  assert.ok(Math.abs(fittedPanel.scale - exactScale) < 1e-14);
  assert.equal(fittedPanel.rowSpan, 1); assert.equal(fittedPanel.columnSpan, 1);
  assert.equal(fittedProject.assets.find((asset: { name: string }) => asset.name === roundedStandard.name).bytesBase64, roundedStandard.bytesBase64);
  checks.push('One-click fit retains exact 99.939430648% whole-page scale in one ordinary cell, displays ≈99.94%, and preserves original bytes plus the original-size choice.');

  await page.setViewportSize({ width: 1000, height: 700 });
  await page.evaluate(() => document.fonts.ready);
  const metrics = await page.evaluate(() => ({ width: innerWidth, body: document.body.scrollWidth,
    exportRight: document.querySelector('.export-buttons')!.getBoundingClientRect().right }));
  assert.equal(metrics.body, metrics.width); assert.ok(metrics.exportRight <= metrics.width);
  await page.screenshot({ path: resolve(out, 'narrow-desktop.png') });
  checks.push('1000 × 700 desktop viewport has no horizontal page or primary-toolbar clipping.');
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await page.evaluate(() => ({ width: innerWidth, body: document.body.scrollWidth,
    exportRight: document.querySelector('.export-buttons')!.getBoundingClientRect().right }));
  assert.equal(mobile.body, mobile.width); assert.ok(mobile.exportRight <= mobile.width);
  await page.screenshot({ path: resolve(out, 'small-viewport.png') });
  checks.push('Small viewport wraps toolbar controls and keeps the primary export accessible.');
  assert.deepEqual(failures, []);
  await writeFile(resolve(out, 'result.json'), JSON.stringify({ status: 'passed', checks,
    browser: 'Playwright Chromium; Browser/IAB tools unavailable',
    previewScope: 'Browser harness explicitly refuses PDFKit preview emulation. Native PDFKit pixels and actual file dialogs are verified separately.',
    screenshots: ['blank-desktop.png', 'narrow-desktop.png', 'small-viewport.png'] }, null, 2));
  console.log(JSON.stringify({ status: 'passed', checks: checks.length, output: out }));
} catch (error) {
  await page.screenshot({ path: resolve(out, 'failure.png') });
  await writeFile(resolve(out, 'result.json'), JSON.stringify({ status: 'failed', completed: checks, error: String(error) }, null, 2));
  throw error;
} finally { await browser.close(); }
