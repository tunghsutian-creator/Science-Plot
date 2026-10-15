import type { SourceAsset } from '../core/types';
import { PT_PER_MM } from '../core/document';
import { Icon } from './Icon';
import { PagePreview } from './PagePreview';

export function SourceRail({ assets, selectedAssetId, busy, onChoose, onCollapse, onImport, onOpen }: {
  assets: SourceAsset[]; selectedAssetId: string | null; busy: boolean;
  onChoose: (asset: SourceAsset) => void; onCollapse: () => void; onImport: () => void; onOpen: () => void;
}) {
  return <aside className="source-rail" aria-label="Imported sources">
    <div className="rail-heading"><h2>Sources</h2><button className="icon-button" aria-label="Hide sources" title="Hide sources"
      onClick={onCollapse}><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="m8 2-4 4 4 4" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg></button></div>
    <div className="source-list">
      {assets.map((asset) => <button key={asset.id} className={`source-item${selectedAssetId === asset.id ? ' is-selected' : ''}`}
        disabled={busy} onClick={() => onChoose(asset)} aria-label={`Place ${asset.name}`}>
        <div className="source-thumbnail"><PagePreview asset={asset} pageIndex={0} maxPixels={240} label={false} /></div>
        <span className="source-name">{asset.name}</span><span className="source-detail">{asset.pages.length} {asset.pages.length === 1 ? 'page' : 'pages'}
          {asset.pages.length === 1 ? ` · ${(asset.pages[0].widthPt / PT_PER_MM).toFixed(2)} × ${(asset.pages[0].heightPt / PT_PER_MM).toFixed(2)} mm` : ''}</span>
        {asset.pages[0]?.dpiAssumed ? <span className="source-dpi-warning">DPI unknown · 300 dpi assumed</span> : null}
      </button>)}
      {assets.length === 0 ? <div className="empty-sources"><Icon name="file" size={26} />
        <p>Your original pages,<br />ready to arrange.</p><button className="button" disabled={busy} onClick={onImport}>Import files</button></div> : null}
    </div>
    <div className="rail-footer"><button className="text-button" disabled={busy} onClick={onOpen}>Open project…</button></div>
  </aside>;
}
