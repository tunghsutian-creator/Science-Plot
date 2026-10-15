import { PDFArray, PDFDict, PDFDocument, PDFName, PDFObject, PDFRef, PDFStream } from 'pdf-lib';
import { PdfAssemblyError } from './error';

const MAX_NODES = 100_000, MAX_EDGES = 200_000, MAX_DEPTH = 128;

/** Inspect only copied page/resource graphs; never resolve a file specification. */
export function assertSelfContainedResources(document: PDFDocument, name: string): void {
  const seen = new Set<PDFObject>();
  const pending: { object: PDFObject; depth: number; page: number }[] = [];
  let edges = 0;
  function refuse(page: number, reason: string, code = 'pdf_unsupported'): never {
    throw new PdfAssemblyError(code, `${name}, page ${page + 1}: ${reason} Export a self-contained static PDF from the source application.`);
  }
  function push(object: PDFObject, depth: number, page: number): void {
    if (++edges > MAX_EDGES) refuse(page, 'The resource graph exceeds the inspection limit.', 'pdf_resource_limit');
    pending.push({ object, depth, page });
  }
  for (const [index, page] of document.getPages().entries()) {
    push(page.node, 0, index);
    const inherited = page.node.Resources();
    if (inherited) push(inherited, 1, index);
  }
  while (pending.length) {
    const { object, depth, page } = pending.pop()!;
    if (seen.has(object)) continue;
    if (depth > MAX_DEPTH || seen.size >= MAX_NODES) refuse(page, 'The resource graph exceeds the inspection limit.', 'pdf_resource_limit');
    seen.add(object);
    if (object instanceof PDFRef) {
      const resolved = document.context.lookup(object);
      if (!resolved) refuse(page, 'A resource reference is missing from the PDF.');
      push(resolved, depth, page);
    } else if (object instanceof PDFStream) {
      for (const key of ['F', 'FFilter', 'FDecodeParms']) {
        if (object.dict.has(PDFName.of(key))) refuse(page, `An external stream /${key} is unsupported; its data is not guaranteed to be inside this file.`);
      }
      push(object.dict, depth + 1, page);
    } else if (object instanceof PDFArray) {
      if (object.size() > MAX_NODES) refuse(page, 'The resource graph exceeds the inspection limit.', 'pdf_resource_limit');
      for (let index = 0; index < object.size(); index++) push(object.get(index), depth + 1, page);
    } else if (object instanceof PDFDict) {
      const type = object.lookupMaybe(PDFName.of('Type'), PDFName)?.toString();
      const subtype = object.lookupMaybe(PDFName.of('Subtype'), PDFName)?.toString();
      if (subtype === '/PS') refuse(page, 'A PostScript XObject is unsupported.');
      if ((subtype === '/Form' || type === '/XObject') && object.has(PDFName.of('Ref'))) {
        refuse(page, 'A Reference Form XObject /Ref is not a self-contained static page.');
      }
      for (const [key, value] of object.entries()) {
        // Page parents are not copied into page Forms; inherited resources are seeded above.
        if (key === PDFName.of('Parent') && (type === '/Page' || type === '/Pages')) continue;
        push(value, depth + 1, page);
      }
    }
  }
}
