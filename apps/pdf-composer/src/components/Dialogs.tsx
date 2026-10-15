import { useState } from 'react';
import { orderedPanels, PT_PER_MM } from '../core/document';
import type { SourceAsset } from '../core/types';
import { Modal } from './Modal';
import { PagePreview } from './PagePreview';
import type { Composer } from './useComposer';

function DialogError({ composer }: { composer: Composer }) {
  return composer.notice?.error ? <p className="dialog-error" role="alert">{composer.notice.text}</p> : null;
}

function PagePicker({ asset, onPlace, onClose }: { asset: SourceAsset; onPlace: (index: number) => void; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const batch = Math.floor(index / 9) * 9;
  return <Modal title="Choose a page" onClose={onClose} wide>
    <p className="dialog-description">{asset.name} · {asset.pages.length} pages. Each page stays intact.</p>
    <div className="page-picker-grid">{asset.pages.slice(batch, batch + 9).map((page) => <button key={page.index}
      className={`page-choice${index === page.index ? ' is-selected' : ''}`} aria-label={`Page ${page.index + 1}, ${(page.widthPt / PT_PER_MM).toFixed(2)} by ${(page.heightPt / PT_PER_MM).toFixed(2)} millimetres`}
      aria-pressed={index === page.index} onClick={() => setIndex(page.index)}>
      <span className="page-choice-image"><PagePreview asset={asset} pageIndex={page.index} maxPixels={280} label={false} /></span>
      <strong>Page {page.index + 1}</strong><span>{(page.widthPt / PT_PER_MM).toFixed(2)} × {(page.heightPt / PT_PER_MM).toFixed(2)} mm</span>
    </button>)}</div>
    <div className="page-navigation"><button className="button" disabled={batch === 0} onClick={() => setIndex(Math.max(0, batch - 9))}>Previous</button>
      <label>Page <input type="number" min="1" max={asset.pages.length} value={index + 1}
        onChange={(event) => { const next = Number(event.target.value) - 1; if (Number.isInteger(next) && next >= 0 && next < asset.pages.length) setIndex(next); }} /> of {asset.pages.length}</label>
      <button className="button" disabled={batch + 9 >= asset.pages.length} onClick={() => setIndex(batch + 9)}>Next</button></div>
    <div className="modal-actions"><button className="button" onClick={onClose}>Cancel</button><button className="button button-primary" onClick={() => onPlace(index)}>Place page {index + 1}</button></div>
  </Modal>;
}

function GridDialog({ composer }: { composer: Composer }) {
  const [rows, setRows] = useState(composer.document.grid.rows), [columns, setColumns] = useState(composer.document.grid.columns);
  return <Modal title="Grid layout" onClose={() => composer.setModal(null)}>
    <p className="dialog-description">60 × 55 mm cells, with no additional outer margin. Changing containers never resizes a source.</p>
    <div className="template-options">{[[2, 2], [3, 2], [2, 3], [3, 3]].map(([cols, count]) => <button key={`${cols}:${count}`}
      className={`template-choice${columns === cols && rows === count ? ' is-selected' : ''}`} aria-pressed={columns === cols && rows === count}
      onClick={() => { setRows(count); setColumns(cols); }}><span className="template-grid" style={{ gridTemplateColumns: `repeat(${cols},1fr)` }}>
        {Array.from({ length: cols * count }, (_, index) => <i key={index} />)}</span>{cols} × {count}</button>)}</div>
    <form onSubmit={(event) => { event.preventDefault(); composer.resize(rows, columns); }}>
      <div className="form-row"><label>Columns<input type="number" min="1" max="12" value={columns} onChange={(event) => setColumns(Number(event.target.value))} /></label>
        <label>Rows<input type="number" min="1" max="12" value={rows} onChange={(event) => setRows(Number(event.target.value))} /></label></div>
      <p className="dimension-readout">{columns * 60} × {rows * 55} mm</p><DialogError composer={composer} />
      <div className="modal-actions"><button className="button" type="button" onClick={() => composer.setModal(null)}>Cancel</button><button className="button button-primary">Apply grid</button></div>
    </form>
  </Modal>;
}

function ScaleDialog({ composer }: { composer: Composer }) {
  const modal = composer.modal;
  const panel = modal?.kind === 'scale' ? composer.document.panels.find((item) => item.id === modal.panelId) : null;
  const maximum = modal?.kind === 'scale' ? modal.maxScale : 1;
  const [percent, setPercent] = useState(panel ? panel.scale * 100 : 100);
  if (modal?.kind !== 'scale') return null;
  const source = composer.document.assets.find((asset) => asset.id === modal.assetId);
  const page = source?.pages[modal.pageIndex];
  const valid = Number.isFinite(percent) && percent >= 0.1 && percent / 100 <= maximum + 0.000001;
  const exactFit = Math.min(1, maximum);
  const fitPercent = (exactFit * 100).toFixed(2);
  return <Modal title={modal.intent === 'scale' ? 'Scale whole page' : 'This page needs more room'} onClose={() => composer.setModal(null)}>
    <p className="dialog-description">{modal.intent === 'scale' ? 'Scaling is uniform and explicit.' : 'Merge cells for a larger container, or explicitly scale the whole page.'} Original whitespace and page proportions are preserved.</p>
    {page ? <p className="source-readout">{source?.name} · {(page.widthPt / PT_PER_MM).toFixed(2)} × {(page.heightPt / PT_PER_MM).toFixed(2)} mm at 100%</p> : null}
    <form onSubmit={(event) => { event.preventDefault(); if (valid) composer.confirmScale(percent / 100); }}>
      <label className="scale-field">Scale <span><input type="number" min="0.1" max={maximum * 100} step="any" value={percent}
        onChange={(event) => setPercent(Number(event.target.value))} autoFocus /> %</span></label>
      <button className="button button-primary fit-page-button" type="button" onClick={() => composer.confirmScale(exactFit)}>
        Fit whole page to cell (≈{fitPercent}%)</button>
      {!valid ? <p className="dialog-error">Use a smaller scale or choose the exact fit above. To keep 100%, retain the original and merge cells first.</p> : null}
      {page?.pixelWidth ? <p className="resolution-note">Effective source resolution: {Math.round((page.dpi ?? 300) / (percent / 100 || 1))} dpi{page.dpiAssumed ? ' · original DPI unknown; 300 dpi assumed' : ''}.</p> : null}
      <DialogError composer={composer} /><div className="modal-actions">
        {modal.intent === 'place' && maximum < 1 ? <button className="button" type="button" onClick={() => {
          composer.setModal(null); composer.setNotice({ text: 'Original size retained. Merge adjacent cells, then choose the source again to place at 100%. The current placement is unchanged.', error: false });
        }}>Keep original size</button> : null}
        <button className="button" type="button" onClick={() => composer.setModal(null)}>Cancel</button>
        <button className="button button-primary" disabled={!valid}>{modal.intent === 'split' ? 'Apply scale & split' : 'Apply scale'}</button></div>
    </form>
  </Modal>;
}

function MoveDialog({ composer }: { composer: Composer }) {
  const [targetId, setTargetId] = useState('');
  if (composer.modal?.kind !== 'move') return null;
  const originId = composer.modal.panelId;
  return <Modal title="Move or swap figure" onClose={() => composer.setModal(null)}>
    <p className="dialog-description">Choose a destination. If it contains a figure, the two sources swap while keeping their explicit scales.</p>
    <label className="select-field">Destination<select aria-label="Destination" value={targetId} onChange={(event) => setTargetId(event.target.value)} autoFocus>
      <option value="">Choose a panel…</option>{orderedPanels(composer.document).filter((panel) => panel.id !== originId).map((panel) => {
        const asset = composer.document.assets.find((item) => item.id === panel.assetId);
        return <option key={panel.id} value={panel.id}>Row {panel.row + 1}, column {panel.column + 1} · {asset?.name ?? 'Empty'}</option>;
      })}</select></label><DialogError composer={composer} />
    <div className="modal-actions"><button className="button" onClick={() => composer.setModal(null)}>Cancel</button>
      <button className="button button-primary" disabled={!targetId} onClick={() => composer.swap(originId, targetId)}>Move / swap</button></div>
  </Modal>;
}

function ExportDialog({ composer, onExport }: { composer: Composer; onExport: (format: 'pdf' | 'png' | 'tiff', dpi: number) => void }) {
  const [format, setFormat] = useState<'pdf' | 'png' | 'tiff'>('pdf');
  const [dpi, setDpi] = useState(300);
  const rasterPanels = composer.document.panels.filter((panel) => panel.assetId).flatMap((panel) => {
    const asset = composer.document.assets.find((item) => item.id === panel.assetId), page = asset?.pages[panel.pageIndex];
    return asset && page?.pixelWidth ? [{ name: asset.name, effective: (page.dpi ?? 300) / panel.scale, assumed: page.dpiAssumed }] : [];
  });
  const width = composer.document.grid.columns * 60, height = composer.document.grid.rows * 55;
  return <Modal title="Export figure" onClose={() => composer.setModal(null)}>
    <p className="dialog-description">PDF preserves original text, vectors and source resources. PNG and TIFF render the assembled page at your chosen DPI.</p>
    <div className="export-form"><label>Format<select aria-label="Format" value={format} onChange={(event) => setFormat(event.target.value as typeof format)}>
      <option value="pdf">PDF · vector</option><option value="png">PNG · raster</option><option value="tiff">TIFF · raster</option></select></label>
      <label>Raster DPI<select aria-label="Raster DPI" value={dpi} disabled={format === 'pdf'} onChange={(event) => setDpi(Number(event.target.value))}>
        {[150, 300, 600, 1200].map((value) => <option key={value} value={value}>{value} dpi</option>)}</select></label></div>
    <p className="dimension-readout">{width} × {height} mm{format === 'pdf' ? '' : ` · ${Math.ceil(width / 25.4 * dpi)} × ${Math.ceil(height / 25.4 * dpi)} px`}</p>
    {rasterPanels.length > 0 ? <div className="resolution-list"><h3>Source resolution</h3>{rasterPanels.map((item, index) => <p key={`${item.name}:${index}`}
      className={item.effective < (format === 'pdf' ? 300 : dpi) || item.assumed ? 'resolution-warning' : ''}>
      {item.name}: {Math.round(item.effective)} dpi{item.assumed ? ' · original DPI unknown, 300 dpi assumed' : ''}
      {item.effective < (format === 'pdf' ? 300 : dpi) ? ' · below output target' : ''}</p>)}<p>Higher export DPI cannot add detail to a raster source.</p></div> : null}
    <DialogError composer={composer} /><div className="modal-actions"><button className="button" disabled={composer.busy} onClick={() => composer.setModal(null)}>Cancel</button>
      <button className="button button-primary" disabled={composer.busy} onClick={() => onExport(format, dpi)}>{composer.busy ? 'Exporting…' : `Export ${format.toUpperCase()}`}</button></div>
  </Modal>;
}

export function Dialogs({ composer, onExport, onDiscard }: { composer: Composer;
  onExport: (format: 'pdf' | 'png' | 'tiff', dpi: number) => void; onDiscard: () => void;
}) {
  const modal = composer.modal;
  if (modal?.kind === 'grid') return <GridDialog composer={composer} />;
  if (modal?.kind === 'scale') return <ScaleDialog composer={composer} />;
  if (modal?.kind === 'move') return <MoveDialog composer={composer} />;
  if (modal?.kind === 'export') return <ExportDialog composer={composer} onExport={onExport} />;
  if (modal?.kind === 'discard') return <Modal title="Keep your changes?" onClose={() => composer.setModal(null)}>
    <p className="dialog-description">This project has unsaved changes. Save it first, or discard these changes to continue.</p>
    <div className="modal-actions"><button className="button" onClick={() => composer.setModal(null)}>Cancel</button><button className="button button-destructive" onClick={onDiscard}>Discard changes</button></div>
  </Modal>;
  if (modal?.kind === 'pages') {
    const asset = composer.document.assets.find((item) => item.id === modal.assetId);
    return asset ? <PagePicker key={asset.id} asset={asset} onClose={() => composer.setModal(null)} onPlace={(index) => composer.place(asset, modal.targetId, index)} /> : null;
  }
  return null;
}
