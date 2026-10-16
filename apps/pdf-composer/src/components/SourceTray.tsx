import { useEffect, useRef, useState } from 'react';
import { cancelSourceDrag, SOURCE_DRAG_TYPE, startSourceDrag } from '../browserFiles';
import type { SourceAsset } from '../core/types';
import { Icon } from './Icon';
import { PagePreview } from './PagePreview';

export function SourceTray({ assets, selectedAssetId, busy, onChoose, onImport, onOpen, onDropFiles }: {
  assets: SourceAsset[]; selectedAssetId: string | null; busy: boolean;
  onChoose: (asset: SourceAsset) => void; onImport: () => void; onOpen: () => void;
  onDropFiles: (files: File[]) => void;
}) {
  const [dropping, setDropping] = useState(false);
  const sourceList = useRef<HTMLDivElement>(null);
  useEffect(() => {
    sourceList.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [selectedAssetId]);
  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { cancelSourceDrag(); setDropping(false); }
    };
    window.addEventListener('keydown', cancel);
    return () => { window.removeEventListener('keydown', cancel); cancelSourceDrag(); };
  }, []);

  return <aside className={`source-tray${dropping ? ' is-file-drag' : ''}`} aria-label="Imported sources"
    onDragOver={(event) => {
      if (event.dataTransfer.types.includes('Files')) {
        event.preventDefault(); event.stopPropagation();
        event.dataTransfer.dropEffect = busy ? 'none' : 'copy';
        if (!busy) setDropping(true);
      }
    }} onDragLeave={(event) => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDropping(false);
    }} onDrop={(event) => {
      event.preventDefault(); event.stopPropagation(); setDropping(false);
      if (!busy && event.dataTransfer.files.length) onDropFiles(Array.from(event.dataTransfer.files));
    }}>
    <div className="tray-heading"><h2>Sources</h2><button type="button" className="tray-open" disabled={busy}
      aria-label="Open project" title="Open a saved project" onClick={onOpen}>Open…</button></div>
    <div ref={sourceList} className="source-list" role="region" aria-label="Source pages" tabIndex={assets.length ? 0 : undefined}>
      {assets.map((asset) => <button type="button" key={asset.id}
        className={`source-item${selectedAssetId === asset.id ? ' is-selected' : ''}`}
        disabled={busy} draggable={!busy} onClick={() => onChoose(asset)} aria-label={`Place ${asset.name}`}
        aria-pressed={selectedAssetId === asset.id} title={`${asset.name} · ${asset.pages.length} ${asset.pages.length === 1 ? 'page' : 'pages'}${asset.pages[0]?.dpiAssumed ? ' · DPI unknown, 300 dpi assumed' : ''}`}
        onDragStart={(event) => {
          if (busy) { event.preventDefault(); return; }
          event.dataTransfer.setData(SOURCE_DRAG_TYPE, asset.id); event.dataTransfer.effectAllowed = 'copy'; startSourceDrag(asset.id);
        }} onDragEnd={cancelSourceDrag}>
        <span className="source-thumbnail"><PagePreview asset={asset} pageIndex={0} maxPixels={240} label={false} /></span>
        <span className="source-name">{asset.name}</span>
      </button>)}
    </div>
    <button type="button" className="tray-import" disabled={busy} onClick={onImport} aria-label="Import PDFs"
      title="Import PDF, PNG or JPEG files, or drop a saved project to reopen it">
      <Icon name="plus" size={23} /><span className="tray-import-label">Import PDFs</span>
    </button>
  </aside>;
}
