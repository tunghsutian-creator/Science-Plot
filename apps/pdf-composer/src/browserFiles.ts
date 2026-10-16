import { toBase64 } from './core/bytes';
import { MAX_SOURCE_BYTES, MAX_TOTAL_BYTES } from './core/document';
import type { ImportedFile, OpenedProject } from './core/types';

/** Read only user-selected local files; nothing is sent to a server. */
export async function readBrowserSources(files: File[]): Promise<ImportedFile[]> {
  if (files.length > 100 || files.some((file) => file.size > MAX_SOURCE_BYTES)) {
    throw new Error('Import up to 100 sources, each no larger than 64 MiB.');
  }
  if (files.reduce((total, file) => total + file.size, 0) > MAX_TOTAL_BYTES) {
    throw new Error('The selected source files exceed the 128 MiB project limit.');
  }
  return Promise.all(files.map(async (file) => ({ name: file.name,
    bytesBase64: toBase64(new Uint8Array(await file.arrayBuffer())) })));
}

export async function readBrowserProject(file: File): Promise<OpenedProject> {
  // Original bytes are base64 in the portable JSON. Bound the read before allocation.
  if (file.size > Math.ceil(MAX_TOTAL_BYTES * 4 / 3) + 2 * 1024 * 1024) {
    throw new Error('This project exceeds the portable source storage limit.');
  }
  return { name: file.name, text: await file.text(), token: '' };
}

export const SOURCE_DRAG_TYPE = 'application/x-figure-source';
export const PANEL_DRAG_TYPE = 'application/x-figure-panel';

// Escape must also cancel source drags, which originate outside PaperCanvas.
let activeSource: string | null = null;
export function startSourceDrag(id: string): void { activeSource = id; }
export function cancelSourceDrag(): void { activeSource = null; }
export function isActiveSourceDrag(id: string): boolean { return activeSource === id; }
