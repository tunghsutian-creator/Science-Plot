import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createDocument, validateDocument, panelSizePt, requiredScale, placeSource,
  clearPanel, setPanelScale, mergePanels, splitPanel, swapPanels, resizeGrid,
  toggleLabels, orderedPanels, panelLetter, PT_PER_MM,
} from '../src/core/document';
import { createHistory, commit, undo, redo } from '../src/core/history';
import { parseProject, serializeProject } from '../src/core/storage';
import { toBase64, fromBase64, sha256 } from '../src/core/bytes';
import type { SourceAsset } from '../src/core/types';

async function asset(width = 60 * PT_PER_MM, height = 55 * PT_PER_MM, name = 'original.pdf'): Promise<SourceAsset> {
  const bytes = new TextEncoder().encode(`immutable source ${name}`);
  const hash = await sha256(bytes);
  return { id: hash, name, kind: 'pdf', sha256: hash, bytesBase64: toBase64(bytes),
    pages: [{ index: 0, widthPt: width, heightPt: height }] };
}

test('all required presets have exact physical dimensions and no extra spacing', () => {
  for (const [rows, columns] of [[2, 2], [2, 3], [3, 2], [3, 3]]) {
    const document = createDocument(rows, columns);
    assert.equal(document.panels.length, rows * columns);
    assert.equal(document.grid.cellWidthMm * columns, 60 * columns);
    assert.equal(document.grid.cellHeightMm * rows, 55 * rows);
    assert.deepEqual(panelSizePt(document, document.panels[0]), { width: 60 * PT_PER_MM, height: 55 * PT_PER_MM });
  }
});

test('oversize placement refuses atomically until user explicitly supplies uniform scale', async () => {
  const document = createDocument(), before = JSON.stringify(document), source = await asset(340, 310);
  assert.throws(() => placeSource(document, document.panels[0].id, source, 0), /larger/);
  assert.equal(JSON.stringify(document), before);
  const scale = requiredScale(document, document.panels[0], source.pages[0]);
  const placed = placeSource(document, document.panels[0].id, source, 0, scale);
  assert.equal(placed.panels[0].scale, scale);
  assert.equal(placed.assets[0].bytesBase64, source.bytesBase64);
});

test('merge changes only container; split preserves whole page, identity and scale', async () => {
  const source = await asset(), document = createDocument();
  const placed = placeSource(document, document.panels[0].id, source, 0);
  const merged = mergePanels(placed, [document.panels[0].id, document.panels[1].id]);
  const panel = merged.panels.find((item) => item.assetId)!;
  assert.equal(panel.columnSpan, 2);
  assert.equal(panel.scale, 1);
  assert.strictEqual(merged.assets[0], source);
  const split = splitPanel(merged, panel.id);
  assert.equal(split.panels.length, 6);
  assert.equal(split.panels.find((item) => item.assetId)!.scale, 1);
});

test('merge rejects holes, duplicate selection and multiple occupied panels without loss', async () => {
  const document = createDocument();
  assert.throws(() => mergePanels(document, [document.panels[0].id, document.panels[2].id]), /rectangle/);
  assert.throws(() => mergePanels(document, [document.panels[0].id, document.panels[0].id]), /distinct/);
  let placed = placeSource(document, document.panels[0].id, await asset(), 0);
  placed = placeSource(placed, document.panels[1].id, await asset(60, 55, 'second.pdf'), 0);
  const before = JSON.stringify(placed);
  assert.throws(() => mergePanels(placed, [document.panels[0].id, document.panels[1].id]), /remove a source/);
  assert.equal(JSON.stringify(placed), before);
});

test('split refuses oversize original instead of silently scaling', async () => {
  const document = createDocument();
  let merged = mergePanels(document, [document.panels[0].id, document.panels[1].id]);
  const panel = merged.panels.find((item) => item.columnSpan === 2)!;
  merged = placeSource(merged, panel.id, await asset(300, 120), 0);
  assert.throws(() => splitPanel(merged, panel.id), /larger/);
  const explicit = setPanelScale(merged, panel.id, 0.5);
  assert.equal(splitPanel(explicit, panel.id).panels.find((item) => item.assetId)!.scale, 0.5);
});

test('swap exchanges entire content and scale, and refuses impossible swaps', async () => {
  const document = createDocument();
  let placed = placeSource(document, document.panels[0].id, await asset(), 0, 0.9);
  const swapped = swapPanels(placed, document.panels[0].id, document.panels[1].id);
  assert.equal(swapped.panels[0].assetId, null);
  assert.equal(swapped.panels[1].scale, 0.9);
  placed = mergePanels(document, [document.panels[0].id, document.panels[1].id]);
  const large = placed.panels.find((item) => item.columnSpan === 2)!;
  placed = placeSource(placed, large.id, await asset(300, 120), 0);
  assert.throws(() => swapPanels(placed, large.id, document.panels[2].id), /larger/);
  assert.equal(placed.panels.find((item) => item.id === large.id)!.scale, 1);
});

test('resize never discards populated sources; enlargement keeps identities', async () => {
  const document = createDocument();
  const placed = placeSource(document, document.panels[5].id, await asset(), 0);
  assert.throws(() => resizeGrid(placed, 1, 1), /remove a source/);
  const expanded = resizeGrid(placed, 3, 3);
  assert.equal(expanded.panels.find((item) => item.id === document.panels[5].id)!.assetId, placed.panels[5].assetId);
  assert.equal(expanded.panels.length, 9);
});

test('undo redo restores replacement, merge and clear including exact source bytes', async () => {
  const document = createDocument(), first = await asset(), second = await asset(120, 100, 'replacement.pdf');
  let history = createHistory(document);
  history = commit(history, placeSource(history.present, document.panels[0].id, first, 0));
  const original = history.present;
  history = commit(history, placeSource(history.present, document.panels[0].id, second, 0));
  history = commit(history, mergePanels(history.present, [document.panels[0].id, document.panels[1].id]));
  history = commit(history, clearPanel(history.present, document.panels[0].id));
  history = undo(undo(undo(history)));
  assert.deepEqual(history.present, original);
  history = redo(redo(redo(history)));
  assert.equal(history.present.panels.find((item) => item.id === document.panels[0].id)!.assetId, null);
  assert.equal(history.present.assets[0].bytesBase64, first.bytesBase64);
  const branched = commit(undo(history), toggleLabels(undo(history).present));
  assert.equal(branched.future.length, 0);
});

test('portable save/reopen needs no source paths and detects corrupted original bytes', async () => {
  const document = createDocument(), source = await asset();
  const placed = placeSource(document, document.panels[0].id, source, 0);
  const saved = await serializeProject(placed);
  assert.deepEqual(await parseProject(saved), placed);
  const corrupt = JSON.parse(saved);
  corrupt.assets[0].bytesBase64 = toBase64(new TextEncoder().encode('different'));
  await assert.rejects(parseProject(JSON.stringify(corrupt)), /source bytes changed/);
});

test('closed project validation refuses unknown fields, overlap, gaps, nonfinite and missing references', async () => {
  for (const mutate of [
    (value: Record<string, unknown>) => { value.secret = 'unknown'; },
    (value: Record<string, unknown>) => { (value.grid as Record<string, unknown>).cellWidthMm = 61; },
    (value: Record<string, unknown>) => { (value.panels as Record<string, unknown>[])[1].column = 0; },
    (value: Record<string, unknown>) => { (value.panels as unknown[]).pop(); },
    (value: Record<string, unknown>) => { (value.panels as Record<string, unknown>[])[0].scale = null; },
    (value: Record<string, unknown>) => { (value.panels as Record<string, unknown>[])[0].assetId = 'missing'; },
  ]) {
    const document = JSON.parse(JSON.stringify(createDocument()));
    mutate(document);
    assert.throws(() => validateDocument(document));
    await assert.rejects(parseProject(JSON.stringify(document)));
  }
});

test('large byte conversion and validation avoid recursive regex stack overflow', async () => {
  const bytes = new Uint8Array(2 * 1024 * 1024).fill(29);
  assert.deepEqual(fromBase64(toBase64(bytes)), bytes);
  const source = await asset();
  source.bytesBase64 = toBase64(bytes);
  source.sha256 = await sha256(bytes);
  const document = createDocument();
  assert.ok(placeSource(document, document.panels[0].id, source, 0));
});

test('labels follow visual order and remain independent of geometry', () => {
  const document = createDocument();
  assert.equal(orderedPanels(document)[0].id, document.panels[0].id);
  assert.deepEqual([0, 25, 26, 27, 51, 52].map(panelLetter), ['a', 'z', 'aa', 'ab', 'az', 'ba']);
  assert.deepEqual(toggleLabels(document, false).grid, document.grid);
});
