import { PDFArray, PDFBool, PDFDict, PDFDocument, PDFName, PDFNumber } from 'pdf-lib';
import { PdfAssemblyError } from './error';

export interface PdfGeometry {
  crop: { x: number; y: number; width: number; height: number };
  rotation: number;
  widthPt: number;
  heightPt: number;
}

function refuse(name: string, reason: string): never {
  throw new PdfAssemblyError('pdf_unsupported', `${name}: ${reason} Export a static PDF from the source application and import that file.`);
}

/** Parse static pages without rewriting the immutable original PDF bytes. */
export async function openPdf(bytes: Uint8Array, name: string): Promise<PDFDocument> {
  try {
    const document = await PDFDocument.load(bytes, { updateMetadata: false, throwOnInvalidObject: true });
    if (!document.getPageCount() || document.getPageCount() > 1000) refuse(name, 'The PDF must contain 1–1000 pages.');
    for (const key of ['AcroForm', 'OCProperties', 'OutputIntents', 'AA', 'OpenAction', 'StructTreeRoot', 'NeedsRendering']) {
      if (document.catalog.has(PDFName.of(key))) refuse(name, `Unsupported document state /${key} cannot be preserved in a page Form.`);
    }
    const names = document.catalog.lookupMaybe(PDFName.of('Names'), PDFDict);
    if (names?.has(PDFName.of('JavaScript'))) refuse(name, 'Document JavaScript cannot be preserved.');
    for (let index = 0; index < document.getPageCount(); index++) geometry(document, index, name);
    return document;
  } catch (error) {
    if (error instanceof PdfAssemblyError) throw error;
    const encrypted = error instanceof Error && error.message.toLowerCase().includes('encrypted');
    throw new PdfAssemblyError('pdf_invalid', `${name}: ${encrypted ? 'Encrypted PDF is unsupported.' : 'PDF cannot be read safely.'} Export an unencrypted static PDF from the source application.`);
  }
}

/** CropBox∩MediaBox is the complete visible paper, including all whitespace. */
export function geometry(document: PDFDocument, index: number, name: string): PdfGeometry {
  const context = `${name}, page ${index + 1}`;
  try {
    const page = document.getPage(index);
    const annotations = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray);
    if (annotations?.size()) refuse(context, 'Annotations are unsupported: their visible appearances would otherwise be lost.');
    for (const key of ['AA', 'Trans', 'Dur', 'PresSteps', 'VP', 'SeparationInfo']) {
      if (page.node.has(PDFName.of(key))) refuse(context, `Unsupported page state /${key}.`);
    }
    const unit = page.node.lookupMaybe(PDFName.of('UserUnit'), PDFNumber);
    if (unit && unit.asNumber() !== 1) refuse(context, 'UserUnit other than 1 has unproven physical scaling.');
    const group = page.node.lookupMaybe(PDFName.of('Group'), PDFDict);
    if (group) {
      const isolated = group.lookupMaybe(PDFName.of('I'), PDFBool)?.asBoolean();
      const knockout = group.lookupMaybe(PDFName.of('K'), PDFBool)?.asBoolean();
      if (String(group.get(PDFName.of('S'))) !== '/Transparency'
          || String(group.get(PDFName.of('CS'))) !== '/DeviceRGB'
          || isolated !== true || knockout === true
          || (group.has(PDFName.of('Type')) && String(group.get(PDFName.of('Type'))) !== '/Group')
          || group.keys().some((key) => !['/S', '/CS', '/I', '/K', '/Type'].includes(String(key)))) {
        refuse(context, 'Only an isolated RGB transparency Group without knockout is supported; this page Group has unproven appearance.');
      }
    }
    const media = page.getMediaBox(), box = page.getCropBox();
    if (![media.x, media.y, media.width, media.height, box.x, box.y, box.width, box.height].every(Number.isFinite)
        || media.width <= 0 || media.height <= 0 || box.width <= 0 || box.height <= 0) refuse(context, 'Invalid page boxes.');
    const x = Math.max(media.x, box.x), y = Math.max(media.y, box.y);
    const width = Math.min(media.x + media.width, box.x + box.width) - x;
    const height = Math.min(media.y + media.height, box.y + box.height) - y;
    const rotation = ((page.getRotation().angle % 360) + 360) % 360;
    if (width <= 0 || height <= 0 || ![0, 90, 180, 270].includes(rotation)) refuse(context, 'Invalid visible page box or intrinsic rotation.');
    return { crop: { x, y, width, height }, rotation,
      widthPt: rotation % 180 ? height : width, heightPt: rotation % 180 ? width : height };
  } catch (error) {
    if (error instanceof PdfAssemblyError) throw error;
    refuse(context, 'Malformed or unsupported page appearance state.');
  }
}
