import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PDFDocument } from 'pdf-lib';
import UPNG from '@pdf-lib/upng';
import { folderImportNotice, inspectFolderSources, orderFolderFiles } from '../src/folderImport';
import { fromBase64, sha256 } from '../src/core/bytes';
import { createDocument, MAX_SOURCE_BYTES, MAX_TOTAL_BYTES, validateDocument } from '../src/core/document';
import { parseProject, serializeProject } from '../src/core/storage';

const pngCodec = (UPNG as unknown as { default?: typeof UPNG }).default ?? UPNG;

async function pdfBytes(text = 'Original source'): Promise<Uint8Array> {
  const pdf = await PDFDocument.create();
  pdf.addPage([120, 100]).drawText(text, { x: 8, y: 20, size: 9 });
  return pdf.save();
}

function file(path: string, bytes: Uint8Array): File {
  const value = new File([Uint8Array.from(bytes).buffer], path.split('/').at(-1)!);
  Object.defineProperty(value, 'webkitRelativePath', { value: path });
  return value;
}

test('nested folder order is independent of incoming enumeration and keeps duplicate original names and bytes', async () => {
  const a = await pdfBytes('A'), b = await pdfBytes('B');
  const png = new Uint8Array(pngCodec.encode([Uint8Array.of(255, 0, 0, 255).buffer], 1, 1, 0));
  const files = [file('Sources/z/same.pdf', b), file('Sources/b/marker.PNG', png), file('Sources/a/same.pdf', a)];
  assert.deepEqual(orderFolderFiles(files).map((item) => item.webkitRelativePath), ['Sources/a/same.pdf', 'Sources/b/marker.PNG', 'Sources/z/same.pdf']);
  const result = await inspectFolderSources(files, []);
  assert.deepEqual(result.assets.map((asset) => asset.name), ['same.pdf', 'marker.PNG', 'same.pdf']);
  assert.deepEqual(result.assets.map((asset) => result.relativePaths[asset.id]), ['Sources/a/same.pdf', 'Sources/b/marker.PNG', 'Sources/z/same.pdf']);
  for (const [index, original] of [a, png, b].entries()) {
    assert.deepEqual(fromBase64(result.assets[index].bytesBase64), original);
    assert.equal(result.assets[index].sha256, await sha256(original));
  }
  assert.equal(new Set(result.assets.map((asset) => asset.id)).size, 3);
  assert.equal(result.assets[1].kind, 'png');
  assert.equal(result.invalid + result.unsupported + result.limited, 0);
});

test('same-name, same-content files remain two sources and a folder import leaves every panel unchanged through portable reopen', async () => {
  const bytes = await pdfBytes(), document = createDocument();
  const result = await inspectFolderSources([file('Folder/one/same.pdf', bytes), file('Folder/two/same.pdf', bytes)], []);
  assert.equal(result.assets.length, 2);
  assert.notEqual(result.assets[0].id, result.assets[1].id);
  assert.equal(result.assets[0].sha256, result.assets[1].sha256);
  const imported = { ...document, assets: result.assets };
  validateDocument(imported);
  assert.deepEqual(imported.panels, document.panels);
  const reopened = await parseProject(await serializeProject(imported));
  assert.equal(reopened.assets.length, 2);
  assert.deepEqual(reopened.panels, document.panels);
  assert.deepEqual(reopened.assets.map((asset) => asset.bytesBase64), result.assets.map((asset) => asset.bytesBase64));
  assert.equal('relativePaths' in reopened, false);
});

test('unsupported TIFF and other files, corrupt sources and unreadable files are reported without discarding valid siblings', async () => {
  const unreadable = file('Folder/c/unreadable.pdf', await pdfBytes());
  Object.defineProperty(unreadable, 'arrayBuffer', { value: async () => { throw new Error('The original file could not be read.'); } });
  const result = await inspectFolderSources([
    file('Folder/z/good.PDF', await pdfBytes()), file('Folder/b/broken.pdf', new TextEncoder().encode('not a pdf')),
    unreadable, file('Folder/a/notes.txt', new TextEncoder().encode('notes')), file('Folder/a/original.tiff', Uint8Array.of(73, 73)),
  ], []);
  assert.equal(result.assets.length, 1); assert.equal(result.assets[0].name, 'good.PDF');
  assert.equal(result.unsupported, 2); assert.equal(result.invalid, 2); assert.equal(result.limited, 0);
  assert.deepEqual(result.failures.map((failure) => failure.name), ['broken.pdf', 'unreadable.pdf']);
  assert.match(folderImportNotice(result), /Imported 1 source from folder/);
  assert.match(folderImportNotice(result), /2 unsupported, 2 unreadable or invalid/);
  assert.match(folderImportNotice(result), /Supported: PDF, PNG and JPEG/);
});

test('existing source count and byte budgets are enforced before reads, with deterministic partial results', async () => {
  const bytes = await pdfBytes();
  const initial = (await inspectFolderSources([file('base.pdf', bytes)], [])).assets[0];
  const inventory = Array.from({ length: 99 }, (_, index) => ({ ...initial, id: `existing-${index}` }));
  const result = await inspectFolderSources([file('Folder/z/last.pdf', bytes), file('Folder/a/first.pdf', bytes)], inventory);
  assert.equal(result.assets.length, 1); assert.equal(result.assets[0].name, 'first.pdf'); assert.equal(result.limited, 1);
  const oversized = file('Folder/oversized.pdf', Uint8Array.of(1));
  Object.defineProperty(oversized, 'size', { value: MAX_SOURCE_BYTES + 1 });
  Object.defineProperty(oversized, 'arrayBuffer', { value: async () => { throw new Error('An oversized file must never be read.'); } });
  const limited = await inspectFolderSources([oversized], []);
  assert.equal(limited.limited, 1); assert.equal(limited.invalid, 0);
  // A valid large but unreferenced PDF stream keeps this boundary test small in
  // memory: the 99 existing entries share one immutable original byte string.
  const large = await PDFDocument.create();
  large.addPage([120, 100]);
  large.context.register(large.context.stream(new Uint8Array(1_200_000)));
  const budgetSource = (await inspectFolderSources([file('budget-source.pdf', await large.save())], [])).assets[0];
  const budgetInventory = Array.from({ length: 99 }, (_, index) => ({ ...budgetSource, id: `budget-${index}` }));
  const remaining = MAX_TOTAL_BYTES - 99 * fromBase64(budgetSource.bytesBase64).length;
  assert.ok(remaining > 0 && remaining < MAX_SOURCE_BYTES);
  const cannotFit = file('Folder/over-budget.pdf', Uint8Array.of(1));
  Object.defineProperty(cannotFit, 'size', { value: remaining + 1 });
  Object.defineProperty(cannotFit, 'arrayBuffer', { value: async () => { throw new Error('A file beyond the remaining budget must never be read.'); } });
  const budget = await inspectFolderSources([cannotFit], budgetInventory);
  assert.equal(budget.limited, 1); assert.equal(budget.invalid, 0);
  assert.match(folderImportNotice(budget), /1 over project limits/);
});

test('an empty folder result is harmless and does not manufacture sources or placements', async () => {
  const result = await inspectFolderSources([], []);
  assert.deepEqual(result.assets, []); assert.deepEqual(result.relativePaths, {});
  assert.equal(result.unsupported + result.invalid + result.limited, 0);
  assert.equal(folderImportNotice(result), 'No sources imported from folder.');
});
