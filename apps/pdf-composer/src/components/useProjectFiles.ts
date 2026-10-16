import { useEffect, useLayoutEffect, useRef } from 'react';
import labelFontData from '../../assets/NotoSans-Regular.ttf?inline';
import { bridge, hasNativeBridge } from '../bridge';
import { readBrowserProject, readBrowserSources } from '../browserFiles';
import { fromBase64, toBase64 } from '../core/bytes';
import { createDocument } from '../core/document';
import { parseProject, serializeProject } from '../core/storage';
import { composePdf, inspectSource } from '../pdf';
import type { AssemblyDocument, ImportedFile, SourceAsset } from '../core/types';
import { documentSignature, type Composer } from './useComposer';

const fontBytes = fromBase64(labelFontData.slice(labelFontData.indexOf(',') + 1));

export function useProjectFiles(composer: Composer) {
  const latest = useRef(composer);
  const operating = useRef(false);
  const pendingDrop = useRef<{ document: AssemblyDocument; name: string; signature: string } | null>(null);
  useLayoutEffect(() => { latest.current = composer; });
  useEffect(() => {
    if (hasNativeBridge() || (!composer.dirty && !composer.busy)) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [composer.dirty, composer.busy]);
  useEffect(() => {
    if (composer.modal?.kind !== 'discard') pendingDrop.current = null;
  }, [composer.modal]);

  function begin(): boolean {
    if (operating.current || latest.current.busy) return false;
    operating.current = true; latest.current.setBusy(true); return true;
  }
  function finish() { operating.current = false; latest.current.setBusy(false); }

  async function inspectFiles(files: ImportedFile[]): Promise<SourceAsset[]> {
    const assets = await Promise.all(files.map((file) => inspectSource(file)));
    await Promise.all(assets.filter((asset) => asset.kind === 'tiff').map((asset) => {
      if (!asset.normalizedPngBase64) throw new Error('TIFF is missing its lossless native decoding.');
      return bridge.verifyTiff(asset.bytesBase64, asset.normalizedPngBase64);
    }));
    return assets;
  }

  function acceptImports(assets: SourceAsset[], replaceTarget?: string) {
    if (!assets.length) return;
    const current = latest.current;
    // Validation and the complete inventory commit happen together, after every file passes.
    const next = current.addAssets(assets);
    current.setNotice({ text: `Imported ${assets.length} ${assets.length === 1 ? 'source' : 'sources'}. Drag a source to a cell, or select a cell and choose a source.`, error: false });
    if (replaceTarget && assets.length === 1) current.chooseSource(assets[0], replaceTarget, next);
  }

  async function importFiles(replaceTarget?: string) {
    if (!begin()) return;
    try {
      const files = await bridge.importFiles();
      if (files.length === 0) return;
      acceptImports(await inspectFiles(files), replaceTarget);
    } catch (error) { latest.current.report(error); }
    finally { finish(); }
  }

  async function openNow(preloaded?: { document: AssemblyDocument; name: string }) {
    if (!begin()) return;
    const expected = latest.current.signature;
    try {
      if (preloaded) { latest.current.replaceDocument(preloaded.document, preloaded.name); return; }
      const opened = await bridge.openProject();
      if (!opened) return;
      const document = await parseProject(opened.text, bridge.verifyTiff);
      if (latest.current.signature !== expected) throw new Error('The current project changed while opening. Open the saved project again when your changes are saved.');
      latest.current.replaceDocument(document, opened.name, opened.token || undefined);
    } catch (error) { latest.current.report(error); }
    finally { finish(); }
  }

  function openProject() {
    if (operating.current || latest.current.busy) return;
    pendingDrop.current = null;
    if (latest.current.dirty) latest.current.setModal({ kind: 'discard', action: 'open' });
    else void openNow();
  }

  function newProject() {
    if (operating.current || latest.current.busy) return;
    pendingDrop.current = null;
    if (latest.current.dirty) latest.current.setModal({ kind: 'discard', action: 'new' });
    else latest.current.replaceDocument(createDocument());
  }

  async function handleDrop(files: File[], targetId?: string) {
    if (!files.length || latest.current.modal || !begin()) return;
    try {
      const projects = files.filter((file) => /\.figureassembly$/i.test(file.name));
      if (projects.length) {
        if (files.length !== 1) throw new Error('Drop one .figureassembly project by itself, or drop source files to import.');
        const opened = await readBrowserProject(projects[0]);
        const document = await parseProject(opened.text, bridge.verifyTiff);
        if (latest.current.dirty) {
          pendingDrop.current = { document, name: opened.name, signature: latest.current.signature };
          latest.current.setModal({ kind: 'discard', action: 'open' });
        } else latest.current.replaceDocument(document, opened.name);
      } else acceptImports(await inspectFiles(await readBrowserSources(files)), targetId);
    } catch (error) { latest.current.report(error); }
    finally { finish(); }
  }

  async function saveProject(saveAs = false) {
    if (!begin()) return;
    try {
      const current = latest.current, snapshot = current.document;
      const text = await serializeProject(snapshot, bridge.verifyTiff);
      const saved = await bridge.saveProject(text, current.projectName, saveAs ? undefined : current.projectToken);
      if (saved.cancelled) return;
      if (hasNativeBridge()) {
        latest.current.setSavedSignature(documentSignature(snapshot));
        latest.current.setProjectName(saved.name ?? current.projectName); latest.current.setProjectToken(saved.token);
        latest.current.setNotice({ text: 'Project saved with its original source files.', error: false });
      } else latest.current.setNotice({ text: 'Project download started with its original source files. Edge cannot confirm the disk save; keep this tab open until the download finishes. Reopen the downloaded project to continue from that saved copy.', error: false });
    } catch (error) { latest.current.report(error); }
    finally { finish(); }
  }

  async function exportFile(format: 'pdf' | 'png' | 'tiff' = 'pdf', dpi = 300) {
    if (!begin()) return;
    try {
      const current = latest.current;
      const result = await composePdf(current.document, fontBytes, bridge.verifyTiff);
      const stem = current.projectName.replace(/\.figureassembly$/i, '');
      const saved = await bridge.saveExport(toBase64(result.bytes), `${stem}.${format === 'tiff' ? 'tiff' : format}`, format, dpi);
      if (saved.cancelled) return;
      latest.current.setModal(null);
      const status = hasNativeBridge() ? `${format.toUpperCase()} exported.` : `${format.toUpperCase()} download started. Check Edge downloads for completion.`;
      latest.current.setNotice({ text: [status, ...result.warnings].join(' '), error: false });
    } catch (error) { latest.current.report(error); }
    finally { finish(); }
  }

  function discardAndContinue() {
    if (operating.current || latest.current.busy || latest.current.modal?.kind !== 'discard') return;
    const action = latest.current.modal.action, dropped = pendingDrop.current;
    pendingDrop.current = null;
    latest.current.setModal(null);
    if (dropped && latest.current.signature !== dropped.signature) {
      latest.current.report(new Error('The current project changed after this open request. Drop the saved project again to review those changes before replacing it.'));
      return;
    }
    if (action === 'open') void openNow(dropped ?? undefined); else latest.current.replaceDocument(createDocument());
  }

  return { importFiles, handleDrop, openProject, newProject, saveProject, exportFile, discardAndContinue };
}

export { labelFontData };
