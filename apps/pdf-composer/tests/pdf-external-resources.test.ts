import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { PDFDocument, PDFName, PDFString } from 'pdf-lib';
import { sha256, toBase64 } from '../src/core/bytes';
import { createDocument, placeSource } from '../src/core/document';
import type { SourceAsset } from '../src/core/types';
import { composePdf, inspectSource } from '../src/pdf';

const missingFile = '/definitely-not-present/figure-assembly-external-control/missing.pdf';
type Mode = 'F' | 'FFilter' | 'FDecodeParms' | 'nested-image' | 'font-file' | 'reference-form' | 'postscript';
async function externalFixture(mode: Mode): Promise<Uint8Array> {
  const pdf = await PDFDocument.create(), page = pdf.addPage([40, 30]);
  page.drawText('Static', { size: 7, x: 2, y: 20 });
  if (['F', 'FFilter', 'FDecodeParms'].includes(mode)) {
    const stream = pdf.context.stream(new Uint8Array());
    stream.dict.set(PDFName.of(mode), mode === 'F' ? PDFString.of(missingFile)
      : mode === 'FFilter' ? PDFName.of('FlateDecode') : pdf.context.obj({}));
    page.node.set(PDFName.of('Contents'), pdf.context.register(stream));
  } else {
    const external = pdf.context.stream(new Uint8Array(), {
      Type: 'XObject', Subtype: mode === 'postscript' ? 'PS' : mode === 'nested-image' ? 'Image' : 'Form',
      BBox: [0, 0, 10, 10], Width: 1, Height: 1, ColorSpace: 'DeviceRGB', BitsPerComponent: 8,
    });
    if (mode === 'reference-form') external.dict.set(PDFName.of('Ref'), pdf.context.obj({ F: PDFString.of(missingFile), Page: 0 }));
    else if (mode !== 'postscript') external.dict.set(PDFName.of('F'), PDFString.of(missingFile));
    const reference = pdf.context.register(external);
    if (mode === 'font-file') {
      page.node.Resources()!.set(PDFName.of('Font'), pdf.context.obj({ ExternalFont: {
        Type: 'Font', Subtype: 'Type1', BaseFont: 'Helvetica', FontDescriptor: { Type: 'FontDescriptor', FontFile: reference },
      } }));
    } else {
      const form = pdf.context.stream('/Nested Do', { Type: 'XObject', Subtype: 'Form', BBox: [0, 0, 10, 10], Resources: { XObject: { Nested: reference } } });
      page.node.Resources()!.set(PDFName.of('XObject'), pdf.context.obj({ Outer: pdf.context.register(form) }));
    }
  }
  return pdf.save();
}
async function declaredDocument(bytes: Uint8Array) {
  const asset: SourceAsset = { id: 'negative-source', name: 'external.pdf', kind: 'pdf', sha256: await sha256(bytes),
    bytesBase64: toBase64(bytes), pages: [{ index: 0, widthPt: 40, heightPt: 30 }] };
  const doc = createDocument(1, 1); doc.labels.enabled = false;
  return placeSource(doc, doc.panels[0].id, asset, 0);
}

for (const mode of ['F', 'FFilter', 'FDecodeParms', 'nested-image', 'font-file', 'reference-form', 'postscript'] as const) {
  test(`external resource ${mode} refuses import and direct export without file access`, async (context) => {
    const bytes = await externalFixture(mode), doc = await declaredDocument(bytes), before = structuredClone(doc);
    const reads = [
      context.mock.method(fs, 'readFileSync', () => { throw new Error('Unexpected file access'); }),
      context.mock.method(fs, 'readFile', () => { throw new Error('Unexpected file access'); }),
      context.mock.method(fs, 'openSync', () => { throw new Error('Unexpected file access'); }),
      context.mock.method(fs.promises, 'readFile', async () => { throw new Error('Unexpected file access'); }),
      context.mock.method(fs.promises, 'open', async () => { throw new Error('Unexpected file access'); }),
    ];
    const reason = mode === 'reference-form' ? /Reference Form.*self-contained/
      : mode === 'postscript' ? /PostScript XObject.*unsupported/ : /external stream.*unsupported/;
    await assert.rejects(inspectSource({ name: 'external.pdf', bytesBase64: toBase64(bytes) }), reason);
    await assert.rejects(composePdf(doc, new Uint8Array()), reason);
    assert.deepEqual(doc, before);
    for (const read of reads) assert.equal(read.mock.callCount(), 0);
  });
}

test('shared and cyclic internal resource references terminate and remain self-contained', async () => {
  const pdf = await PDFDocument.create(), page = pdf.addPage([40, 30]); page.drawText('Local', { size: 7 });
  const cycle = pdf.context.obj({}), ref = pdf.context.register(cycle);
  cycle.set(PDFName.of('Self'), ref); page.node.Resources()!.set(PDFName.of('Internal'), pdf.context.obj([ref, ref]));
  const bytes = await pdf.save(); await inspectSource({ name: 'cycle.pdf', bytesBase64: toBase64(bytes) });
  assert.ok((await composePdf(await declaredDocument(bytes), new Uint8Array())).bytes.length > 0);
});

test('resource graph inspection has a finite node/edge budget', async () => {
  const pdf = await PDFDocument.create(), page = pdf.addPage([40, 30]);
  page.node.Resources()!.set(PDFName.of('Oversized'), pdf.context.obj(Array.from({ length: 100001 }, (_, index) => index)));
  await assert.rejects(inspectSource({ name: 'too-many.pdf', bytesBase64: toBase64(await pdf.save()) }), /resource graph.*limit/);
});

test('resource graph inspection refuses excessive nesting without recursive traversal', async () => {
  const pdf = await PDFDocument.create(), page = pdf.addPage([40, 30]);
  let current = pdf.context.obj([]);
  for (let depth = 0; depth < 130; depth++) current = pdf.context.obj([current]);
  page.node.Resources()!.set(PDFName.of('Deep'), current);
  await assert.rejects(inspectSource({ name: 'too-deep.pdf', bytesBase64: toBase64(await pdf.save()) }), /resource graph.*limit/);
});

test('repeated resource edges also have a finite work budget', async () => {
  const pdf = await PDFDocument.create(), page = pdf.addPage([40, 30]);
  const arrays = Array.from({ length: 3 }, () => pdf.context.register(pdf.context.obj(Array(100000).fill(PDFName.of('Shared')))));
  page.node.Resources()!.set(PDFName.of('Repeated'), pdf.context.obj(arrays));
  await assert.rejects(inspectSource({ name: 'too-many-edges.pdf', bytesBase64: toBase64(await pdf.save()) }), /resource graph.*limit/);
});

test('catalog-only embedded attachments do not make ordinary page resources unsupported', async () => {
  const pdf = await PDFDocument.create(); pdf.addPage([40, 30]).drawText('Page', { size: 7 });
  await pdf.attach(new TextEncoder().encode('Non-appearance note'), 'notes.txt');
  const asset = await inspectSource({ name: 'with-notes.pdf', bytesBase64: toBase64(await pdf.save()) });
  assert.equal(asset.pages.length, 1);
});
