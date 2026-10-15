import { fromBase64, sha256 } from '../core/bytes';
import { MAX_SOURCE_BYTES } from '../core/document';
import type { ImportedFile, SourceAsset } from '../core/types';
import { PdfAssemblyError } from './error';
import { geometry, openPdf } from './preflight';
import { rasterDimensions, sourceKind } from './raster';

/** Capture original bytes without changing any PDF text, content or resources. */
export async function inspectSource(file: ImportedFile): Promise<SourceAsset> {
  const name = file.name.split(/[\\/]/).at(-1) ?? '';
  if (!name || name.length > 255 || file.bytesBase64.length > MAX_SOURCE_BYTES * 4 / 3 + 4) {
    throw new PdfAssemblyError('source_invalid', 'Source name is invalid or the file exceeds 64 MiB.');
  }
  const bytes = fromBase64(file.bytesBase64);
  if (!bytes.length || bytes.length > MAX_SOURCE_BYTES) throw new PdfAssemblyError('source_invalid', `${name}: source is empty or exceeds 64 MiB.`);
  const kind = sourceKind(bytes), digest = await sha256(bytes);
  const asset: SourceAsset = { id: crypto.randomUUID(), name, kind, sha256: digest,
    bytesBase64: file.bytesBase64, pages: [] };
  if (kind === 'pdf') {
    const pdf = await openPdf(bytes, name);
    asset.pages = pdf.getPages().map((_, index) => {
      const page = geometry(pdf, index, name);
      return { index, widthPt: page.widthPt, heightPt: page.heightPt };
    });
  } else {
    let normalized: Uint8Array | undefined;
    if (kind === 'tiff') {
      if (!file.normalizedPngBase64 || file.normalizedPngBase64.length > MAX_SOURCE_BYTES * 4 / 3 + 4) {
        throw new PdfAssemblyError('tiff_decode_required', `${name}: import TIFF through the native app to obtain its lossless PNG decoding.`);
      }
      normalized = fromBase64(file.normalizedPngBase64);
      if (sourceKind(normalized) !== 'png' || normalized.length > MAX_SOURCE_BYTES) {
        throw new PdfAssemblyError('tiff_decode_invalid', `${name}: invalid or oversized native TIFF PNG decoding.`);
      }
      asset.normalizedPngBase64 = file.normalizedPngBase64;
      asset.normalizedPngSha256 = await sha256(normalized);
    }
    const pixels = await rasterDimensions(kind, bytes, normalized);
    if ((file.pixelWidth !== undefined && file.pixelWidth !== pixels.width)
        || (file.pixelHeight !== undefined && file.pixelHeight !== pixels.height)) {
      throw new PdfAssemblyError('image_dimensions_changed', `${name}: original image dimensions disagree with native import metadata.`);
    }
    const known = file.dpi !== undefined && Number.isFinite(file.dpi) && file.dpi >= 1 && file.dpi <= 9600;
    const dpi = pixels.dpi ?? (known ? file.dpi! : 300);
    asset.pages = [{ index: 0, widthPt: pixels.width * 72 / dpi, heightPt: pixels.height * 72 / dpi,
      pixelWidth: pixels.width, pixelHeight: pixels.height, dpi, dpiAssumed: pixels.dpi === undefined && !known }];
  }
  return asset;
}
