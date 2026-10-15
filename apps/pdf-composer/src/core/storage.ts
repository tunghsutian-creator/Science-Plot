import type { AssemblyDocument } from './types';
import { validateDocument } from './document';
import { fromBase64, sha256 } from './bytes';

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
export async function serializeProject(document: AssemblyDocument): Promise<string> {
  validateDocument(document);
  await verifySourceHashes(document);
  const text = JSON.stringify(document);
  if (text.length > MAX_PROJECT_CHARACTERS) throw new Error('Project exceeds the 192 MiB file limit.');
  return text;
}
export async function parseProject(text: string): Promise<AssemblyDocument> {
  if (text.length > MAX_PROJECT_CHARACTERS) throw new Error('Project exceeds the 192 MiB file limit.');
  const value: unknown = JSON.parse(text);
  validateDocument(value);
  await verifySourceHashes(value);
  return value;
}
