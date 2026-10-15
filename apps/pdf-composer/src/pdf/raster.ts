import { PDFDocument } from 'pdf-lib';
import { PdfAssemblyError } from './error';
import type { SourceKind } from '../core/types';

interface RasterInfo { width: number; height: number; dpi?: number }
interface TiffInfo { width?: number; height?: number; orientation: number; dpi?: number }
function invalid(reason: string): never { throw new PdfAssemblyError('image_unsupported', reason); }
function resolution(x: number, y: number): number | undefined {
  if (x > 0 && y > 0 && Math.abs(x - y) > Math.max(x, y) * 0.001) invalid('Non-square image resolution is unsupported; export square-pixel PNG.');
  return Number.isFinite(x) && x >= 1 && x <= 9600 && y >= 1 && y <= 9600 ? x : undefined;
}
function checkPixels(width: number, height: number): void {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1
      || width * height > 100_000_000 || width > 100000 || height > 100000) invalid('Image exceeds the supported 100 megapixel size or has invalid dimensions.');
}
export function sourceKind(bytes: Uint8Array): SourceKind {
  if (bytes[0] === 0x89 && String.fromCharCode(...bytes.slice(1, 4)) === 'PNG') return 'png';
  if (bytes[0] === 255 && bytes[1] === 216) return 'jpeg';
  if ((bytes[0] === 73 && bytes[1] === 73) || (bytes[0] === 77 && bytes[1] === 77)) return 'tiff';
  if (new TextDecoder('latin1').decode(bytes.slice(0, 1024)).includes('%PDF-')) return 'pdf';
  return invalid('Unsupported source type. Import PDF, PNG, JPEG or a single-page TIFF.');
}

function tiffFields(bytes: Uint8Array, image = true): TiffInfo {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), little = bytes[0] === 73;
  if (view.getUint16(2, little) !== 42) invalid('BigTIFF is unsupported. Export a standard single-page TIFF or PNG.');
  const offset = view.getUint32(4, little), count = view.getUint16(offset, little);
  if (count > 4096 || offset + 2 + count * 12 + 4 > bytes.length) invalid('Invalid TIFF directory.');
  if (image && view.getUint32(offset + 2 + count * 12, little)) invalid('Multi-page TIFF is unsupported; import individual pages.');
  const result: TiffInfo = { orientation: 1 };
  let xResolution = 0, yResolution = 0, unit = 2;
  for (let index = 0; index < count; index++) {
    const entry = offset + 2 + index * 12, tag = view.getUint16(entry, little);
    const type = view.getUint16(entry + 2, little), size = view.getUint32(entry + 4, little);
    if (image && tag === 258 && type === 3) {
      const start = size > 2 ? view.getUint32(entry + 8, little) : entry + 8;
      for (let sample = 0; sample < size; sample++) if (view.getUint16(start + sample * 2, little) > 8) invalid('TIFF above 8 bits per sample is unsupported; retain the original and export an 8-bit display image.');
    }
    if (![256, 257, 274, 282, 283, 296, 262].includes(tag)) continue;
    if (tag === 282 || tag === 283) {
      if (type !== 5 || size !== 1) invalid('Invalid image resolution encoding.');
      const start = view.getUint32(entry + 8, little), value = view.getUint32(start, little) / view.getUint32(start + 4, little);
      if (tag === 282) xResolution = value; else yResolution = value;
      continue;
    }
    if (size !== 1 || ![3, 4].includes(type)) invalid('Unsupported image dimension/orientation encoding.');
    const value = type === 3 ? view.getUint16(entry + 8, little) : view.getUint32(entry + 8, little);
    if (tag === 256) result.width = value;
    if (tag === 257) result.height = value;
    if (tag === 274) result.orientation = value;
    if (tag === 296) unit = value;
    if (image && tag === 262 && ![0, 1, 2].includes(value)) invalid('Only grayscale/RGB TIFF is supported; export a color-normalized PNG.');
  }
  if (unit === 2 || unit === 3) result.dpi = resolution(xResolution * (unit === 3 ? 2.54 : 1), yResolution * (unit === 3 ? 2.54 : 1));
  return result;
}

function jpegInfo(bytes: Uint8Array): Partial<RasterInfo> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), result: Partial<RasterInfo> = {};
  let offset = 2;
  while (offset + 4 <= bytes.length && bytes[offset] === 255) {
    const marker = bytes[offset + 1];
    if (marker === 0xda || marker === 0xd9) break;
    const length = view.getUint16(offset + 2);
    if (length < 2 || offset + 2 + length > bytes.length) invalid('Invalid JPEG segment.');
    if (marker === 0xe0 && String.fromCharCode(...bytes.slice(offset + 4, offset + 9)) === 'JFIF\0') {
      const unit = bytes[offset + 11], x = view.getUint16(offset + 12), y = view.getUint16(offset + 14);
      if (unit === 1 || unit === 2) result.dpi = resolution(x * (unit === 2 ? 2.54 : 1), y * (unit === 2 ? 2.54 : 1));
      else if (x && y && x !== y) invalid('JPEG has non-square pixel aspect ratio; export square-pixel PNG.');
    }
    if (marker === 0xe2 && String.fromCharCode(...bytes.slice(offset + 4, offset + 16)) === 'ICC_PROFILE\0') {
      invalid('JPEG ICC color profiles are unsupported. Export a standard sRGB display PNG without an embedded ICC profile.');
    }
    if (marker === 0xe1 && String.fromCharCode(...bytes.slice(offset + 4, offset + 10)) === 'Exif\0\0') {
      const exif = tiffFields(bytes.slice(offset + 10, offset + 2 + length), false);
      if (exif.orientation !== 1) invalid('Rotated JPEG EXIF orientation is unsupported. Export an orientation-normalized PNG first.');
      if (exif.dpi !== undefined) result.dpi = exif.dpi;
    }
    if ([0xc0, 0xc1, 0xc2].includes(marker)) {
      if (![1, 3].includes(bytes[offset + 9])) invalid('Only grayscale/RGB JPEG is supported; export a color-normalized PNG first.');
      result.width = view.getUint16(offset + 7); result.height = view.getUint16(offset + 5);
      checkPixels(result.width, result.height);
    }
    offset += length + 2;
  }
  return result;
}

function pngInfo(bytes: Uint8Array): RasterInfo {
  if (bytes.length < 33 || bytes[24] > 8) invalid('PNG must have a supported bit depth of at most 8; preserve higher-depth originals separately.');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const result: RasterInfo = { width: view.getUint32(16), height: view.getUint32(20) };
  checkPixels(result.width, result.height);
  let srgb = false, corrected = false;
  for (let offset = 8; offset + 12 <= bytes.length;) {
    const length = view.getUint32(offset), type = String.fromCharCode(...bytes.slice(offset + 4, offset + 8));
    if (offset + 12 + length > bytes.length) invalid('Invalid PNG chunk.');
    if (type === 'iCCP') invalid('PNG ICC color profiles are unsupported. Export a standard sRGB display PNG without an embedded ICC profile.');
    if (type === 'sRGB') {
      if (length !== 1 || bytes[offset + 8] > 3) invalid('Invalid PNG sRGB declaration.');
      srgb = true;
    }
    if (type === 'gAMA') {
      corrected = true;
      if (length !== 4 || view.getUint32(offset + 8) !== 45455) invalid('Nonstandard PNG gamma is unsupported. Export a standard sRGB display PNG.');
    }
    if (type === 'cHRM') {
      corrected = true;
      const standard = [31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000];
      if (length !== 32 || standard.some((value, index) => view.getUint32(offset + 8 + index * 4) !== value)) invalid('Nonstandard PNG chromaticities are unsupported. Export a standard sRGB display PNG.');
    }
    if (['acTL', 'eXIf'].includes(type)) invalid('Animated or EXIF-oriented PNG is unsupported. Export a static orientation-normalized PNG.');
    if (type === 'pHYs' && length === 9 && bytes[offset + 16] === 1) {
      result.dpi = resolution(view.getUint32(offset + 8) * 0.0254, view.getUint32(offset + 12) * 0.0254);
    }
    offset += length + 12;
  }
  if (corrected && !srgb) invalid('PNG color-correction metadata requires an explicit standard sRGB declaration.');
  return result;
}

export async function rasterDimensions(kind: SourceKind, bytes: Uint8Array, normalized?: Uint8Array): Promise<RasterInfo> {
  try {
    if (kind === 'pdf') invalid('Expected raster image.');
    const fields = kind === 'tiff' ? tiffFields(bytes) : undefined;
    const info = kind === 'jpeg' ? jpegInfo(bytes) : pngInfo(kind === 'tiff' ? normalized ?? new Uint8Array() : bytes);
    const document = await PDFDocument.create();
    const image = kind === 'jpeg' ? await document.embedJpg(bytes) : await document.embedPng(kind === 'tiff' ? normalized! : bytes);
    checkPixels(image.width, image.height);
    if (fields && (fields.orientation !== 1 || fields.width !== image.width || fields.height !== image.height)) {
      invalid('TIFF orientation/dimensions disagree with its lossless PNG decoding; import an orientation-normalized single-page image.');
    }
    return { width: image.width, height: image.height, dpi: kind === 'tiff' ? fields?.dpi : info.dpi };
  } catch (error) {
    if (error instanceof PdfAssemblyError) throw error;
    invalid('Damaged or unsupported image bytes. Export a standard RGB PNG/JPEG or single-page TIFF.');
  }
}
