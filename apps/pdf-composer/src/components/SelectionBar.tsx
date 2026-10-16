import type { Panel } from '../core/types';

export function SelectionBar({ panels, busy, onAction }: { panels: Panel[]; busy: boolean; onAction: (action: string) => void }) {
  const panel = panels.length === 1 ? panels[0] : null;
  const filled = Boolean(panel?.assetId);
  if (panels.length === 0) return null;
  return <div className="selection-tools">
    <div className="selection-bar">
      <div role="group" aria-label="Selected panel controls" className="selection-primary">
        {filled ? <button disabled={busy} className="scale-control" onClick={() => onAction('scale')}
          aria-label="Scale selected panel" title={`Current scale ${Number((panel!.scale * 100).toFixed(2))}%. Scale changes are explicit.`}>Scale</button> : null}
        {filled && panel ? <span className="control-divider" /> : null}
        {panel ? <button disabled={busy} onClick={() => onAction('replace')}>Replace</button> : null}
        {panels.length > 1 ? <button disabled={busy} onClick={() => onAction('merge')}>Merge cells</button> : null}
      </div>
    </div>
  </div>;
}
