import fontkit from '@pdf-lib/fontkit';
import { PDFDocument, rgb } from 'pdf-lib';
import { fromBase64, sha256 } from '../core/bytes';
import { orderedPanels, panelLetter, panelSizePt, PT_PER_MM, validateDocument } from '../core/document';
import type { AssemblyDocument, ExportResult, SourceAsset } from '../core/types';
import { PdfAssemblyError } from './error';
import { drawSourcePage } from './forms';
import { geometry, openPdf } from './preflight';
import { rasterDimensions, sourceKind } from './raster';

export { inspectSource } from './assets';
export { PdfAssemblyError } from './error';

function agree(actual: number, declared: number): boolean { return Math.abs(actual - declared) < 0.00001; }

async function verifyRaster(asset: SourceAsset): Promise<void> {
  const pixels = await rasterDimensions(asset.kind, fromBase64(asset.bytesBase64),
    asset.normalizedPngBase64 ? fromBase64(asset.normalizedPngBase64) : undefined);
  const page = asset.pages[0], dpi = page.dpi;
  if (asset.pages.length !== 1 || !dpi || pixels.width !== page.pixelWidth || pixels.height !== page.pixelHeight
      || (pixels.dpi !== undefined && (!agree(dpi, pixels.dpi) || page.dpiAssumed === true))
      || !agree(page.widthPt, pixels.width * 72 / dpi) || !agree(page.heightPt, pixels.height * 72 / dpi)) {
    throw new PdfAssemblyError('source_geometry_changed', `${asset.name}: image dimensions or physical geometry disagree with its original bytes.`);
  }
}

/** Compose original pages, at their explicit uniform scale, without source editing. */
export async function composePdf(document: AssemblyDocument, labelFont: Uint8Array,
  verifyTiff?: (bytesBase64: string, normalizedPngBase64: string) => Promise<void>): Promise<ExportResult> {
  validateDocument(document);
  const snapshot = structuredClone(document); // Freeze this export across asynchronous parsing/hashing.
  for (const asset of snapshot.assets) {
    if (await sha256(fromBase64(asset.bytesBase64)) !== asset.sha256
        || (asset.kind === 'tiff' && await sha256(fromBase64(asset.normalizedPngBase64!)) !== asset.normalizedPngSha256)) {
      throw new PdfAssemblyError('source_bytes_changed', `${asset.name}: original or TIFF decoding bytes changed or are corrupt.`);
    }
  }
  const sources = new Map<string, PDFDocument>();
  for (const asset of snapshot.assets) {
    if (sourceKind(fromBase64(asset.bytesBase64)) !== asset.kind) {
      throw new PdfAssemblyError('source_kind_changed', `${asset.name}: source type disagrees with the original bytes.`);
    }
    if (asset.kind === 'pdf') {
      const pdf = await openPdf(fromBase64(asset.bytesBase64), asset.name);
      if (pdf.getPageCount() !== asset.pages.length) throw new PdfAssemblyError('source_geometry_changed', `${asset.name}: page count changed.`);
      for (const original of asset.pages) {
        const actual = geometry(pdf, original.index, asset.name);
        if (!agree(actual.widthPt, original.widthPt) || !agree(actual.heightPt, original.heightPt)) {
          throw new PdfAssemblyError('source_geometry_changed', `${asset.name}, page ${original.index + 1}: stored geometry does not match the original PDF.`);
        }
      }
      sources.set(asset.id, pdf);
    } else {
      if (asset.kind === 'tiff') {
        if (!verifyTiff) throw new PdfAssemblyError('tiff_verification_required', `${asset.name}: native TIFF pixel verification is required before PDF export.`);
        await verifyTiff(asset.bytesBase64, asset.normalizedPngBase64!);
      }
      await verifyRaster(asset);
    }
  }
  const output = await PDFDocument.create();
  output.setTitle(snapshot.title); output.setCreator('Figure Assembly'); output.setProducer('Figure Assembly');
  output.setCreationDate(new Date(0)); output.setModificationDate(new Date(0));
  const width = snapshot.grid.columns * 60 * PT_PER_MM, height = snapshot.grid.rows * 55 * PT_PER_MM;
  const page = output.addPage([width, height]), warnings: string[] = [];
  const panels = orderedPanels(snapshot).filter((panel) => panel.assetId !== null);
  for (const panel of panels) {
    const asset = snapshot.assets.find((item) => item.id === panel.assetId)!;
    const original = asset.pages[panel.pageIndex], size = panelSizePt(snapshot, panel);
    const drawWidth = original.widthPt * panel.scale, drawHeight = original.heightPt * panel.scale;
    const x = panel.column * 60 * PT_PER_MM + (size.width - drawWidth) / 2;
    const y = height - panel.row * 55 * PT_PER_MM - size.height + (size.height - drawHeight) / 2;
    page.drawRectangle({ x, y, width: drawWidth, height: drawHeight, color: rgb(1, 1, 1) });
    if (asset.kind === 'pdf') {
      const source = sources.get(asset.id)!;
      await drawSourcePage(page, output, source, panel.pageIndex, geometry(source, panel.pageIndex, asset.name), x, y, panel.scale);
    } else {
      const bytes = fromBase64(asset.kind === 'tiff' ? asset.normalizedPngBase64! : asset.bytesBase64);
      const image = asset.kind === 'jpeg' ? await output.embedJpg(bytes) : await output.embedPng(bytes);
      page.drawImage(image, { x, y, width: drawWidth, height: drawHeight });
      warnings.push(`${asset.name}: effective raster resolution ${(original.dpi! / panel.scale).toFixed(1)} dpi${original.dpiAssumed ? '; original DPI unknown, 300 dpi assumed' : ''}.`);
    }
    if (panel.scale !== 1) warnings.push(`${asset.name}, page ${panel.pageIndex + 1}: explicit whole-page scale ${(panel.scale * 100).toFixed(2)}%; text and marks scale together.`);
  }
  if (snapshot.labels.enabled && panels.length) {
    output.registerFontkit(fontkit);
    const font = await output.embedFont(labelFont, { subset: true });
    const size = snapshot.labels.fontSizePt, inset = snapshot.labels.insetMm * PT_PER_MM;
    const ascent = font.heightAtSize(size, { descender: false });
    for (const [index, panel] of panels.entries()) {
      const text = panelLetter(index), bounds = panelSizePt(snapshot, panel);
      if (font.widthOfTextAtSize(text, size) + inset > bounds.width || ascent + inset > bounds.height
          || [...text].some((character) => !font.getCharacterSet().includes(character.codePointAt(0)!))) {
        throw new PdfAssemblyError('label_does_not_fit', 'Panel letter does not fit its container or the bundled font cannot represent it.');
      }
      page.drawText(text, { font, size, color: rgb(0, 0, 0),
        x: panel.column * 60 * PT_PER_MM + inset, y: height - panel.row * 55 * PT_PER_MM - inset - ascent });
    }
  }
  return { bytes: await output.save(), warnings };
}
