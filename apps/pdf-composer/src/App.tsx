import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { bridge } from './bridge';
import type { NativeMenuAction } from './core/types';
import { Dialogs } from './components/Dialogs';
import { Icon } from './components/Icon';
import { PaperCanvas } from './components/PaperCanvas';
import { SelectionBar } from './components/SelectionBar';
import { SourceTray } from './components/SourceTray';
import { GlassSurface } from './components/GlassSurface';
import { Toolbar } from './components/Toolbar';
import { useComposer } from './components/useComposer';
import { labelFontData, useProjectFiles } from './components/useProjectFiles';

export default function App() {
  const composer = useComposer();
  const files = useProjectFiles(composer);
  const [zoom, setZoom] = useState('fit');
  const title = composer.projectName.replace(/\.figureassembly$/i, '');

  function action(name: string) {
    if (composer.busy) return;
    switch (name) {
      case 'import': void files.importFiles(); break;
      case 'open': files.openProject(); break;
      case 'new': files.newProject(); break;
      case 'save': void files.saveProject(); break;
      case 'saveAs': void files.saveProject(true); break;
      case 'export': void files.exportFile(); break;
      case 'exportOptions': composer.setModal({ kind: 'export' }); break;
      case 'undo': composer.travel('undo'); break;
      case 'redo': composer.travel('redo'); break;
      case 'grid': composer.setModal({ kind: 'grid' }); break;
      case 'labels': composer.labels(); break;
      case 'merge': composer.merge(); break;
      case 'split': composer.split(); break;
      case 'scale': composer.showScale(); break;
      case 'move': if (composer.single?.assetId) composer.setModal({ kind: 'move', panelId: composer.single.id }); break;
      case 'clear': composer.clear(); break;
      case 'replace': if (composer.single) void files.importFiles(composer.single.id); break;
    }
  }

  const events = useRef({ action, modal: composer.modal !== null, busy: composer.busy });
  useLayoutEffect(() => { events.current = { action, modal: composer.modal !== null, busy: composer.busy }; });

  useEffect(() => { void bridge.setDocumentState(title, composer.dirty).catch(() => undefined); }, [title, composer.dirty]);
  useEffect(() => {
    const menu = (event: Event) => {
      const name = (event as CustomEvent<NativeMenuAction>).detail;
      const editing = document.activeElement?.closest('input,textarea,[contenteditable="true"]');
      if ((name === 'undo' || name === 'redo') && editing) { document.execCommand(name); return; }
      if (!events.current.modal) events.current.action(name);
    };
    const shortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input,textarea,select,[contenteditable="true"]') || events.current.modal || events.current.busy) return;
      const key = event.key.toLowerCase(), command = event.metaKey || event.ctrlKey;
      const name = command ? ({ i: 'import', o: 'open', n: 'new', s: event.shiftKey ? 'saveAs' : 'save',
        e: 'export', z: event.shiftKey ? 'redo' : 'undo' } as Record<string, string>)[key]
        : event.key === 'Delete' || event.key === 'Backspace' ? 'clear' : null;
      if (name) { event.preventDefault(); events.current.action(name); }
    };
    window.addEventListener('assembly-menu', menu); window.addEventListener('keydown', shortcut);
    return () => { window.removeEventListener('assembly-menu', menu); window.removeEventListener('keydown', shortcut); };
  }, []);

  return <div className="app-shell" aria-busy={composer.busy}
    onDragOver={(event) => {
      if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = composer.busy ? 'none' : 'copy'; }
    }} onDrop={(event) => {
      if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); void files.handleDrop(Array.from(event.dataTransfer.files)); }
    }}>
    <style>{`@font-face{font-family:AssemblyLetter;src:url('${labelFontData}') format('truetype');font-display:swap}`}</style>
    <Toolbar title={title} dirty={composer.dirty} zoom={zoom} onZoomChange={setZoom}
      rows={composer.document.grid.rows} columns={composer.document.grid.columns} labels={composer.document.labels.enabled}
      canUndo={composer.history.past.length > 0} canRedo={composer.history.future.length > 0} busy={composer.busy}
      onAction={action} />
    {composer.notice ? <div className={`notice${composer.notice.error ? ' notice-error' : ''}`} role={composer.notice.error ? 'alert' : 'status'}>
      <span>{composer.notice.text}</span><button className="icon-button" aria-label="Dismiss message" onClick={() => composer.setNotice(null)}><Icon name="close" size={14} /></button></div> : null}
    <div className="editor-body">
      <div className="canvas-region"><SelectionBar panels={composer.selectedPanels} busy={composer.busy} onAction={action} />
        <PaperCanvas document={composer.document} selected={composer.selected} busy={composer.busy} zoom={zoom}
          onSelect={composer.selectPanel} onSwap={composer.swap} onAction={action}
          onPlaceSource={(assetId, panelId) => { const asset = composer.document.assets.find((item) => item.id === assetId); if (asset) composer.chooseSource(asset, panelId); }}
          onDropFiles={(items, panelId) => void files.handleDrop(items, panelId)} /></div>
    </div>
    <GlassSurface className="source-tray-shell">
      <SourceTray assets={composer.document.assets} selectedAssetId={composer.single?.assetId ?? null} busy={composer.busy}
        onChoose={(asset) => composer.chooseSource(asset)} onImport={() => void files.importFiles()} onOpen={files.openProject}
        onDropFiles={(items) => void files.handleDrop(items)} />
    </GlassSurface>
    <Dialogs composer={composer} onExport={(format, dpi) => void files.exportFile(format, dpi)} onDiscard={files.discardAndContinue} />
  </div>;
}
