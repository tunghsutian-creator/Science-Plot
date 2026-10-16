import { useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { ControlPopover } from './ControlPopover';
import { Icon } from './Icon';

function GridControls({ rows, columns, onApply }: { rows: number; columns: number; onApply: (rows: number, columns: number) => void }) {
  const [nextRows, setRows] = useState(rows), [nextColumns, setColumns] = useState(columns);
  return <form onSubmit={(event) => { event.preventDefault(); onApply(nextRows, nextColumns); }}>
    <div className="popover-heading">Grid layout</div>
    <div className="compact-presets">{[[2, 2], [3, 2], [2, 3], [3, 3]].map(([cols, count]) =>
      <button type="button" key={`${cols}:${count}`} aria-pressed={nextColumns === cols && nextRows === count}
        onClick={() => { setRows(count); setColumns(cols); }}>{cols} × {count}</button>)}</div>
    <div className="compact-fields"><label>Columns<input type="number" min="1" max="12" value={nextColumns} onChange={(event) => setColumns(Number(event.target.value))} /></label>
      <label>Rows<input type="number" min="1" max="12" value={nextRows} onChange={(event) => setRows(Number(event.target.value))} /></label></div>
    <div className="popover-apply"><span>{nextColumns * 60} × {nextRows * 55} mm</span><button type="submit">Apply grid</button></div>
  </form>;
}

export function Toolbar({ title, dirty, rows, columns, labels, canUndo, canRedo, busy, zoom, onZoomChange, onGridChange, onAction }: {
  title: string; dirty: boolean; rows: number; columns: number; labels: boolean;
  canUndo: boolean; canRedo: boolean; busy: boolean; zoom: string;
  onZoomChange: (value: string) => void; onAction: (action: string) => void;
  onGridChange: (rows: number, columns: number) => boolean;
}) {
  const toolbar = useRef<HTMLElement>(null);
  const [active, setActive] = useState<'grid' | 'labels' | 'zoom' | null>(null);
  useEffect(() => {
    const close = (event: globalThis.MouseEvent | KeyboardEvent) => {
      for (const menu of toolbar.current?.querySelectorAll<HTMLDetailsElement>('details[open]') ?? []) {
        if (event instanceof KeyboardEvent) {
          if (event.key !== 'Escape') return;
          menu.open = false; menu.querySelector<HTMLElement>('summary')?.focus();
        } else if (!(event.target instanceof Node) || !menu.contains(event.target)) menu.open = false;
      }
    };
    window.addEventListener('click', close); window.addEventListener('keydown', close);
    return () => { window.removeEventListener('click', close); window.removeEventListener('keydown', close); };
  }, []);
  useEffect(() => {
    const show = (event: Event) => {
      if (event.type === 'assembly-control-close') { setActive(null); return; }
      const name = (event as CustomEvent<string>).detail;
      if (!busy && (name === 'grid' || name === 'labels' || name === 'zoom')) setActive(name);
    };
    window.addEventListener('assembly-control', show);
    window.addEventListener('assembly-control-close', show);
    return () => { window.removeEventListener('assembly-control', show); window.removeEventListener('assembly-control-close', show); };
  }, [busy]);

  function closeMenu(event: MouseEvent<HTMLButtonElement>, action: string) {
    event.currentTarget.closest('details')?.removeAttribute('open'); onAction(action);
  }

  return <header ref={toolbar} className="toolbar" aria-label="Figure assembly toolbar">
    <div className="document-menu-group toolbar-cluster">
      <details className="toolbar-menu">
        <summary aria-label="Project menu" title="Project menu"><Icon name="file" size={18} />
          <span className="project-title" title={title}>{title}{dirty ? <span className="dirty-indicator" aria-label="Unsaved changes" /> : null}</span>
          <Icon name="chevron" size={12} /></summary>
        <div className="toolbar-popover" role="group" aria-label="Project actions">
          <button disabled={busy} onClick={(event) => closeMenu(event, 'new')}>New project</button>
          <button disabled={busy} onClick={(event) => closeMenu(event, 'open')}>Open project…</button>
          <button disabled={busy} onClick={(event) => closeMenu(event, 'import')}>Import PDFs…</button>
          <button disabled={busy} onClick={(event) => closeMenu(event, 'saveAs')}>Save project as…</button>
        </div>
      </details>
    </div>
    <div className="layout-cluster toolbar-cluster">
    <div className="grid-group"><ControlPopover label="Choose grid template" title="Grid layout" open={active === 'grid' && !busy}
      onOpenChange={(open) => setActive(open ? 'grid' : null)} disabled={busy}
      trigger={<><Icon name="grid" size={17} /><span>{columns} × {rows}</span><Icon name="chevron" size={11} /></>}>
      <GridControls rows={rows} columns={columns} onApply={(count, cols) => { if (onGridChange(count, cols)) setActive(null); }} />
    </ControlPopover></div>
    <div className="labels-group"><ControlPopover label="Labels" title="Panel labels" open={active === 'labels' && !busy}
      onOpenChange={(open) => setActive(open ? 'labels' : null)} disabled={busy}
      trigger={<><span className="label-icon" aria-hidden="true">ab</span><Icon name="chevron" size={10} /></>}>
      <div className="popover-heading">Panel labels</div>
      <button className="popover-switch" type="button" role="switch" aria-checked={labels} onClick={() => onAction('labels')}>
        <span>Show panel letters</span><span className={`compact-switch${labels ? ' is-on' : ''}`} aria-hidden="true"><i /></span></button>
    </ControlPopover></div>
    <div className="history-group">
      <button className="toolbar-control icon-control" aria-label="Undo" title="Undo (⌘Z)" disabled={!canUndo || busy} onClick={() => onAction('undo')}><Icon name="undo" size={17} /></button>
      <button className="toolbar-control icon-control" aria-label="Redo" title="Redo (⇧⌘Z)" disabled={!canRedo || busy} onClick={() => onAction('redo')}><Icon name="redo" size={17} /></button>
    </div>
    </div>
    <div className="toolbar-spacer" />
    <div className="zoom-group toolbar-cluster">
      <ControlPopover label="Canvas zoom" title="Canvas zoom" open={active === 'zoom' && !busy} className="zoom-popover"
        onOpenChange={(open) => setActive(open ? 'zoom' : null)} disabled={busy}
        trigger={<><span>{zoom === 'fit' ? 'Fit' : `${zoom}%`}</span><Icon name="chevron" size={11} /></>}>
        <div className="zoom-options" role="menu" aria-label="Zoom levels">{['fit', '50', '75', '100', '125', '150', '200'].map((value) =>
          <button type="button" role="menuitemradio" aria-checked={zoom === value} key={value} onClick={() => { onZoomChange(value); setActive(null); }}>
            {value === 'fit' ? 'Fit to view' : `${value}%`}</button>)}</div>
      </ControlPopover>
    </div>
    <div className="save-group toolbar-cluster"><button className="toolbar-control" disabled={busy} onClick={() => onAction('save')} title="Save project (⌘S)">Save project</button></div>
    <div className="export-group toolbar-cluster"><button className="toolbar-control export-pdf" disabled={busy} onClick={() => onAction('export')}><Icon name="export" size={16} />Export PDF</button></div>
    <div className="more-group toolbar-cluster">
      <details className="toolbar-menu">
        <summary aria-label="More options" title="More options"><Icon name="more" size={19} /></summary>
        <div className="toolbar-popover toolbar-popover-right" role="group" aria-label="More actions">
          <button disabled={busy} onClick={(event) => closeMenu(event, 'exportOptions')}>Export options…</button>
        </div>
      </details>
    </div>
  </header>;
}
