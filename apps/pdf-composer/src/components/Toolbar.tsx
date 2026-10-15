import { Icon } from './Icon';

export function Toolbar({ rows, columns, labels, canUndo, canRedo, busy, sourcesVisible, onAction }: {
  rows: number; columns: number; labels: boolean; canUndo: boolean; canRedo: boolean; busy: boolean;
  sourcesVisible: boolean; onAction: (action: string) => void;
}) {
  return <header className="toolbar" aria-label="Figure assembly toolbar">
    <div className="app-name">Figure Assembly</div>
    <button className="icon-button rail-toggle" title="Show sources" aria-label="Show sources" aria-pressed={sourcesVisible}
      onClick={() => onAction('sources')}><Icon name="rail" /></button>
    <button className="button toolbar-plain" disabled={busy} onClick={() => onAction('import')} title="Import PDF or image (⌘I)">
      <Icon name="import" /><span>Import</span></button>
    <button className="button" disabled={busy} onClick={() => onAction('grid')} aria-label="Choose grid template">
      <Icon name="grid" /><span>{columns} × {rows}</span><Icon name="chevron" size={14} /></button>
    <button className={`button labels-button${labels ? ' is-active' : ''}`} aria-pressed={labels} disabled={busy}
      onClick={() => onAction('labels')}><span className="label-icon" aria-hidden="true">A</span><span>Labels</span></button>
    <span className="toolbar-divider" />
    <button className="icon-button" aria-label="Undo" title="Undo (⌘Z)" disabled={!canUndo || busy} onClick={() => onAction('undo')}><Icon name="undo" /></button>
    <button className="icon-button" aria-label="Redo" title="Redo (⇧⌘Z)" disabled={!canRedo || busy} onClick={() => onAction('redo')}><Icon name="redo" /></button>
    <div className="toolbar-spacer" />
    <button className="button save-button" disabled={busy} onClick={() => onAction('save')} title="Save project (⌘S)"><Icon name="save" /><span>Save</span></button>
    <div className="export-buttons">
      <button className="button button-primary" disabled={busy} onClick={() => onAction('export')}><Icon name="export" /><span>Export PDF</span></button>
      <button className="button button-primary export-options" aria-label="Export options" title="PNG, TIFF and export options"
        disabled={busy} onClick={() => onAction('exportOptions')}><Icon name="chevron" size={14} /></button>
    </div>
  </header>;
}
