import { useEffect, useState } from 'react';
import { bridge } from './bridge';
import type { NativeMenuAction } from './core/types';
import { PT_PER_MM } from './core/document';
import { Dialogs } from './components/Dialogs';
import { Icon } from './components/Icon';
import { PaperCanvas } from './components/PaperCanvas';
import { SelectionBar } from './components/SelectionBar';
import { SourceRail } from './components/SourceRail';
import { Toolbar } from './components/Toolbar';
import { useComposer } from './components/useComposer';
import { labelFontData, useProjectFiles } from './components/useProjectFiles';

export default function App() {
  const composer = useComposer();
  const files = useProjectFiles(composer);
  const [sourcesVisible, setSourcesVisible] = useState(true);
  const [zoom, setZoom] = useState('fit');
  const title = composer.projectName.replace(/\.figureassembly$/i, '');
  const width = composer.document.grid.columns * 60, height = composer.document.grid.rows * 55;
  const selectedSource = composer.document.assets.find((asset) => asset.id === composer.single?.assetId);
  const selectedPage = selectedSource?.pages[composer.single?.pageIndex ?? 0];

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
      case 'sources': setSourcesVisible((value) => !value); break;
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

  useEffect(() => { void bridge.setDocumentState(title, composer.dirty).catch(() => undefined); }, [title, composer.dirty]);
  useEffect(() => {
    const menu = (event: Event) => {
      const name = (event as CustomEvent<NativeMenuAction>).detail;
      const editing = document.activeElement?.closest('input,textarea,[contenteditable="true"]');
      if ((name === 'undo' || name === 'redo') && editing) { document.execCommand(name); return; }
      if (!composer.modal) action(name);
    };
    const shortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input,textarea,select,[contenteditable="true"]') || composer.modal || composer.busy) return;
      const key = event.key.toLowerCase(), command = event.metaKey || event.ctrlKey;
      const name = command ? ({ i: 'import', o: 'open', n: 'new', s: event.shiftKey ? 'saveAs' : 'save',
        e: 'export', z: event.shiftKey ? 'redo' : 'undo' } as Record<string, string>)[key]
        : event.key === 'Delete' || event.key === 'Backspace' ? 'clear' : null;
      if (name) { event.preventDefault(); action(name); }
    };
    window.addEventListener('assembly-menu', menu); window.addEventListener('keydown', shortcut);
    return () => { window.removeEventListener('assembly-menu', menu); window.removeEventListener('keydown', shortcut); };
  });

  return <div className="app-shell" aria-busy={composer.busy}>
    <style>{`@font-face{font-family:AssemblyLetter;src:url('${labelFontData}') format('truetype');font-display:swap}`}</style>
    <Toolbar rows={composer.document.grid.rows} columns={composer.document.grid.columns} labels={composer.document.labels.enabled}
      canUndo={composer.history.past.length > 0} canRedo={composer.history.future.length > 0} busy={composer.busy}
      sourcesVisible={sourcesVisible} onAction={action} />
    <div className="document-strip"><span>{title}{composer.dirty ? ' •' : ''}</span><span className="document-separator">·</span><span>{width} × {height} mm</span></div>
    {composer.notice ? <div className={`notice${composer.notice.error ? ' notice-error' : ''}`} role={composer.notice.error ? 'alert' : 'status'}>
      <span>{composer.notice.text}</span><button className="icon-button" aria-label="Dismiss message" onClick={() => composer.setNotice(null)}><Icon name="close" size={14} /></button></div> : null}
    <div className="editor-body">
      {sourcesVisible ? <SourceRail assets={composer.document.assets} selectedAssetId={composer.single?.assetId ?? null} busy={composer.busy}
        onChoose={(asset) => composer.chooseSource(asset)} onCollapse={() => setSourcesVisible(false)}
        onImport={() => void files.importFiles()} onOpen={files.openProject} /> : null}
      <div className="canvas-region"><SelectionBar panels={composer.selectedPanels} busy={composer.busy} onAction={action} />
        <PaperCanvas document={composer.document} selected={composer.selected} busy={composer.busy} zoom={zoom}
          onSelect={composer.selectPanel} onSwap={composer.swap} onAction={action} /></div>
    </div>
    <footer className="status-bar"><span>{composer.busy ? 'Working…' : 'Shift-click to select cells · Drag to swap'}</span>
      {selectedPage && composer.single ? <span className="selected-source-size">Source {(selectedPage.widthPt / PT_PER_MM).toFixed(2)} × {(selectedPage.heightPt / PT_PER_MM).toFixed(2)} mm · {Number((composer.single.scale * 100).toFixed(2))}%</span> : null}
      <div className="status-actions"><button className="text-button new-project" disabled={composer.busy} onClick={files.newProject}>New project</button>
        <label className="zoom-control"><span className="sr-only">Canvas zoom</span><select value={zoom} onChange={(event) => setZoom(event.target.value)}>
          <option value="fit">Fit</option>{[50, 75, 100, 125, 150, 200].map((value) => <option key={value} value={String(value)}>{value}%</option>)}</select></label></div></footer>
    <Dialogs composer={composer} onExport={(format, dpi) => void files.exportFile(format, dpi)} onDiscard={files.discardAndContinue} />
  </div>;
}
