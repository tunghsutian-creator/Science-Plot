import { fromBase64 } from './core/bytes';
import type { PDFiumLibrary } from '@hyzyla/pdfium/inline';

let library: Promise<PDFiumLibrary> | undefined;
let queue: Promise<unknown> = Promise.resolve();

async function renderer(): Promise<PDFiumLibrary> {
  if (!library) {
    library = import('@hyzyla/pdfium/inline').then(({ PDFiumLibrary }) => PDFiumLibrary.init({ disableBase64Warning: true }));
    void library.catch(() => { library = undefined; });
  }
  return library;
}

/** Disposable local preview only. The PDF export never consumes these pixels. */
export function browserPdfPreview(bytesBase64: string, pageIndex: number, maxPixels: number): Promise<string> {
  const render = async () => {
    if (!Number.isInteger(pageIndex) || pageIndex < 0 || !Number.isInteger(maxPixels) || maxPixels < 32 || maxPixels > 2000) {
      throw new Error('The requested PDF preview size or page is invalid.');
    }
    const engine = await renderer();
    const document = await engine.loadDocument(fromBase64(bytesBase64));
    try {
      if (pageIndex >= document.getPageCount()) throw new Error('The selected PDF page is unavailable.');
      const page = document.getPage(pageIndex);
      try {
        const { originalWidth, originalHeight } = page.getOriginalSize();
        const scale = maxPixels / Math.max(originalWidth, originalHeight);
        const rendered = await page.render({ scale, colorSpace: 'RGBA', transparent: false });
        const canvas = window.document.createElement('canvas');
        canvas.width = rendered.width; canvas.height = rendered.height;
        const context = canvas.getContext('2d');
        if (!context) throw new Error('Edge could not create a canvas for the PDF preview.');
        context.putImageData(new ImageData(new Uint8ClampedArray(rendered.data), rendered.width, rendered.height), 0, 0);
        const url = canvas.toDataURL('image/png');
        canvas.width = 0; canvas.height = 0;
        return url;
      } finally { page.close(); }
    } finally { document.destroy(); }
  };
  // PDFium has one WASM heap. Serialize work and close every source/page promptly.
  const result = queue.then(render);
  queue = result.catch(() => undefined);
  return result.catch((error: unknown) => {
    throw new Error(`Local PDF preview failed: ${error instanceof Error ? error.message : 'unknown renderer error'}`);
  });
}
