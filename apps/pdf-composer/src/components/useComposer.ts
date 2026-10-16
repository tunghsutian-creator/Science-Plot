import { useMemo, useState } from 'react';
import { clearPanel, createDocument, mergePanels, panelSizePt, placeSource, PT_PER_MM, requiredScale,
  resizeGrid, setPanelScale, splitPanel, swapPanels, toggleLabels, validateDocument } from '../core/document';
import { commit, createHistory, redo, undo } from '../core/history';
import type { AssemblyDocument, Panel, SourceAsset } from '../core/types';

export type ComposerModal = null | { kind: 'grid' } | { kind: 'export' }
  | { kind: 'pages'; assetId: string; targetId: string }
  | { kind: 'scale'; panelId: string; assetId: string; pageIndex: number; maxScale: number; intent: 'place' | 'scale' | 'split' }
  | { kind: 'move'; panelId: string } | { kind: 'discard'; action: 'open' | 'new' };

export function documentSignature(document: AssemblyDocument): string {
  return JSON.stringify({ ...document, assets: document.assets.map(({ bytesBase64: _bytes, normalizedPngBase64: _png, ...metadata }) => metadata) });
}

export function useComposer() {
  const [history, setHistory] = useState(() => createHistory(createDocument()));
  const [selected, setSelected] = useState<string[]>(() => [history.present.panels[0].id]);
  const [modal, setModal] = useState<ComposerModal>(null);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const document = history.present;
  const signature = useMemo(() => documentSignature(document), [document]);
  const [savedSignature, setSavedSignature] = useState(signature);
  const [projectName, setProjectName] = useState('Untitled.figureassembly');
  const [projectToken, setProjectToken] = useState<string | undefined>();
  const dirty = signature !== savedSignature;
  const selectedPanels = document.panels.filter((panel) => selected.includes(panel.id));
  const single = selectedPanels.length === 1 ? selectedPanels[0] : null;
  const report = (error: unknown) => setNotice({ text: error instanceof Error ? error.message : 'The operation could not complete.', error: true });

  function accept(next: AssemblyDocument, selection?: string[]) {
    setHistory((current) => commit(current, next));
    setSelected((current) => (selection ?? current).filter((id) => next.panels.some((panel) => panel.id === id)));
    setNotice(null);
  }

  function change(operation: () => AssemblyDocument, selection?: string[]): boolean {
    try { accept(operation(), selection); return true; } catch (error) { report(error); return false; }
  }

  function selectPanel(id: string, range: boolean) {
    const target = document.panels.find((panel) => panel.id === id);
    const anchor = document.panels.find((panel) => panel.id === selected[0]);
    if (!target || !range || !anchor) { setSelected([id]); return; }
    const top = Math.min(target.row, anchor.row), left = Math.min(target.column, anchor.column);
    const bottom = Math.max(target.row + target.rowSpan, anchor.row + anchor.rowSpan);
    const right = Math.max(target.column + target.columnSpan, anchor.column + anchor.columnSpan);
    setSelected(document.panels.filter((panel) => panel.row < bottom && panel.row + panel.rowSpan > top
      && panel.column < right && panel.column + panel.columnSpan > left).map((panel) => panel.id));
  }

  function targetPanel(current = document): Panel {
    const panel = (single ? current.panels.find((item) => item.id === single.id) : undefined) ?? current.panels.find((item) => item.assetId === null);
    if (!panel) throw new Error('Select a panel to replace, or add empty cells.');
    return panel;
  }

  function place(asset: SourceAsset, panelId: string, pageIndex: number, current = document) {
    const panel = current.panels.find((item) => item.id === panelId);
    const page = asset.pages[pageIndex];
    if (!panel || !page) { report(new Error('Select an existing panel and source page.')); return; }
    const fit = requiredScale(current, panel, page);
    if (fit < 1 - 0.000001) {
      setModal({ kind: 'scale', panelId, assetId: asset.id, pageIndex, maxScale: fit, intent: 'place' });
    } else if (change(() => placeSource(current, panelId, asset, pageIndex), [panelId])) setModal(null);
  }

  function chooseSource(asset: SourceAsset, panelId?: string, current = document) {
    try {
      const targetId = panelId ?? targetPanel(current).id;
      if (asset.pages.length > 1) setModal({ kind: 'pages', assetId: asset.id, targetId });
      else place(asset, targetId, 0, current);
    } catch (error) { report(error); }
  }

  function addAssets(assets: SourceAsset[]) {
    const additions = assets.filter((asset, index) => !document.assets.some((item) => item.id === asset.id)
      && assets.findIndex((item) => item.id === asset.id) === index);
    const next = { ...document, assets: [...document.assets, ...additions] };
    validateDocument(next);
    accept(next);
    return next;
  }

  function merge() {
    try {
      const next = mergePanels(document, selected);
      const first = selectedPanels[0];
      const merged = next.panels.find((panel) => first && panel.row <= first.row && panel.row + panel.rowSpan > first.row
        && panel.column <= first.column && panel.column + panel.columnSpan > first.column);
      accept(next, merged ? [merged.id] : []);
    } catch (error) { report(error); }
  }

  function split() {
    if (!single) return;
    const asset = document.assets.find((item) => item.id === single.assetId);
    const page = asset?.pages[single.pageIndex];
    const maxScale = page ? Math.min(document.grid.cellWidthMm * PT_PER_MM / page.widthPt,
      document.grid.cellHeightMm * PT_PER_MM / page.heightPt) : 1;
    if (asset && single.scale > maxScale + 0.000001) {
      setModal({ kind: 'scale', panelId: single.id, assetId: asset.id, pageIndex: single.pageIndex, maxScale, intent: 'split' });
    } else change(() => splitPanel(document, single.id), [single.id]);
  }

  function showScale() {
    if (!single?.assetId) return;
    const asset = document.assets.find((item) => item.id === single.assetId);
    const page = asset?.pages[single.pageIndex];
    if (!asset || !page) return;
    const size = panelSizePt(document, single);
    setModal({ kind: 'scale', panelId: single.id, assetId: asset.id, pageIndex: single.pageIndex,
      maxScale: Math.min(size.width / page.widthPt, size.height / page.heightPt), intent: 'scale' });
  }

  function confirmScale(scale: number) {
    if (modal?.kind !== 'scale') return;
    const action = modal;
    const asset = document.assets.find((item) => item.id === action.assetId);
    if (!asset) return;
    const success = change(() => action.intent === 'place'
      ? placeSource(document, action.panelId, asset, action.pageIndex, scale)
      : action.intent === 'split' ? splitPanel(setPanelScale(document, action.panelId, scale), action.panelId)
        : setPanelScale(document, action.panelId, scale), [action.panelId]);
    if (success) setModal(null);
  }

  function swap(first: string, second: string) {
    if (first !== second && change(() => swapPanels(document, first, second), [second])) setModal(null);
  }

  function travel(direction: 'undo' | 'redo') {
    const next = direction === 'undo' ? undo(history) : redo(history);
    setHistory(next);
    setSelected((current) => current.filter((id) => next.present.panels.some((panel) => panel.id === id)));
    setNotice(null);
  }

  function replaceDocument(next: AssemblyDocument, name = 'Untitled.figureassembly', token?: string) {
    setHistory(createHistory(next)); setSelected([next.panels[0].id]); setModal(null); setNotice(null);
    setSavedSignature(documentSignature(next)); setProjectName(name); setProjectToken(token);
  }

  return { document, history, selected, selectedPanels, single, modal, setModal, notice, setNotice, busy, setBusy,
    dirty, projectName, projectToken, setProjectName, setProjectToken, signature, setSavedSignature,
    report, accept, change, selectPanel, place, chooseSource, addAssets, merge, split, showScale, confirmScale, swap,
    travel, replaceDocument,
    resize: (rows: number, columns: number) => { if (change(() => resizeGrid(document, rows, columns))) setModal(null); },
    labels: () => change(() => toggleLabels(document)),
    clear: () => change(() => selected.reduce((current, id) => clearPanel(current, id), document)),
  };
}

export type Composer = ReturnType<typeof useComposer>;
