import type { AssemblyDocument, TiffVerifier } from './types';
import { validateDocument } from './document';
import { fromBase64, sha256 } from './bytes';
import { inspectSource } from '../pdf/index';

const MAX_PROJECT_CHARACTERS = 192 * 1024 * 1024;
export async function verifySourceHashes(document: AssemblyDocument): Promise<void> {
  for (const asset of document.assets) {
    if (await sha256(fromBase64(asset.bytesBase64)) !== asset.sha256) {
      throw new Error(`Original source bytes changed or are corrupt: ${asset.name}`);
    }
    if (asset.kind === 'tiff' && await sha256(fromBase64(asset.normalizedPngBase64!)) !== asset.normalizedPngSha256) {
      throw new Error(`TIFF decoding bytes changed or are corrupt: ${asset.name}`);
    }
  }
}
export async function verifySourceAdmission(document: AssemblyDocument, verifyTiff?: TiffVerifier): Promise<void> {
  for (const asset of document.assets) {
    if (asset.kind === 'tiff') {
      if (!verifyTiff) throw new Error('TIFF projects require the desktop application to verify original pixels.');
      await verifyTiff(asset.bytesBase64, asset.normalizedPngBase64!);
    }
    const inspected = await inspectSource({
      name: asset.name, bytesBase64: asset.bytesBase64,
      normalizedPngBase64: asset.normalizedPngBase64,
      dpi: asset.pages[0].dpiAssumed ? undefined : asset.pages[0].dpi,
    });
    if (inspected.kind !== asset.kind || inspected.pages.length !== asset.pages.length) {
      throw new Error(`Source type or page inventory does not match original bytes: ${asset.name}`);
    }
    for (let index = 0; index < asset.pages.length; index++) {
      const actual = inspected.pages[index], stored = asset.pages[index];
      for (const field of ['index', 'widthPt', 'heightPt', 'pixelWidth', 'pixelHeight', 'dpi', 'dpiAssumed'] as const) {
        if (actual[field] !== stored[field]) {
          throw new Error(`Source page geometry or resolution does not match original bytes: ${asset.name}`);
        }
      }
    }
    if (inspected.normalizedPngSha256 !== asset.normalizedPngSha256) {
      throw new Error(`TIFF decoding identity does not match original bytes: ${asset.name}`);
    }
  }
}
export async function serializeProject(document: AssemblyDocument, verifyTiff?: TiffVerifier): Promise<string> {
  validateDocument(document);
  await verifySourceHashes(document);
  await verifySourceAdmission(document, verifyTiff);
  const text = JSON.stringify(document);
  if (text.length > MAX_PROJECT_CHARACTERS) throw new Error('Project exceeds the 192 MiB file limit.');
  return text;
}
export async function parseProject(text: string, verifyTiff?: TiffVerifier): Promise<AssemblyDocument> {
  if (text.length > MAX_PROJECT_CHARACTERS) throw new Error('Project exceeds the 192 MiB file limit.');
  const value: unknown = JSON.parse(text);
  validateDocument(value);
  await verifySourceHashes(value);
  await verifySourceAdmission(value, verifyTiff);
  return value;
}
