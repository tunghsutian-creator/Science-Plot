import labelFontData from '../../assets/NotoSans-Regular.ttf?inline';
import { bridge } from '../bridge';
import { fromBase64, toBase64 } from '../core/bytes';
import { createDocument } from '../core/document';
import { parseProject, serializeProject } from '../core/storage';
import { composePdf, inspectSource } from '../pdf';
import { documentSignature, type Composer } from './useComposer';

const fontBytes = fromBase64(labelFontData.slice(labelFontData.indexOf(',') + 1));

export function useProjectFiles(composer: Composer) {
  async function importFiles(replaceTarget?: string) {
    if (composer.busy) return;
    composer.setBusy(true);
    try {
      const files = await bridge.importFiles();
      if (files.length === 0) return;
      const assets = await Promise.all(files.map((file) => inspectSource(file)));
      await Promise.all(assets.filter((asset) => asset.kind === 'tiff').map((asset) => {
        if (!asset.normalizedPngBase64) throw new Error('TIFF is missing its lossless native decoding.');
        return bridge.verifyTiff(asset.bytesBase64, asset.normalizedPngBase64);
      }));
      composer.addAssets(assets);
      composer.setNotice({ text: `Imported ${assets.length} ${assets.length === 1 ? 'source' : 'sources'}. Select a cell, then choose a source.`, error: false });
      if (replaceTarget && assets.length === 1) composer.chooseSource(assets[0], replaceTarget);
    } catch (error) { composer.report(error); }
    finally { composer.setBusy(false); }
  }

  async function openNow() {
    if (composer.busy) return;
    composer.setBusy(true);
    try {
      const opened = await bridge.openProject();
      if (!opened) return;
      const document = await parseProject(opened.text, bridge.verifyTiff);
      composer.replaceDocument(document, opened.name, opened.token || undefined);
    } catch (error) { composer.report(error); }
    finally { composer.setBusy(false); }
  }

  function openProject() {
    if (composer.dirty) composer.setModal({ kind: 'discard', action: 'open' });
    else void openNow();
  }

  function newProject() {
    if (composer.dirty) composer.setModal({ kind: 'discard', action: 'new' });
    else composer.replaceDocument(createDocument());
  }

  async function saveProject(saveAs = false) {
    if (composer.busy) return;
    composer.setBusy(true);
    try {
      const snapshot = composer.document;
      const text = await serializeProject(snapshot, bridge.verifyTiff);
      const saved = await bridge.saveProject(text, composer.projectName, saveAs ? undefined : composer.projectToken);
      if (saved.cancelled) return;
      composer.setSavedSignature(documentSignature(snapshot));
      composer.setProjectName(saved.name ?? composer.projectName); composer.setProjectToken(saved.token);
      composer.setNotice({ text: 'Project saved with its original source files.', error: false });
    } catch (error) { composer.report(error); }
    finally { composer.setBusy(false); }
  }

  async function exportFile(format: 'pdf' | 'png' | 'tiff' = 'pdf', dpi = 300) {
    if (composer.busy) return;
    composer.setBusy(true);
    try {
      const result = await composePdf(composer.document, fontBytes, bridge.verifyTiff);
      const stem = composer.projectName.replace(/\.figureassembly$/i, '');
      const saved = await bridge.saveExport(toBase64(result.bytes), `${stem}.${format === 'tiff' ? 'tiff' : format}`, format, dpi);
      if (saved.cancelled) return;
      composer.setModal(null);
      composer.setNotice({ text: result.warnings.length ? `Exported. ${result.warnings.join(' ')}` : `${format.toUpperCase()} exported.`, error: false });
    } catch (error) { composer.report(error); }
    finally { composer.setBusy(false); }
  }

  function discardAndContinue() {
    if (composer.modal?.kind !== 'discard') return;
    const action = composer.modal.action;
    composer.setModal(null);
    if (action === 'open') void openNow(); else composer.replaceDocument(createDocument());
  }

  return { importFiles, openProject, newProject, saveProject, exportFile, discardAndContinue };
}

export { labelFontData };
