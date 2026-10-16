import { memo, useEffect, useState } from 'react';
import { bridge } from '../bridge';
import type { SourceAsset } from '../core/types';
import { Icon } from './Icon';

interface CachedPreview { result: Promise<string>; size: number }
const previews = new Map<string, CachedPreview>();
const MAX_PREVIEWS = 24, MAX_PREVIEW_CHARACTERS = 24 * 1024 * 1024;

function trimPreviews() {
  let characters = [...previews.values()].reduce((total, entry) => total + entry.size, 0);
  for (const [key, entry] of previews) {
    if (previews.size <= MAX_PREVIEWS && characters <= MAX_PREVIEW_CHARACTERS) break;
    previews.delete(key); characters -= entry.size;
  }
}

function preview(asset: SourceAsset, pageIndex: number, maxPixels: number): Promise<string> {
  if (asset.kind === 'png' || asset.kind === 'jpeg') return Promise.resolve(`data:image/${asset.kind};base64,${asset.bytesBase64}`);
  if (asset.kind === 'tiff' && asset.normalizedPngBase64) return Promise.resolve(`data:image/png;base64,${asset.normalizedPngBase64}`);
  const key = `${asset.sha256}:${pageIndex}:${maxPixels}`;
  let entry = previews.get(key);
  if (!entry) {
    entry = { result: bridge.previewPdf(asset.bytesBase64, pageIndex, maxPixels), size: 0 };
    const created = entry;
    previews.set(key, created); trimPreviews();
    void created.result.then((url) => { created.size = url.length; trimPreviews(); }).catch(() => {
      if (previews.get(key) === created) previews.delete(key);
    });
  } else {
    // Map insertion order is the cache's LRU order.
    previews.delete(key); previews.set(key, entry);
  }
  return entry.result;
}

export const PagePreview = memo(function PagePreview({ asset, pageIndex, maxPixels = 1000, label = true, onReady }: {
  asset: SourceAsset; pageIndex: number; maxPixels?: number; label?: boolean; onReady?: () => void;
}) {
  const [result, setResult] = useState<{ key: string; url: string } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);
  const key = `${asset.sha256}:${pageIndex}:${maxPixels}`;
  useEffect(() => {
    let current = true;
    void preview(asset, pageIndex, maxPixels).then((url) => {
      if (current) { setResult({ key, url }); setFailed(null); }
    }).catch((error: unknown) => { if (current) setFailed({ key, message: error instanceof Error ? error.message : 'Preview unavailable.' }); });
    return () => { current = false; };
  }, [asset, pageIndex, maxPixels, key]);
  if (result?.key === key) return <img className="page-preview" src={result.url} alt={label ? `${asset.name}, page ${pageIndex + 1}` : ''} draggable={false} onLoad={onReady} />;
  const message = failed?.key === key ? failed.message : '';
  return <span className="preview-unavailable" title={message || 'Rendering page preview…'} role={message ? 'status' : undefined}>
    <Icon name="file" size={24} /><span>{message ? 'Preview unavailable' : 'Rendering preview…'}</span>
  </span>;
});
