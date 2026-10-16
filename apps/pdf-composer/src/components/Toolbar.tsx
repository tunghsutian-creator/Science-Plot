import type { MouseEvent } from 'react';
import { GlassSurface } from './GlassSurface';
import { Icon } from './Icon';

export function Toolbar({ title, dirty, rows, columns, labels, canUndo, canRedo, busy, zoom, onZoomChange, onAction }: {
  title: string; dirty: boolean; rows: number; columns: number; labels: boolean;
  canUndo: boolean; canRedo: boolean; busy: boolean; zoom: string;
  onZoomChange: (value: string) => void; onAction: (action: string) => void;
}) {
  function closeMenu(event: MouseEvent<HTMLButtonElement>, action: string) {
    event.currentTarget.closest('details')?.removeAttribute('open'); onAction(action);
  }

  return <header className="toolbar" aria-label="Figure assembly toolbar">
    <GlassSurface className="document-menu-group">
      <details className="toolbar-menu">
        <summary aria-label="Project menu" title="Project menu"><Icon name="rail" size={24} /><Icon name="chevron" size={15} /></summary>
        <div className="toolbar-popover" role="group" aria-label="Project actions">
          <button disabled={busy} onClick={(event) => closeMenu(event, 'new')}>New project</button>
          <button disabled={busy} onClick={(event) => closeMenu(event, 'open')}>Open project…</button>
          <button disabled={busy} onClick={(event) => closeMenu(event, 'import')}>Import PDFs…</button>
          <button disabled={busy} onClick={(event) => closeMenu(event, 'saveAs')}>Save project as…</button>
        </div>
      </details>
    </GlassSurface>
    <div className="project-title" title={title}>{title}{dirty ? <span className="dirty-indicator" aria-label="Unsaved changes" /> : null}</div>
    <GlassSurface className="grid-group" refract>
      <button className="toolbar-control" disabled={busy} onClick={() => onAction('grid')} aria-label="Choose grid template">
        <Icon name="grid" size={23} /><span>{columns} × {rows}</span><Icon name="chevron" size={15} /></button>
    </GlassSurface>
    <GlassSurface className={`labels-group${labels ? ' is-active' : ''}`}>
      <button className="toolbar-control" aria-label="Labels" aria-pressed={labels} title="Toggle panel labels" disabled={busy} onClick={() => onAction('labels')}>
        <span className="label-icon" aria-hidden="true">a b</span><Icon name="chevron" size={15} /></button>
    </GlassSurface>
    <GlassSurface className="history-group" refract>
      <button className="toolbar-control icon-control" aria-label="Undo" title="Undo (⌘Z)" disabled={!canUndo || busy} onClick={() => onAction('undo')}><Icon name="undo" size={23} /></button>
      <button className="toolbar-control icon-control" aria-label="Redo" title="Redo (⇧⌘Z)" disabled={!canRedo || busy} onClick={() => onAction('redo')}><Icon name="redo" size={23} /></button>
    </GlassSurface>
    <GlassSurface className="zoom-group" refract>
      <label className="zoom-control"><span className="sr-only">Canvas zoom</span>
        <select value={zoom} onChange={(event) => onZoomChange(event.target.value)}>
          <option value="fit">Fit</option>{[50, 75, 100, 125, 150, 200].map((value) => <option key={value} value={String(value)}>{value}%</option>)}
        </select><Icon name="chevron" size={15} /></label>
    </GlassSurface>
    <div className="toolbar-spacer" />
    <GlassSurface className="save-group"><button className="toolbar-control" disabled={busy} onClick={() => onAction('save')} title="Save project (⌘S)">Save project</button></GlassSurface>
    <GlassSurface className="export-group"><button className="toolbar-control export-pdf" disabled={busy} onClick={() => onAction('export')}>Export PDF</button></GlassSurface>
    <GlassSurface className="more-group">
      <details className="toolbar-menu">
        <summary aria-label="More options" title="More options"><Icon name="more" size={23} /></summary>
        <div className="toolbar-popover toolbar-popover-right" role="group" aria-label="More actions">
          <button disabled={busy} onClick={(event) => closeMenu(event, 'exportOptions')}>Export options…</button>
        </div>
      </details>
    </GlassSurface>
  </header>;
}
