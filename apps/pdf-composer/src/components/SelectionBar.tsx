import type { Panel } from '../core/types';

export function SelectionBar({ panels, busy, onAction }: { panels: Panel[]; busy: boolean; onAction: (action: string) => void }) {
  const panel = panels.length === 1 ? panels[0] : null;
  const filled = Boolean(panel?.assetId);
  return <div className="selection-bar" aria-label="Selected panel controls">
    <button disabled={busy || !filled} className="scale-control" onClick={() => onAction('scale')}>
      {panel ? filled ? `${Number((panel.scale * 100).toFixed(2))}%${panel.scale === 1 ? ' · Original size' : ' · Explicit scale'}` : 'Empty panel' : `${panels.length} panels selected`}</button>
    <span className="control-divider" />
    <button disabled={busy || !panel} onClick={() => onAction('replace')}>Replace</button>
    <button disabled={busy || panels.length < 2} onClick={() => onAction('merge')}>Merge</button>
    <button disabled={busy || !panel || (panel.rowSpan === 1 && panel.columnSpan === 1)} onClick={() => onAction('split')}>Split</button>
    <button disabled={busy || !filled} onClick={() => onAction('move')}>Move</button>
    <button disabled={busy || !panels.some((item) => item.assetId)} onClick={() => onAction('clear')}>Clear</button>
  </div>;
}
