import type { Panel } from '../core/types';
import { GlassSurface } from './GlassSurface';

export function SelectionBar({ panels, busy, onAction }: { panels: Panel[]; busy: boolean; onAction: (action: string) => void }) {
  const panel = panels.length === 1 ? panels[0] : null;
  const filled = Boolean(panel?.assetId);
  return <div className="selection-tools">
    <GlassSurface className="selection-bar" refract>
      <div role="group" aria-label="Selected panel controls" className="selection-primary">
        <button disabled={busy || !filled} className="scale-control" onClick={() => onAction('scale')}
          aria-label="Scale selected panel" title={panel && filled ? `Current scale ${Number((panel.scale * 100).toFixed(2))}%. Scale changes are explicit.` : 'Select a placed PDF to change its scale'}>Fit</button>
        <span className="control-divider" />
        <button disabled={busy || !panel} onClick={() => onAction('replace')}>Replace</button>
        <span className="control-divider" />
        <button disabled={busy || panels.length < 2} onClick={() => onAction('merge')}>Merge</button>
      </div>
    </GlassSurface>
  </div>;
}
