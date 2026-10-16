import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { basename, dirname, extname, join, resolve, sep } from 'node:path';
import UPNG from '@pdf-lib/upng';
import { PDFDocument } from 'pdf-lib';
import { chromium, type FileChooser, type Locator } from 'playwright';
import type { AssemblyDocument } from '../src/core/types';

interface MotionSample { surface: string; duration: number; frames: string }
declare global { interface Window { __previewMotion: { samples: MotionSample[]; timer: number } } }

// Independent, focused actual-Edge acceptance for the preview interactions.
// No native bridge, picker mock, React state hook or renderer substitute.
const out = resolve(process.env.FIGURE_ASSEMBLY_PREVIEW_OUT ?? 'test-results/preview-edge');
const dist = resolve(process.env.FIGURE_ASSEMBLY_PREVIEW_DIST ?? 'dist');
const fixtureRoot = join(out, 'fixtures');
await mkdir(fixtureRoot, { recursive: true });
const builtHtml = await readFile(join(dist, 'index.html'));
const sha256 = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
let sourceHead: string | null = null;
try { sourceHead = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(); } catch { /* Source archives may have no Git metadata. */ }
const png = (UPNG as unknown as { default?: typeof UPNG }).default ?? UPNG;

async function pdf(path: string, text: string) {
  const document = await PDFDocument.create();
  document.setCreationDate(new Date('2026-10-16T00:00:00Z'));
  document.setModificationDate(new Date('2026-10-16T00:00:00Z'));
  const page = document.addPage([55 * 72 / 25.4, 50 * 72 / 25.4]);
  page.drawText(text, { x: 8, y: 70, size: 7 });
  page.drawLine({ start: { x: 10, y: 20 }, end: { x: 120, y: 100 }, thickness: 0.4 });
  const bytes = await document.save();
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, bytes);
  return { path, name: basename(path), bytes, sha256: sha256(bytes) };
}

const first = await pdf(join(fixtureRoot, 'first.pdf'), 'Generated first-page control');
const replacement = await pdf(join(fixtureRoot, 'replacement.pdf'), 'Generated replacement control');
const folder = join(fixtureRoot, 'recursive-folder');
// Deliberately create siblings in a different order from their relative paths.
const later = await pdf(join(folder, 'b', 'shared.pdf'), 'Generated later duplicate name');
const earlier = await pdf(join(folder, 'a', 'shared.pdf'), 'Generated earlier duplicate name');
const upper = await pdf(join(folder, 'a', 'Alpha.PDF'), 'Generated uppercase extension');
await mkdir(join(folder, 'c'), { recursive: true });
const pixels = new Uint8Array(4 * 4 * 4);
for (let index = 0; index < pixels.length; index += 4) pixels.set([30, 90, 150, 255], index);
const rasterBytes = new Uint8Array(png.encode([pixels.buffer], 4, 4, 0));
const rasterPath = join(folder, 'c', 'control.PNG');
await writeFile(rasterPath, rasterBytes);
await writeFile(join(folder, 'b', 'broken.pdf'), 'This is not a PDF document.');
await writeFile(join(folder, 'notes.txt'), 'Unsupported text fixture; do not import as an image.');
await writeFile(join(folder, 'a', 'ignored.svg'), '<svg xmlns="http://www.w3.org/2000/svg"/>');
const expectedFolder = [upper, earlier, later, { path: rasterPath, name: 'control.PNG', bytes: rasterBytes, sha256: sha256(rasterBytes) }];

const mime: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.wasm': 'application/wasm', '.png': 'image/png', '.svg': 'image/svg+xml', '.ttf': 'font/ttf' };
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url ?? '/', 'http://localhost').pathname);
    if (path === '/favicon.ico') { response.writeHead(204).end(); return; }
    const file = resolve(dist, `.${path === '/' ? '/index.html' : path}`);
    if (file !== dist && !file.startsWith(`${dist}${sep}`)) { response.writeHead(403).end(); return; }
    response.setHeader('Content-Type', mime[extname(file)] ?? 'application/octet-stream');
    response.end(await readFile(file));
  } catch { response.writeHead(404).end(); }
});
server.listen(0, '127.0.0.1');
await once(server, 'listening');
const address = server.address();
assert.ok(address && typeof address !== 'string');
const origin = `http://127.0.0.1:${address.port}`;
const executablePath = process.env.FIGURE_ASSEMBLY_EDGE_EXECUTABLE;
const browser = await chromium.launch({ ...(executablePath ? { executablePath } : { channel: 'msedge' }), headless: true });
// Video may wait for a first compositor frame while creating the page. Bound
// setup too, rather than starting the deadline only after newPage resolves.
const deadline = setTimeout(() => { console.error('Focused actual Edge preview exceeded 90 seconds.'); void browser.close(); }, 90000);
async function setupFailed(error: unknown, phase: string): Promise<never> {
  clearTimeout(deadline);
  await writeFile(join(out, 'result.json'), JSON.stringify({ status: 'failed', phase, sourceHead,
    browser: 'Actual Microsoft Edge; recording setup did not reach application checks', version: browser.version(),
    builtHtmlSha256: sha256(builtHtml), checks: [], error: String(error),
    scope: 'A recording/page initialization failure is not application acceptance or a successful video.' }, null, 2));
  await browser.close(); server.close();
  throw error;
}
console.log('Preview Edge: create video context.');
const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1463, height: 1075 }, deviceScaleFactor: 1,
  recordVideo: { dir: join(out, 'video'), size: { width: 1463, height: 1075 } } }).catch((error: unknown) => setupFailed(error, 'video context'));
console.log('Preview Edge: start trace.');
await context.tracing.start({ screenshots: true, snapshots: true, sources: true }).catch((error: unknown) => setupFailed(error, 'trace setup'));
console.log('Preview Edge: create recorded page.');
const page = await context.newPage().catch((error: unknown) => setupFailed(error, 'recorded page / first frame'));
console.log('Preview Edge: recorded page created.');
page.setDefaultTimeout(12000);
const errors: string[] = [], warnings: string[] = [], externalRequests: string[] = [], writes: string[] = [], checks: string[] = [], screenshots: string[] = [];
const popupBounds: unknown[] = [];
let failure: unknown, userAgent = '', motions: MotionSample[] = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); else if (message.type() === 'warning') warnings.push(message.text()); });
await context.route('**/*', async (route) => {
  const request = route.request(), url = request.url();
  if (/^https?:/.test(url) && new URL(url).origin !== origin) { externalRequests.push(url); await route.abort(); }
  else { if (request.postData() !== null || !['GET', 'HEAD'].includes(request.method())) writes.push(url); await route.continue(); }
});
const cell = (row: number, column: number) => page.locator(`[data-row="${row}"][data-column="${column}"]`);
const idle = () => page.locator('.app-shell[aria-busy="false"]').waitFor();
async function screenshot(name: string) {
  await page.evaluate(async () => { await Promise.allSettled(document.getAnimations().map((animation) => animation.finished)); });
  await page.screenshot({ path: join(out, name), timeout: 10000 });
  screenshots.push(name);
}
async function picker(action: () => Promise<unknown>): Promise<FileChooser> {
  const choice = page.waitForEvent('filechooser');
  await action();
  return choice;
}
async function save(name: string): Promise<AssemblyDocument> {
  const pending = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save project', exact: true }).click();
  const download = await pending;
  await download.saveAs(join(out, name));
  assert.equal(await download.failure(), null);
  await idle();
  return JSON.parse(await readFile(join(out, name), 'utf8')) as AssemblyDocument;
}
async function assertPopupBounds(popup: Locator, name: string) {
  await popup.evaluate(async (element) => { await Promise.allSettled(element.getAnimations({ subtree: true }).map((animation) => animation.finished)); });
  assert.equal(await popup.evaluate((element) => Number(getComputedStyle(element).opacity)), 1, 'The actual popover entrance finishes before evidence capture.');
  const bounds = await popup.boundingBox();
  assert.ok(bounds);
  const viewport = page.viewportSize()!;
  assert.ok(bounds.x >= 7 && bounds.y >= 7 && bounds.x + bounds.width <= viewport.width - 7 && bounds.y + bounds.height <= viewport.height - 7,
    `Anchored ${name} must remain inside viewport: ${JSON.stringify({ bounds, viewport })}`);
  assert.equal(await popup.getAttribute('aria-modal'), 'false');
  assert.equal(await page.locator('dialog[open]').count(), 0, 'Control popovers must not open a centered modal dialog.');
  assert.equal(await page.locator('.control-popover').count(), 1);
  popupBounds.push({ name, bounds, viewport });
}
async function zoom(value: string) {
  await page.getByRole('button', { name: 'Canvas zoom', exact: true }).click();
  await page.getByRole('menuitemradio', { name: value === 'fit' ? 'Fit to view' : `${value}%`, exact: true }).click();
}

try {
  await page.goto(origin);
  userAgent = await page.evaluate(() => navigator.userAgent);
  assert.match(userAgent, /Edg\//, 'This focused recording must run in actual Microsoft Edge.');
  assert.match(await page.title(), /Figure Assembly/);
  assert.equal(await page.evaluate(() => Boolean(window.webkit?.messageHandlers?.assembly)), false);
  await page.getByRole('button', { name: 'Export PDF', exact: true }).waitFor();
  assert.equal(await page.locator('.figure-panel').count(), 6);
  assert.equal(await page.locator('.selection-bar').count(), 0, 'A blank document starts without a selected cell or action bar.');
  assert.equal(await page.locator('vite-error-overlay,nextjs-portal').count(), 0);
  const styles = await page.evaluate(() => ({ body: getComputedStyle(document.body).backgroundColor,
    effects: Array.from(document.querySelectorAll('.toolbar,.toolbar-control,.source-tray-shell,.toolbar-popover,.control-popover,.panel-menu,.selection-bar')).map((element) => ({ filter: getComputedStyle(element).filter, backdrop: getComputedStyle(element).backdropFilter })),
    displacementMaps: document.querySelectorAll('feDisplacementMap').length }));
  assert.equal(styles.displacementMaps, 0);
  assert.ok(styles.effects.length > 0 && styles.effects.every((effect) => effect.filter === 'none' && effect.backdrop === 'none'), 'The minimal preview has no blur or SVG refraction surfaces.');
  await page.evaluate(() => {
    window.__previewMotion = { samples: [], timer: window.setInterval(() => {
      for (const element of document.querySelectorAll('.selection-bar,.source-placement,.source-placement img')) {
        for (const animation of element.getAnimations()) {
          const duration = animation.effect?.getTiming().duration;
          if (typeof duration !== 'number' || duration <= 0 || !(animation.effect instanceof KeyframeEffect)) continue;
          const sample = { surface: element.matches('.selection-bar') ? 'selection' : 'source', duration,
            frames: JSON.stringify(animation.effect.getKeyframes().map((frame) => ({ opacity: frame.opacity, transform: frame.transform }))) };
          if (!window.__previewMotion.samples.some((old) => old.surface === sample.surface && old.duration === sample.duration && old.frames === sample.frames)) window.__previewMotion.samples.push(sample);
        }
      }
    }, 16) };
  });
  await screenshot('01-minimal-empty-edge.png');
  checks.push('Actual Edge built app, no native bridge, no initial selection/action bar, no error overlay, no blur or displacement engine.');

  const controls = [{ trigger: 'Choose grid template', dialog: 'Grid layout' }, { trigger: 'Labels', dialog: 'Panel labels' }, { trigger: 'Canvas zoom', dialog: 'Canvas zoom' }];
  for (const control of controls) {
    const trigger = page.getByRole('button', { name: control.trigger, exact: true });
    await trigger.click();
    const popup = page.getByRole('dialog', { name: control.dialog, exact: true });
    await popup.waitFor(); await assertPopupBounds(popup, control.dialog);
    assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
    await screenshot(`02-${control.dialog.replaceAll(' ', '-').toLowerCase()}.png`);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.control-popover').count(), 0);
    assert.equal(await trigger.evaluate((element) => document.activeElement === element), true, 'Escape restores the trigger focus.');
    await trigger.click();
    await page.locator('.tray-heading').click();
    assert.equal(await page.locator('.control-popover').count(), 0, 'Clicking outside dismisses the anchored control.');
  }
  await page.getByRole('button', { name: 'Choose grid template', exact: true }).click();
  await page.getByRole('button', { name: 'Labels', exact: true }).click();
  assert.equal(await page.getByRole('dialog', { name: 'Grid layout', exact: true }).count(), 0);
  assert.equal(await page.getByRole('dialog', { name: 'Panel labels', exact: true }).count(), 1);
  await page.keyboard.press('Escape');
  for (const viewport of [{ width: 600, height: 800 }, { width: 390, height: 560 }]) {
    await page.setViewportSize(viewport);
    for (const control of controls) {
      await page.getByRole('button', { name: control.trigger, exact: true }).click();
      await assertPopupBounds(page.getByRole('dialog', { name: control.dialog, exact: true }), control.dialog);
      await screenshot(`03-${viewport.width}-${control.dialog.replaceAll(' ', '-').toLowerCase()}.png`);
      await page.keyboard.press('Escape');
    }
  }
  await page.setViewportSize({ width: 1463, height: 1075 });
  checks.push('Grid/Labels/Zoom are singly open anchored popovers; outside/Escape dismiss and focus returns, with all edges visible at 1463/600/390 px.');

  const before = await save('blank-before.figureassembly');
  const canceled = await picker(() => cell(0, 2).click());
  assert.equal(canceled.isMultiple(), false);
  await canceled.setFiles([]); await idle();
  assert.deepEqual(await save('blank-after-empty-choice.figureassembly'), before);
  const selected = await picker(() => cell(1, 1).click());
  assert.equal(selected.isMultiple(), false);
  await selected.setFiles(first.path); await idle();
  await cell(1, 1).locator('img.page-preview').waitFor();
  await page.waitForFunction(() => { const image = document.querySelector<HTMLImageElement>('[data-row="1"][data-column="1"] img'); return image?.complete && image.naturalWidth > 20; });
  const placed = await save('placed.figureassembly');
  assert.equal(await page.locator('.selection-bar').evaluate((element) => getComputedStyle(element).backdropFilter), 'none');
  const placedPanel = placed.panels.find((panel) => panel.row === 1 && panel.column === 1)!;
  assert.ok(placedPanel.assetId);
  assert.equal(placed.panels.filter((panel) => panel.assetId).length, 1);
  assert.equal(placed.assets.find((asset) => asset.id === placedPanel.assetId)?.sha256, first.sha256);
  let unexpectedPicker = 0;
  const countPicker = () => { unexpectedPicker++; };
  page.on('filechooser', countPicker);
  await cell(1, 1).click();
  await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  page.off('filechooser', countPicker);
  assert.equal(unexpectedPicker, 0, 'Clicking an occupied panel selects it without reopening a picker.');
  assert.equal(await cell(1, 1).getAttribute('class').then((value) => value?.includes('is-selected')), true);
  const cancelReplace = await picker(() => page.getByRole('button', { name: 'Replace', exact: true }).click());
  await cancelReplace.setFiles([]); await idle();
  assert.deepEqual(await save('after-cancel-replace.figureassembly'), placed);
  const replace = await picker(() => page.getByRole('button', { name: 'Replace', exact: true }).click());
  await replace.setFiles(replacement.path); await idle();
  const replaced = await save('replaced.figureassembly');
  const newPanel = replaced.panels.find((panel) => panel.id === placedPanel.id)!;
  assert.equal(replaced.assets.find((asset) => asset.id === newPanel.assetId)?.sha256, replacement.sha256);
  assert.equal(replaced.panels.filter((panel) => panel.assetId).length, 1);
  await screenshot('04-target-placement-edge.png');
  checks.push('Real empty-cell single-file chooser targets that exact cell; empty choice and Replace cancellation preserve the portable document; occupied click selects and only Replace opens a picker.');

  const folderChoice = await picker(() => page.getByRole('button', { name: 'Import folder', exact: true }).click());
  assert.equal(await folderChoice.element().getAttribute('webkitdirectory') !== null, true);
  await folderChoice.setFiles(folder); await idle();
  const folderNotice = (await page.getByRole('status').allTextContents()).join(' ');
  assert.match(folderNotice, /Imported 4 sources from folder\./);
  assert.match(folderNotice, /Skipped 2 unsupported, 1 unreadable or invalid/);
  assert.match(folderNotice, /broken\.pdf/);
  await writeFile(join(out, 'folder-notice.json'), JSON.stringify({ text: folderNotice }, null, 2));
  await screenshot('05-recursive-folder-edge.png');
  const imported = await save('folder-import.figureassembly');
  assert.deepEqual(imported.panels, replaced.panels, 'Folder import adds library sources without placing or replacing any panel.');
  assert.deepEqual(imported.grid, replaced.grid);
  const added = imported.assets.slice(replaced.assets.length);
  assert.deepEqual(added.map((asset) => asset.name), expectedFolder.map((file) => file.name));
  assert.deepEqual(added.map((asset) => asset.sha256), expectedFolder.map((file) => file.sha256), 'Relative path codepoint ordering must distinguish same-name files by their actual bytes.');
  assert.equal(added.filter((asset) => asset.name === 'shared.pdf').length, 2);
  for (const [index, source] of added.entries()) assert.equal(source.bytesBase64, Buffer.from(expectedFolder[index].bytes).toString('base64'));
  const sourceList = page.getByRole('region', { name: 'Source pages', exact: true });
  const scroll = await sourceList.evaluate((element) => ({ top: element.scrollTop, height: element.clientHeight, total: element.scrollHeight }));
  assert.ok(scroll.total > scroll.height, 'The real imported library overflows vertically.');
  const importBefore = await page.getByRole('button', { name: 'Import folder', exact: true }).boundingBox();
  await sourceList.hover(); await page.mouse.wheel(0, scroll.total);
  await page.waitForFunction((before) => document.querySelector('.source-list')!.scrollTop > before, scroll.top);
  assert.deepEqual(await page.getByRole('button', { name: 'Import folder', exact: true }).boundingBox(), importBefore);
  await screenshot('06-library-scroll-edge.png');
  await page.mouse.wheel(0, -scroll.total);
  await page.waitForFunction(() => document.querySelector('.source-list')!.scrollTop === 0);
  checks.push('Real recursive folder picker accepts PDF/PNG case-insensitively, preserves both same-name originals in relative-path order, rejects malformed/unsupported files and only adds valid library assets.');

  const gridTrigger = page.getByRole('button', { name: 'Choose grid template', exact: true });
  await page.mouse.move(1300, 950);
  const normalBackground = await gridTrigger.evaluate((element) => getComputedStyle(element).backgroundColor);
  await gridTrigger.hover();
  await screenshot('07-hover-edge.png');
  const hover = await gridTrigger.evaluate((element) => ({ duration: getComputedStyle(element).transitionDuration,
    property: getComputedStyle(element).transitionProperty, background: getComputedStyle(element).backgroundColor }));
  assert.notEqual(hover.background, normalBackground, 'Real pointer hover changes the control appearance.');
  assert.ok(hover.duration.split(',').some((value) => Math.abs(Number.parseFloat(value) * 1000 - 140) < 1), 'Minimal hover transition is 140 ms.');
  motions = await page.evaluate(() => [...window.__previewMotion.samples]);
  assert.ok(motions.some((sample) => sample.surface === 'selection' && sample.duration === 180), 'The actual selected-action bar animates for 180 ms.');
  assert.ok(motions.some((sample) => sample.surface === 'source' && sample.duration === 220), 'An actual rendered source entrance animates for 220 ms.');
  assert.ok(motions.every((sample) => sample.duration <= 220), 'No sampled placement/selection motion exceeds the bounded duration.');
  await zoom('125'); await zoom('fit');
  const zoomed = await save('after-view-zoom.figureassembly');
  assert.deepEqual(zoomed, imported, 'Popover view zoom does not change physical document state or originals.');
  await page.getByRole('button', { name: 'Labels', exact: true }).click();
  await page.getByRole('switch', { name: 'Show panel letters', exact: true }).click();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.panel-letter').count(), 0);
  checks.push('Actual 140 ms hover, 180 ms action-bar and 220 ms rendered-source motions are observed; zoom preserves all portable state and Labels popover toggles letters.');

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => { window.__previewMotion.samples = []; });
  const commandKey = process.platform === 'darwin' ? 'Meta' : 'Control';
  await page.keyboard.press(`${commandKey}+n`);
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  assert.equal(await page.locator('.selection-bar').count(), 0);
  const reducedPicker = await picker(() => cell(0, 0).click());
  await reducedPicker.setFiles(first.path); await idle();
  await cell(0, 0).locator('img.page-preview').waitFor();
  const reduced = await page.evaluate(() => ({ enabled: matchMedia('(prefers-reduced-motion: reduce)').matches,
    samples: window.__previewMotion.samples,
    durations: Array.from(document.querySelectorAll('.toolbar-control,.selection-bar,.source-placement')).map((element) => ({ transition: getComputedStyle(element).transitionDuration, animation: getComputedStyle(element).animationDuration })) }));
  assert.equal(reduced.enabled, true);
  assert.deepEqual(reduced.samples, []);
  assert.ok(reduced.durations.length > 0 && reduced.durations.every((timing) => [timing.transition, timing.animation].every((list) => list.split(',').every((value) => Number.parseFloat(value) === 0))));
  await screenshot('08-reduced-motion-edge.png');
  await writeFile(join(out, 'motion.json'), JSON.stringify({ normal: motions, hover, reduced }, null, 2));
  checks.push('Actual reduced-motion media removes selection/source animations and control transitions.');
  assert.deepEqual(errors, []); assert.deepEqual(externalRequests, []); assert.deepEqual(writes, []);
} catch (error) {
  failure = error;
  await page.screenshot({ path: join(out, 'failure.png'), timeout: 10000 }).catch(() => {});
} finally {
  clearTimeout(deadline);
  await context.tracing.stop({ path: join(out, 'trace.zip') }).catch((error: unknown) => { failure ??= error; });
  await context.close().catch((error: unknown) => { failure ??= error; });
  const video = page.video();
  if (video) { await video.saveAs(join(out, 'preview-edge.webm')).catch((error: unknown) => { failure ??= error; }); await video.delete().catch(() => {}); }
  else failure ??= new Error('Actual Edge page video was not recorded.');
  await browser.close();
  server.close();
}
const video = await stat(join(out, 'preview-edge.webm')).catch(() => null);
const trace = await stat(join(out, 'trace.zip')).catch(() => null);
if (!video || video.size < 1024 || !trace || trace.size < 1024) failure ??= new Error('Actual Edge video/trace evidence is missing or empty.');
await writeFile(join(out, 'result.json'), JSON.stringify({ status: failure ? 'failed' : 'passed', sourceHead,
  builtHtmlSha256: sha256(builtHtml), testSha256: sha256(await readFile(new URL(import.meta.url))),
  browser: 'Actual Microsoft Edge; Browser plugin unavailable, regular Playwright', version: browser.version(), userAgent, nativeBridge: false,
  checks, errors, warnings, externalRequests, writes, popupBounds, motions, screenshots,
  video: { path: 'preview-edge.webm', bytes: video?.size, scope: 'Actual browser page frames; operating-system picker windows are outside the page capture. Filechooser events and real file/directory inputs are separately asserted. Empty setFiles exercises browser no-selection delivery, not a human OS Cancel claim.' },
  trace: { path: 'trace.zip', bytes: trace?.size }, ...(failure ? { error: String(failure), stack: failure instanceof Error ? failure.stack : undefined } : {}) }, null, 2));
if (failure) throw failure;
console.log(JSON.stringify({ status: 'passed', checks: checks.length, output: out, video: 'preview-edge.webm' }));
