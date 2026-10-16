import { readBrowserProject, readBrowserSources } from './browserFiles';
import type { ImportedFile, NativeBridge, NativeSaveResult, OpenedProject } from './core/types';

interface NativeReply { id: string; result?: unknown; error?: { message: string; code?: string } }
declare global {
  interface Window {
    webkit?: { messageHandlers?: { assembly?: { postMessage(message: unknown): void } } };
    __assemblyReply?: (reply: NativeReply) => void;
  }
}

const pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
window.__assemblyReply = ({ id, result, error }) => {
  const request = pending.get(id);
  if (!request) return;
  pending.delete(id);
  if (error) request.reject(Object.assign(new Error(error.message), { code: error.code }));
  else request.resolve(result);
};

export function hasNativeBridge(): boolean {
  return Boolean(window.webkit?.messageHandlers?.assembly);
}

function invoke<T>(method: string, params: unknown): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const handler = window.webkit?.messageHandlers?.assembly;
    if (!handler) { reject(new Error('This operation needs the desktop application.')); return; }
    const id = crypto.randomUUID();
    pending.set(id, { resolve: (result) => resolve(result as T), reject });
    try { handler.postMessage({ id, method, params }); }
    catch (error) { pending.delete(id); reject(error); }
  });
}

function chooseFiles(accept: string, multiple: boolean, directory = false): Promise<File[]> {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = accept; input.multiple = multiple;
    if (directory) {
      if (!('webkitdirectory' in input)) { reject(new Error('Folder import needs Microsoft Edge. Use Import files instead.')); return; }
      input.webkitdirectory = true;
    }
    input.hidden = true;
    document.body.append(input);
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      const files = Array.from(input.files ?? []);
      input.remove(); resolve(files);
    };
    input.addEventListener('change', finish, { once: true });
    input.addEventListener('cancel', finish, { once: true });
    try { input.click(); } catch (error) { input.remove(); reject(error); }
  });
}

/** A target cell has one source; a user gesture opens a single-file system picker. */
export async function importPanelSource(): Promise<ImportedFile[]> {
  if (hasNativeBridge()) {
    const files = await invoke<ImportedFile[]>('importFiles', {});
    if (files.length > 1) throw new Error('Choose one source file for this cell. Use Import files to add several sources.');
    return files;
  }
  return readBrowserSources(await chooseFiles('.pdf,.png,.jpg,.jpeg', false));
}

/** Edge recursively supplies the selected folder through webkitRelativePath. */
export function chooseFolderFiles(): Promise<File[]> {
  if (hasNativeBridge()) return Promise.reject(new Error('Folder import is available in the Microsoft Edge workspace. Use Import files in the desktop app.'));
  return chooseFiles('', true, true);
}

function download(bytes: BlobPart, name: string, type: string): NativeSaveResult {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name;
  document.body.append(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { cancelled: false, name };
}

export const bridge: NativeBridge = {
  async importFiles() {
    if (hasNativeBridge()) return invoke<ImportedFile[]>('importFiles', {});
    const files = await chooseFiles('.pdf,.png,.jpg,.jpeg', true);
    return readBrowserSources(files);
  },
  async openProject() {
    if (hasNativeBridge()) return invoke<OpenedProject | null>('openProject', {});
    const [file] = await chooseFiles('.figureassembly', false);
    return file ? readBrowserProject(file) : null;
  },
  async saveProject(text, name, token) {
    if (hasNativeBridge()) return invoke<NativeSaveResult>('saveProject', { text, name, ...(token ? { token } : {}) });
    return download(text, name, 'application/json');
  },
  async saveExport(bytesBase64, name, format, dpi) {
    if (hasNativeBridge()) return invoke<NativeSaveResult>('saveExport', { bytesBase64, name, format, dpi });
    if (format !== 'pdf') throw new Error('PNG and TIFF export use the desktop renderer. You can export PDF here.');
    const bytes = Uint8Array.from(atob(bytesBase64), (character) => character.charCodeAt(0));
    return download(bytes.buffer, name, 'application/pdf');
  },
  async previewPdf(bytesBase64, pageIndex, maxPixels) {
    if (hasNativeBridge()) return invoke<string>('previewPdf', { bytesBase64, pageIndex, maxPixels });
    const { browserPdfPreview } = await import('./browserPreview');
    return browserPdfPreview(bytesBase64, pageIndex, maxPixels);
  },
  async verifyTiff(bytesBase64, normalizedPngBase64) {
    if (!hasNativeBridge()) throw new Error('TIFF verification needs the desktop application. Import PDF, PNG or JPEG here.');
    await invoke<void>('verifyTiff', { bytesBase64, normalizedPngBase64 });
  },
  async setDocumentState(title, dirty) {
    if (hasNativeBridge()) await invoke<void>('setDocumentState', { title, dirty });
  },
};
