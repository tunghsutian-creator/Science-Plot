import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent, CSSProperties } from 'react';
import { orderedPanels, panelLetter, panelSizePt, PT_PER_MM } from '../core/document';
import type { AssemblyDocument, Panel } from '../core/types';
import { cancelSourceDrag, isActiveSourceDrag, PANEL_DRAG_TYPE, SOURCE_DRAG_TYPE } from '../browserFiles';
import { Icon } from './Icon';
import { PagePreview } from './PagePreview';

export function PaperCanvas({ document, selected, busy, zoom, onSelect, onDeselect, onImportToPanel, onSwap, onAction, onPlaceSource, onDropFiles }: {
  document: AssemblyDocument; selected: string[]; busy: boolean; zoom: string;
  onSelect: (id: string, range: boolean) => void; onSwap: (first: string, second: string) => void;
  onDeselect: () => void;
  onImportToPanel: (id: string) => void;
  onAction: (action: string) => void;
  onPlaceSource: (assetId: string, panelId: string) => void;
  onDropFiles: (files: File[], panelId?: string) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const placements = useRef(new Map<string, HTMLSpanElement>());
  const previousSources = useRef(new Map<string, string>());
  const pendingPlacements = useRef(new Set<string>());
  const liveAnimations = useRef(new Set<Animation>());
  const [available, setAvailable] = useState({ width: 1000, height: 720 });
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const panels = orderedPanels(document);
  const occupied = panels.filter((panel) => panel.assetId !== null);
  const widthMm = document.grid.columns * document.grid.cellWidthMm;
  const heightMm = document.grid.rows * document.grid.cellHeightMm;
  const fit = Math.max(120, Math.min(available.width - 64, (available.height - 20) * widthMm / heightMm));
  const width = zoom === 'fit' ? fit : widthMm * 96 / 25.4 * Number(zoom) / 100;
  const height = width * heightMm / widthMm;

  useLayoutEffect(() => {
    const current = new Map(document.panels.map((panel) => [panel.id, `${panel.assetId ?? ''}:${panel.pageIndex}`]));
    for (const panel of document.panels) {
      if (panel.assetId && previousSources.current.has(panel.id)
        && current.get(panel.id) !== previousSources.current.get(panel.id)) {
        pendingPlacements.current.add(panel.id);
      }
      if (!panel.assetId) pendingPlacements.current.delete(panel.id);
    }
    for (const id of pendingPlacements.current) if (!current.has(id)) pendingPlacements.current.delete(id);
    previousSources.current = current;
  }, [document.panels]);
  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const animations = liveAnimations.current;
    const stop = () => { if (reduced.matches) for (const animation of animations) animation.cancel(); };
    reduced.addEventListener('change', stop);
    return () => { reduced.removeEventListener('change', stop); for (const animation of animations) animation.cancel(); };
  }, []);

  function placementReady(id: string) {
    if (!pendingPlacements.current.delete(id) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const element = placements.current.get(id);
    if (!element) return;
    // Animate only after the actual PDF preview image has loaded. Never blur,
    // rescale or alter the original page, its physical layout or export bytes.
    const animation = element.animate([
      { transform: 'translate(-50%, calc(-50% + 6px))', opacity: 0.92 },
      { transform: 'translate(-50%, -50%)', opacity: 1 },
    ], { duration: 220, easing: 'cubic-bezier(.2,.7,.2,1)' });
    liveAnimations.current.add(animation);
    void animation.finished.catch(() => undefined).finally(() => liveAnimations.current.delete(animation));
  }

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
      if (event.key === 'Escape') {
        if (menu) { event.preventDefault(); event.stopImmediatePropagation(); }
        setDragging(null); setDropTarget(null); setMenu(null); cancelSourceDrag();
      }
    };
    window.addEventListener('keydown', cancel, true);
    return () => window.removeEventListener('keydown', cancel, true);
  }, [menu]);
  useEffect(() => {
    if (!menu) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) setMenu(null);
    };
    window.document.addEventListener('pointerdown', outside, true);
    return () => window.document.removeEventListener('pointerdown', outside, true);
  }, [menu]);

  function startDrag(event: DragEvent, panel: Panel) {
    if (busy || !panel.assetId) { event.preventDefault(); return; }
    event.dataTransfer.setData(PANEL_DRAG_TYPE, panel.id);
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

  return <main ref={viewport} className="workspace" aria-label="Figure layout canvas" onClick={() => { setMenu(null); onDeselect(); }}
    onDragOver={(event) => {
      if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = busy ? 'none' : 'copy'; }
    }} onDrop={(event) => {
      event.preventDefault(); event.stopPropagation(); setDropTarget(null); setDragging(null);
      if (!busy && event.dataTransfer.files.length) onDropFiles(Array.from(event.dataTransfer.files));
    }}>
    <div className="paper-positioner" style={{ minWidth: width + 64, minHeight: height + 20 }}>
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
            onClick={(event) => { event.stopPropagation(); setMenu(null); onSelect(panel.id, event.shiftKey); if (!asset && !event.shiftKey) onImportToPanel(panel.id); }}
            onKeyDown={(event) => cellKey(event, panel)} draggable={Boolean(asset) && !busy}
            onDragStart={(event) => startDrag(event, panel)} onDragEnd={() => { setDragging(null); setDropTarget(null); }}
            onDragOver={(event) => {
              const source = event.dataTransfer.types.includes(SOURCE_DRAG_TYPE), files = event.dataTransfer.types.includes('Files');
              if ((dragging || source || files) && !busy) {
                event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = source || files ? 'copy' : 'move'; setDropTarget(panel.id);
              }
            }}
            onDragLeave={() => setDropTarget(null)} onDrop={(event) => {
              event.preventDefault(); event.stopPropagation();
              const source = event.dataTransfer.getData(PANEL_DRAG_TYPE), assetId = event.dataTransfer.getData(SOURCE_DRAG_TYPE);
              if (!busy) {
                if (event.dataTransfer.files.length) onDropFiles(Array.from(event.dataTransfer.files), panel.id);
                else if (assetId && isActiveSourceDrag(assetId)) onPlaceSource(assetId, panel.id);
                else if (dragging && source === dragging) onSwap(source, panel.id);
              }
              cancelSourceDrag();
              setDragging(null); setDropTarget(null);
            }} onContextMenu={(event) => {
              event.preventDefault(); if (busy) return;
              if (!selected.includes(panel.id)) onSelect(panel.id, false);
              const bounds = viewport.current?.getBoundingClientRect();
              setMenu({ x: Math.min(event.clientX - (bounds?.left ?? 0), available.width - 180), y: Math.min(event.clientY - (bounds?.top ?? 0), available.height - 200) });
            }}>
            {asset && page ? <span className="source-placement" ref={(element) => { if (element) placements.current.set(panel.id, element); else placements.current.delete(panel.id); }} style={{ width: `${page.widthPt * panel.scale / size.width * 100}%`,
              height: `${page.heightPt * panel.scale / size.height * 100}%` }}><PagePreview asset={asset} pageIndex={panel.pageIndex} onReady={() => placementReady(panel.id)} /></span> :
              <span className="empty-panel-hint"><Icon name="plus" size={22} /><span>Choose or drop file</span></span>}
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
