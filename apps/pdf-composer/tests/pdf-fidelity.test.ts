import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { deflateSync } from 'node:zlib';
import fontkit from '@pdf-lib/fontkit';
import { decodePDFRawStream, degrees, PDFArray, PDFDict, PDFDocument, PDFName, PDFNumber, PDFRawStream, rgb } from 'pdf-lib';
import { fromBase64, sha256, toBase64 } from '../src/core/bytes';
import { createDocument, mergePanels, placeSource, PT_PER_MM } from '../src/core/document';
import { composePdf, inspectSource } from '../src/pdf';

const labelFont = await readFile(new URL('../assets/NotoSans-Regular.ttf', import.meta.url));
async function fixture(rotation = 0, group?: { isolated: boolean; knockout: boolean }): Promise<Uint8Array> {
  const pdf = await PDFDocument.create(); pdf.registerFontkit(fontkit);
  const font = await pdf.embedFont(labelFont, { subset: true }), page = pdf.addPage([240, 180]);
  page.drawText('η ω cm⁻³ −1', { x: 60, y: 100, size: 7, font });
  page.drawLine({ start: { x: 55, y: 65 }, end: { x: 180, y: 120 }, thickness: 0.25 });
  page.drawRectangle({ x: 70, y: 70, width: 40, height: 30, color: rgb(0, 0, 1), opacity: 0.4 });
  page.setMediaBox(20, 30, 200, 140); page.setCropBox(40, 50, 160, 100); page.setRotation(degrees(rotation));
  if (group) page.node.set(PDFName.of('Group'), pdf.context.obj({ S: 'Transparency', CS: 'DeviceRGB', I: group.isolated, K: group.knockout }));
  return pdf.save();
}
async function imported(bytes: Uint8Array, name = 'scientific.pdf') {
  return inspectSource({ name, bytesBase64: toBase64(bytes) });
}
async function sourceDocument(bytes: Uint8Array) {
  const asset = await imported(bytes);
  let doc = createDocument(2, 2); doc = mergePanels(doc, doc.panels.map((p) => p.id));
  return placeSource(doc, doc.panels[0].id, asset, 0);
}
function forms(pdf: PDFDocument): PDFRawStream[] {
  const objects = pdf.getPage(0).node.Resources()?.lookup(PDFName.of('XObject'), PDFDict);
  return objects ? objects.values().map((ref) => pdf.context.lookup(ref)).filter((value): value is PDFRawStream => value instanceof PDFRawStream && String(value.dict.get(PDFName.of('Subtype'))) === '/Form') : [];
}
function arrayNumbers(array: PDFArray): number[] { return array.asArray().map((value) => (value as PDFNumber).asNumber()); }
async function embeddedFontHashes(pdf: PDFDocument): Promise<string[]> {
  const hashes: Promise<string>[] = [];
  for (const [, value] of pdf.context.enumerateIndirectObjects()) {
    if (value instanceof PDFDict && String(value.get(PDFName.of('Type'))) === '/FontDescriptor') {
      for (const key of ['FontFile', 'FontFile2', 'FontFile3']) {
        const ref = value.get(PDFName.of(key));
        if (ref) { const stream = pdf.context.lookup(ref); if (stream instanceof PDFRawStream) hashes.push(sha256(stream.getContents())); }
      }
    }
  }
  return Promise.all(hashes);
}

for (const rotation of [0, 90, 180, 270]) {
  test(`whole visible page at intrinsic ${rotation} degrees preserves source content and font bytes`, async () => {
    const bytes = await fixture(rotation), before = await sha256(bytes), asset = await imported(bytes);
    assert.equal(asset.pages[0].widthPt, rotation % 180 ? 100 : 160);
    assert.equal(asset.pages[0].heightPt, rotation % 180 ? 160 : 100);
    const document = await sourceDocument(bytes), frozen = structuredClone(document);
    const result = await composePdf(document, labelFont), output = await PDFDocument.load(result.bytes);
    assert.deepEqual(document, frozen); assert.equal(await sha256(bytes), before);
    assert.equal(output.getPageCount(), 1);
    assert.ok(Math.abs(output.getPage(0).getWidth() - 120 * PT_PER_MM) < 1e-8);
    const [form] = forms(output); assert.ok(form);
    assert.deepEqual(arrayNumbers(form.dict.lookup(PDFName.of('BBox'), PDFArray)), [40, 50, 200, 150]);
    assert.deepEqual(arrayNumbers(form.dict.lookup(PDFName.of('Matrix'), PDFArray)), [1, 0, 0, 1, -40, -50]);
    const content = new TextDecoder().decode(decodePDFRawStream(form).decode());
    assert.match(content, /0\.25 w/); assert.match(content, /BT/); assert.match(content, /gs/);
    const original = await PDFDocument.load(bytes), oldFonts = await embeddedFontHashes(original), newFonts = await embeddedFontHashes(output);
    assert.ok(oldFonts.length > 0); assert.ok(oldFonts.every((hash) => newFonts.includes(hash)));
    assert.equal(result.warnings.length, 0);
  });
}

test('supported isolated RGB page Group is retained on the Form object', async () => {
  const doc = await sourceDocument(await fixture(0, { isolated: true, knockout: false }));
  const output = await PDFDocument.load((await composePdf(doc, labelFont)).bytes);
  const group = forms(output)[0].dict.lookup(PDFName.of('Group'), PDFDict);
  assert.equal(String(group.get(PDFName.of('S'))), '/Transparency');
  assert.equal(String(group.get(PDFName.of('I'))), 'true'); assert.equal(String(group.get(PDFName.of('K'))), 'false');
});

for (const state of [{ isolated: false, knockout: false }, { isolated: true, knockout: true }]) {
  test(`unproven page Group ${JSON.stringify(state)} explicitly refuses`, async () => {
    await assert.rejects(imported(await fixture(0, state)), /scientific.pdf, page 1:.*Group/);
  });
}

test('annotations including actual appearances refuse; empty annotation arrays remain valid', async () => {
  const pdf = await PDFDocument.load(await fixture()); const page = pdf.getPage(0);
  page.node.set(PDFName.of('Annots'), pdf.context.obj([])); await imported(await pdf.save());
  const appearance = pdf.context.register(pdf.context.flateStream('1 0 0 rg 0 0 10 10 re f', { Type: 'XObject', Subtype: 'Form', BBox: [0, 0, 10, 10] }));
  page.node.set(PDFName.of('Annots'), pdf.context.obj([{ Type: 'Annot', Subtype: 'Stamp', Rect: [0, 0, 10, 10], AP: { N: appearance } }]));
  await assert.rejects(imported(await pdf.save()), /Annotations.*appearances/);
});

for (const key of ['AcroForm', 'OCProperties', 'OutputIntents', 'OpenAction', 'StructTreeRoot']) {
  test(`unsupported document /${key} refuses without stripping state`, async () => {
    const pdf = await PDFDocument.load(await fixture()); pdf.catalog.set(PDFName.of(key), pdf.context.obj({}));
    await assert.rejects(imported(await pdf.save()), new RegExp(key));
  });
}

test('nonstandard UserUnit and invalid intrinsic rotation refuse', async () => {
  const pdf = await PDFDocument.load(await fixture()); pdf.getPage(0).node.set(PDFName.of('UserUnit'), PDFNumber.of(2));
  await assert.rejects(imported(await pdf.save()), /UserUnit/);
  pdf.getPage(0).node.delete(PDFName.of('UserUnit')); pdf.getPage(0).node.set(PDFName.of('Rotate'), PDFNumber.of(45));
  await assert.rejects(imported(await pdf.save()), /intrinsic rotation/);
});

test('blank source pages retain their complete physical whitespace', async () => {
  const source = await PDFDocument.create(); source.addPage([40, 30]);
  const doc = createDocument(1, 1), asset = await imported(await source.save());
  const output = await PDFDocument.load((await composePdf(placeSource(doc, doc.panels[0].id, asset, 0), labelFont)).bytes);
  assert.equal(forms(output).length, 0); assert.ok(output.getPage(0).getWidth() > 40);
});

test('export rehashes bytes and checks real geometry rather than trusting saved declarations', async () => {
  const doc = await sourceDocument(await fixture()); doc.assets[0].sha256 = '0'.repeat(64);
  await assert.rejects(composePdf(doc, labelFont), /bytes changed/);
  doc.assets[0].sha256 = await sha256(fromBase64(doc.assets[0].bytesBase64)); doc.assets[0].pages[0].widthPt -= 1;
  await assert.rejects(composePdf(doc, labelFont), /stored geometry/);
});

test('explicit uniform scaling is retained, warned and deterministic; export does not mutate editor state', async () => {
  const asset = await imported(await fixture()); const initial = createDocument(1, 1);
  const doc = placeSource(initial, initial.panels[0].id, asset, 0, 0.5);
  const before = structuredClone(doc), first = await composePdf(doc, labelFont), second = await composePdf(doc, labelFont);
  assert.deepEqual(doc, before); assert.deepEqual(first.bytes, second.bytes);
  assert.match(first.warnings[0], /50.00%/);
});

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0); }
  return (crc ^ 0xffffffff) >>> 0;
}
function png(dpi?: number, bitDepth = 8): Uint8Array {
  const chunk = (type: string, data: Uint8Array) => {
    const body = Buffer.concat([Buffer.from(type), data]), length = Buffer.alloc(4), crc = Buffer.alloc(4);
    length.writeUInt32BE(data.length); crc.writeUInt32BE(crc32(body)); return Buffer.concat([length, body, crc]);
  };
  const header = Buffer.alloc(13); header.writeUInt32BE(2, 0); header.writeUInt32BE(3, 4); header[8] = bitDepth; header[9] = 2;
  const pieces = [Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header)];
  if (dpi) { const physical = Buffer.alloc(9); physical.writeUInt32BE(Math.round(dpi / .0254)); physical.writeUInt32BE(Math.round(dpi / .0254), 4); physical[8] = 1; pieces.push(chunk('pHYs', physical)); }
  pieces.push(chunk('IDAT', deflateSync(Buffer.from([0, 255, 0, 0, 0, 255, 0, 0, 255, 0, 0, 0, 255, 0, 255, 255, 0, 0, 0, 255, 255]))), chunk('IEND', new Uint8Array()));
  return Buffer.concat(pieces);
}
function tiff(depth = 8, next = 0, orientation = 1): Uint8Array {
  const bytes = Buffer.alloc(158); bytes.write('II'); bytes.writeUInt16LE(42, 2); bytes.writeUInt32LE(8, 4); bytes.writeUInt16LE(10, 8);
  const fields = [[256, 4, 1, 2], [257, 4, 1, 3], [258, 3, 3, 134], [259, 3, 1, 1], [262, 3, 1, 2], [273, 4, 1, 140], [274, 3, 1, orientation], [277, 3, 1, 3], [278, 4, 1, 3], [279, 4, 1, 18]];
  fields.forEach(([tag, type, count, value], index) => { const offset = 10 + index * 12; bytes.writeUInt16LE(tag, offset); bytes.writeUInt16LE(type, offset + 2); bytes.writeUInt32LE(count, offset + 4); bytes.writeUInt32LE(value, offset + 8); });
  bytes.writeUInt32LE(next, 130); [134, 136, 138].forEach((offset) => bytes.writeUInt16LE(depth, offset)); bytes.fill(255, 140);
  return bytes;
}

test('PNG intrinsic DPI outranks contradictory native metadata; absent DPI is explicitly assumed', async () => {
  const intrinsic = await inspectSource({ name: 'physical.png', bytesBase64: toBase64(png(100)), dpi: 300 });
  assert.ok(Math.abs(intrinsic.pages[0].dpi! - 100) < .01); assert.equal(intrinsic.pages[0].dpiAssumed, false);
  const asset = await imported(png(), 'unknown.png'); assert.equal(asset.pages[0].dpi, 300); assert.equal(asset.pages[0].dpiAssumed, true);
  const doc = createDocument(1, 1), result = await composePdf(placeSource(doc, doc.panels[0].id, asset, 0), labelFont);
  assert.match(result.warnings[0], /300 dpi assumed/);
  await assert.rejects(inspectSource({ name: 'wrong.png', bytesBase64: toBase64(png()), pixelWidth: 3 }), /dimensions disagree/);
  await assert.rejects(imported(png(undefined, 16), '16bit.png'), /bit depth/);
});

test('single-page TIFF keeps original bytes and validates its native PNG byte seal/dimensions', async () => {
  const bytes = tiff(), pngBytes = png();
  const asset = await inspectSource({ name: 'figure.tiff', bytesBase64: toBase64(bytes), normalizedPngBase64: toBase64(pngBytes) });
  assert.equal(asset.bytesBase64, toBase64(bytes)); assert.equal(asset.normalizedPngSha256, await sha256(pngBytes));
  const initial = createDocument(1, 1), doc = placeSource(initial, initial.panels[0].id, asset, 0);
  await assert.rejects(composePdf(doc, labelFont), /native TIFF pixel verification is required/);
  let verified = false;
  await composePdf(doc, labelFont, async (original, normalized) => {
    assert.equal(original, asset.bytesBase64); assert.equal(normalized, asset.normalizedPngBase64); verified = true;
  });
  assert.equal(verified, true);
  await assert.rejects(composePdf(doc, labelFont, async () => { throw new Error('Native pixel mismatch'); }), /Native pixel mismatch/);
  doc.assets[0].normalizedPngSha256 = '0'.repeat(64);
  await assert.rejects(composePdf(doc, labelFont), /decoding bytes/);
  for (const unsafe of [tiff(16), tiff(8, 130), tiff(8, 0, 6)]) {
    await assert.rejects(inspectSource({ name: 'unsafe.tiff', bytesBase64: toBase64(unsafe), normalizedPngBase64: toBase64(pngBytes) }), /TIFF/);
  }
});

test('unknown and damaged source formats fail without product-side rendering fallbacks', async () => {
  await assert.rejects(imported(new TextEncoder().encode('<svg/>'), 'drawing.svg'), /Unsupported source type/);
  await assert.rejects(imported(new TextEncoder().encode('%PDF-1.7\nmissing'), 'damaged.pdf'), /cannot be read safely/);
});
