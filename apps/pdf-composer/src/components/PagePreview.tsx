import { memo, useEffect, useState } from 'react';
import { bridge } from '../bridge';
import type { SourceAsset } from '../core/types';
import { Icon } from './Icon';

const previews = new Map<string, Promise<string>>();

function preview(asset: SourceAsset, pageIndex: number, maxPixels: number): Promise<string> {
  if (asset.kind === 'png' || asset.kind === 'jpeg') return Promise.resolve(`data:image/${asset.kind};base64,${asset.bytesBase64}`);
  if (asset.kind === 'tiff' && asset.normalizedPngBase64) return Promise.resolve(`data:image/png;base64,${asset.normalizedPngBase64}`);
  const key = `${asset.sha256}:${pageIndex}:${maxPixels}`;
  let result = previews.get(key);
  if (!result) {
    result = bridge.previewPdf(asset.bytesBase64, pageIndex, maxPixels);
    previews.set(key, result);
    void result.catch(() => previews.delete(key));
  }
  return result;
}

export const PagePreview = memo(function PagePreview({ asset, pageIndex, maxPixels = 1000, label = true }: {
  asset: SourceAsset; pageIndex: number; maxPixels?: number; label?: boolean;
}) {
  const [result, setResult] = useState<{ key: string; url: string } | null>(null);
  const [failed, setFailed] = useState('');
  const key = `${asset.sha256}:${pageIndex}:${maxPixels}`;
  useEffect(() => {
    let current = true;
    void preview(asset, pageIndex, maxPixels).then((url) => {
      if (current) { setResult({ key, url }); setFailed(''); }
    }).catch((error: unknown) => { if (current) setFailed(error instanceof Error ? error.message : 'Preview unavailable.'); });
    return () => { current = false; };
  }, [asset, pageIndex, maxPixels, key]);
  if (result?.key === key) return <img className="page-preview" src={result.url} alt={label ? `${asset.name}, page ${pageIndex + 1}` : ''} draggable={false} />;
  return <span className="preview-unavailable" title={failed || 'Rendering page preview…'}>
    <Icon name="file" size={24} /><span>{failed ? 'PDF preview in desktop app' : 'Rendering preview…'}</span>
  </span>;
});
