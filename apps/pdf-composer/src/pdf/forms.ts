import { degrees, PDFDocument, PDFName, PDFObjectCopier, PDFStream, type PDFPage } from 'pdf-lib';
import type { PdfGeometry } from './preflight';

/** All source content remains an opaque Form with its own copied resource graph. */
export async function drawSourcePage(target: PDFPage, output: PDFDocument, source: PDFDocument,
  pageIndex: number, page: PdfGeometry, x: number, y: number, scale: number): Promise<void> {
  const original = source.getPage(pageIndex);
  if (!original.node.Contents()) return; // Blank paper is represented by the caller's full white rectangle.
  const box = page.crop;
  const embedded = await output.embedPage(original, {
    left: box.x, bottom: box.y, right: box.x + box.width, top: box.y + box.height,
  });
  await embedded.embed();
  const group = original.node.get(PDFName.of('Group'));
  if (group) {
    // Preflight admits only the measured isolated RGB, non-knockout group state.
    const graph = PDFObjectCopier.for(source.context, output.context).copy(group);
    output.context.lookup(embedded.ref, PDFStream).dict.set(PDFName.of('Group'), graph);
  }
  if (page.rotation === 90) y += box.width * scale;
  if (page.rotation === 180) { x += box.width * scale; y += box.height * scale; }
  if (page.rotation === 270) x += box.height * scale;
  target.drawPage(embedded, { x, y, xScale: scale, yScale: scale, rotate: degrees(-page.rotation) });
}
