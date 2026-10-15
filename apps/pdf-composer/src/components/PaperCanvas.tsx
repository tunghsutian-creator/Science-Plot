import { useEffect, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent, CSSProperties } from 'react';
import { orderedPanels, panelLetter, panelSizePt, PT_PER_MM } from '../core/document';
import type { AssemblyDocument, Panel } from '../core/types';
import { Icon } from './Icon';
import { PagePreview } from './PagePreview';

export function PaperCanvas({ document, selected, busy, zoom, onSelect, onSwap, onAction }: {
  document: AssemblyDocument; selected: string[]; busy: boolean; zoom: string;
  onSelect: (id: string, range: boolean) => void; onSwap: (first: string, second: string) => void;
  onAction: (action: string) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const [available, setAvailable] = useState({ width: 1000, height: 720 });
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const panels = orderedPanels(document);
  const occupied = panels.filter((panel) => panel.assetId !== null);
  const widthMm = document.grid.columns * document.grid.cellWidthMm;
  const heightMm = document.grid.rows * document.grid.cellHeightMm;
  const fit = Math.max(120, Math.min(available.width - 72, (available.height - 108) * widthMm / heightMm));
  const width = zoom === 'fit' ? fit : widthMm * 96 / 25.4 * Number(zoom) / 100;
  const height = width * heightMm / widthMm;

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setAvailable({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (menu) menuRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
  }, [menu]);
  useEffect(() => {
    const cancel = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { setDragging(null); setDropTarget(null); setMenu(null); }
    };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, []);

  function startDrag(event: DragEvent, panel: Panel) {
    if (busy || !panel.assetId) { event.preventDefault(); return; }
    event.dataTransfer.setData('application/x-figure-panel', panel.id);
    event.dataTransfer.effectAllowed = 'move';
    setDragging(panel.id); onSelect(panel.id, false); setMenu(null);
  }

  function cellKey(event: KeyboardEvent, panel: Panel) {
    const delta = { ArrowLeft: [0, -1], ArrowRight: [0, panel.columnSpan], ArrowUp: [-1, 0], ArrowDown: [panel.rowSpan, 0] }[event.key];
    if (!delta || event.metaKey || event.ctrlKey || event.altKey) return;
    event.preventDefault();
    const row = panel.row + delta[0], column = panel.column + delta[1];
    const target = panels.find((item) => item.row <= row && item.row + item.rowSpan > row
      && item.column <= column && item.column + item.columnSpan > column);
    if (target) { buttons.current.get(target.id)?.focus(); onSelect(target.id, event.shiftKey); }
  }

  return <main ref={viewport} className="workspace" aria-label="Figure layout canvas" onClick={() => setMenu(null)}>
    <div className="paper-positioner" style={{ minWidth: width + 72, minHeight: height + 108 }}>
      <div className="paper" style={{ width, height }} role="group" aria-label={`${widthMm} by ${heightMm} millimetre figure`}>
        {panels.map((panel) => {
          const asset = document.assets.find((item) => item.id === panel.assetId);
          const page = asset?.pages[panel.pageIndex];
          const size = panelSizePt(document, panel);
          const style: CSSProperties = { left: `${panel.column / document.grid.columns * 100}%`, top: `${panel.row / document.grid.rows * 100}%`,
            width: `${panel.columnSpan / document.grid.columns * 100}%`, height: `${panel.rowSpan / document.grid.rows * 100}%` };
          return <button key={panel.id} ref={(element) => { if (element) buttons.current.set(panel.id, element); else buttons.current.delete(panel.id); }}
            type="button" className={`figure-panel${asset ? ' has-source' : ' is-empty'}${selected.includes(panel.id) ? ' is-selected' : ''}${dropTarget === panel.id ? ' is-drop-target' : ''}${dragging === panel.id ? ' is-dragging' : ''}`}
            style={style} disabled={busy} aria-pressed={selected.includes(panel.id)}
            aria-label={`Panel row ${panel.row + 1}, column ${panel.column + 1}${asset ? `, ${asset.name}, page ${panel.pageIndex + 1}` : ', empty'}`}
            data-panel-id={panel.id} data-row={panel.row} data-column={panel.column} data-asset-id={panel.assetId ?? ''}
            onClick={(event) => { event.stopPropagation(); setMenu(null); onSelect(panel.id, event.shiftKey); }}
            onKeyDown={(event) => cellKey(event, panel)} draggable={Boolean(asset) && !busy}
            onDragStart={(event) => startDrag(event, panel)} onDragEnd={() => { setDragging(null); setDropTarget(null); }}
            onDragOver={(event) => { if (dragging && !busy) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; setDropTarget(panel.id); } }}
            onDragLeave={() => setDropTarget(null)} onDrop={(event) => {
              event.preventDefault(); const source = event.dataTransfer.getData('application/x-figure-panel');
              if (dragging && source === dragging && !busy) onSwap(source, panel.id);
              setDragging(null); setDropTarget(null);
            }} onContextMenu={(event) => {
              event.preventDefault(); if (busy) return;
              if (!selected.includes(panel.id)) onSelect(panel.id, false);
              const bounds = viewport.current?.getBoundingClientRect();
              setMenu({ x: Math.min(event.clientX - (bounds?.left ?? 0), available.width - 180), y: Math.min(event.clientY - (bounds?.top ?? 0), available.height - 200) });
            }}>
            {asset && page ? <span className="source-placement" style={{ width: `${page.widthPt * panel.scale / size.width * 100}%`,
              height: `${page.heightPt * panel.scale / size.height * 100}%` }}><PagePreview asset={asset} pageIndex={panel.pageIndex} /></span> :
              <span className="empty-panel-hint"><Icon name="plus" size={22} /><span>Select a source</span></span>}
            {asset && document.labels.enabled ? <span className="panel-letter" style={{
              left: `${document.labels.insetMm / (panel.columnSpan * document.grid.cellWidthMm) * 100}%`,
              top: `${document.labels.insetMm / (panel.rowSpan * document.grid.cellHeightMm) * 100}%`,
              fontSize: document.labels.fontSizePt * width / (widthMm * PT_PER_MM),
            }}>{panelLetter(occupied.findIndex((item) => item.id === panel.id))}</span> : null}
            {selected.includes(panel.id) ? <span className="selection-corners" aria-hidden="true"><i /><i /><i /><i /></span> : null}
          </button>;
        })}
      </div>
    </div>
    {menu ? <div ref={menuRef} className="panel-menu" role="menu" aria-label="Panel actions" style={{ left: menu.x, top: menu.y }} onClick={(event) => event.stopPropagation()}>
      {[['replace', 'Replace…'], ['scale', 'Scale…'], ['move', 'Move / swap…'], ['merge', 'Merge cells'], ['split', 'Split cells'], ['clear', 'Clear source']].map(([action, label]) =>
        <button key={action} role="menuitem" onClick={() => { setMenu(null); onAction(action); }}>{label}</button>)}
    </div> : null}
  </main>;
}
