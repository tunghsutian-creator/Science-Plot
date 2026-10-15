import { toBase64 } from './core/bytes';
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

function chooseFiles(accept: string, multiple: boolean): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = accept; input.multiple = multiple;
    input.hidden = true;
    document.body.append(input);
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      window.removeEventListener('focus', onFocus);
      const files = Array.from(input.files ?? []);
      input.remove(); resolve(files);
    };
    const onFocus = () => { window.setTimeout(() => { if (!input.files?.length) finish(); }, 400); };
    input.addEventListener('change', finish, { once: true });
    input.addEventListener('cancel', finish, { once: true });
    window.addEventListener('focus', onFocus, { once: true });
    input.click();
  });
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
    const files = await chooseFiles('.pdf,.png,.jpg,.jpeg,.tif,.tiff', true);
    return Promise.all(files.map(async (file) => ({ name: file.name,
      bytesBase64: toBase64(new Uint8Array(await file.arrayBuffer())) })));
  },
  async openProject() {
    if (hasNativeBridge()) return invoke<OpenedProject | null>('openProject', {});
    const [file] = await chooseFiles('.figureassembly', false);
    return file ? { name: file.name, text: await file.text(), token: '' } : null;
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
    if (!hasNativeBridge()) throw new Error('PDF previews are rendered in the desktop application.');
    return invoke<string>('previewPdf', { bytesBase64, pageIndex, maxPixels });
  },
  async setDocumentState(title, dirty) {
    if (hasNativeBridge()) await invoke<void>('setDocumentState', { title, dirty });
  },
};
