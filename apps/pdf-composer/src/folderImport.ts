import { MAX_SOURCE_BYTES, MAX_TOTAL_BYTES } from './core/document';
import type { SourceAsset } from './core/types';
import { readBrowserSources } from './browserFiles';
import { inspectSource } from './pdf';

export interface FolderImportResult {
  assets: SourceAsset[];
  unsupported: number;
  invalid: number;
  limited: number;
  failures: { name: string; path: string; reason: string }[];
  relativePaths: Record<string, string>;
}

function storedBytes(base64: string): number {
  return base64.length / 4 * 3 - (base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0);
}

function sourceBytes(asset: SourceAsset): number {
  return storedBytes(asset.bytesBase64) + (asset.normalizedPngBase64 ? storedBytes(asset.normalizedPngBase64) : 0);
}

/** Relative paths establish order only. Portable sources retain original names and bytes. */
export function orderFolderFiles(files: readonly File[]): File[] {
  const path = (file: File) => file.webkitRelativePath || file.name;
  return [...files].sort((first, second) => {
    const a = path(first), b = path(second);
    return a < b ? -1 : a > b ? 1 : 0;
  });
}

/** A bad source cannot erase the rest of an explicitly selected local folder. */
export async function inspectFolderSources(files: readonly File[], existing: readonly SourceAsset[]): Promise<FolderImportResult> {
  const result: FolderImportResult = { assets: [], unsupported: 0, invalid: 0, limited: 0, failures: [], relativePaths: {} };
  let remainingBytes = MAX_TOTAL_BYTES - existing.reduce((total, asset) => total + sourceBytes(asset), 0);
  const remainingSources = Math.max(0, 100 - existing.length);
  for (const file of orderFolderFiles(files)) {
    if (!/\.(?:pdf|png|jpe?g)$/i.test(file.name)) { result.unsupported++; continue; }
    if (result.assets.length >= remainingSources || file.size > MAX_SOURCE_BYTES || file.size > remainingBytes) {
      result.limited++; continue;
    }
    try {
      const [imported] = await readBrowserSources([file]);
      const asset = await inspectSource(imported);
      const bytes = sourceBytes(asset);
      if (bytes > remainingBytes) { result.limited++; continue; }
      result.assets.push(asset); remainingBytes -= bytes;
      result.relativePaths[asset.id] = file.webkitRelativePath || file.name;
    } catch (error) {
      result.invalid++;
      if (result.failures.length < 2) result.failures.push({ name: file.name, path: file.webkitRelativePath || file.name,
        reason: error instanceof Error ? error.message : 'The file could not be read.' });
    }
  }
  return result;
}

export function folderImportNotice(result: FolderImportResult): string {
  const count = result.assets.length;
  const status = count ? `Imported ${count} ${count === 1 ? 'source' : 'sources'} from folder.` : 'No sources imported from folder.';
  const skipped = [result.unsupported ? `${result.unsupported} unsupported` : '',
    result.invalid ? `${result.invalid} unreadable or invalid` : '', result.limited ? `${result.limited} over project limits` : ''].filter(Boolean);
  const details = result.failures.map(({ path }) => {
    const characters = [...path];
    return characters.length > 72 ? `…${characters.slice(-69).join('')}` : path;
  }).join(', ');
  return `${status}${skipped.length ? ` Skipped ${skipped.join(', ')}${details ? ` (${details})` : ''}.` : ''}${result.unsupported ? ' Supported: PDF, PNG and JPEG.' : ''}`;
}
