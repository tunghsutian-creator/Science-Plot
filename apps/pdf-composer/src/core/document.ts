import type { AssemblyDocument, Panel, SourceAsset, SourcePage } from './types';

export const PT_PER_MM = 72 / 25.4;
export const MAX_SOURCE_BYTES = 64 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 128 * 1024 * 1024;
const EPSILON = 0.0001;

function integer(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isInteger(value) && (value as number) >= minimum && (value as number) <= maximum;
}

function finite(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= minimum && value <= maximum;
}

function record(value: unknown, keys: string[]): asserts value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).some((key) => !keys.includes(key))) {
    throw new Error('Unsupported project structure or unknown fields.');
  }
}

function text(value: unknown, maximum: number): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= maximum;
}

function encodedBytes(value: unknown): number {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_SOURCE_BYTES * 4 / 3 + 4
      || value.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) {
    throw new Error('Missing, oversized or invalid source bytes.');
  }
  return value.length / 4 * 3 - (value.endsWith('==') ? 2 : value.endsWith('=') ? 1 : 0);
}

export function panelSizePt(document: AssemblyDocument, panel: Panel): { width: number; height: number } {
  return {
    width: panel.columnSpan * document.grid.cellWidthMm * PT_PER_MM,
    height: panel.rowSpan * document.grid.cellHeightMm * PT_PER_MM,
  };
}

export function requiredScale(document: AssemblyDocument, panel: Panel, page: SourcePage): number {
  const size = panelSizePt(document, panel);
  return Math.min(1, size.width / page.widthPt, size.height / page.heightPt);
}

export function validateDocument(value: unknown): asserts value is AssemblyDocument {
  record(value, ['format', 'version', 'title', 'grid', 'labels', 'assets', 'panels']);
  if (value.format !== 'figure-assembly' || value.version !== 1 || !text(value.title, 200)) {
    throw new Error('Unsupported Figure Assembly project version or title.');
  }
  record(value.grid, ['rows', 'columns', 'cellWidthMm', 'cellHeightMm']);
  if (!integer(value.grid.rows, 1, 12) || !integer(value.grid.columns, 1, 12)
      || value.grid.cellWidthMm !== 60 || value.grid.cellHeightMm !== 55) {
    throw new Error('Grid must use 1–12 rows/columns of 60 × 55 mm cells.');
  }
  record(value.labels, ['enabled', 'fontSizePt', 'insetMm']);
  if (typeof value.labels.enabled !== 'boolean' || !finite(value.labels.fontSizePt, 6, 24)
      || !finite(value.labels.insetMm, 0, 10)) throw new Error('Invalid panel letter settings.');
  if (!Array.isArray(value.assets) || value.assets.length > 100) throw new Error('Invalid source inventory.');
  const sourceIds = new Set<string>();
  let totalBytes = 0;
  for (const asset of value.assets) {
    record(asset, ['id', 'name', 'kind', 'sha256', 'bytesBase64', 'pages', 'normalizedPngBase64', 'normalizedPngSha256']);
    if (!text(asset.id, 150) || sourceIds.has(asset.id) || !text(asset.name, 255)
        || !['pdf', 'png', 'jpeg', 'tiff'].includes(asset.kind as string)
        || typeof asset.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(asset.sha256)
        || !Array.isArray(asset.pages) || asset.pages.length < 1 || asset.pages.length > 1000) {
      throw new Error('Invalid or duplicate source metadata.');
    }
    sourceIds.add(asset.id);
    totalBytes += encodedBytes(asset.bytesBase64);
    if (asset.kind === 'tiff') {
      totalBytes += encodedBytes(asset.normalizedPngBase64);
      if (typeof asset.normalizedPngSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(asset.normalizedPngSha256)) {
        throw new Error('Missing TIFF decoding byte seal.');
      }
    } else if (asset.normalizedPngBase64 !== undefined || asset.normalizedPngSha256 !== undefined) {
      throw new Error('Unexpected normalized source.');
    }
    for (let index = 0; index < asset.pages.length; index++) {
      const page = asset.pages[index];
      record(page, ['index', 'widthPt', 'heightPt', 'pixelWidth', 'pixelHeight', 'dpi', 'dpiAssumed']);
      if (page.index !== index || !finite(page.widthPt, 0.01, 144000) || !finite(page.heightPt, 0.01, 144000)
          || (page.pixelWidth !== undefined && !integer(page.pixelWidth, 1, 100000))
          || (page.pixelHeight !== undefined && !integer(page.pixelHeight, 1, 100000))
          || (page.dpi !== undefined && !finite(page.dpi, 1, 9600))
          || (page.dpiAssumed !== undefined && typeof page.dpiAssumed !== 'boolean')) {
        throw new Error('Invalid source page geometry.');
      }
    }
  }
  if (totalBytes > MAX_TOTAL_BYTES) throw new Error('Project source bytes exceed the 128 MiB limit.');
  if (!Array.isArray(value.panels) || value.panels.length > 144) throw new Error('Invalid panel inventory.');
  const occupied = new Set<string>();
  const panelIds = new Set<string>();
  for (const panel of value.panels) {
    record(panel, ['id', 'row', 'column', 'rowSpan', 'columnSpan', 'assetId', 'pageIndex', 'scale']);
    if (!text(panel.id, 150) || panelIds.has(panel.id) || !integer(panel.row, 0, value.grid.rows - 1)
        || !integer(panel.column, 0, value.grid.columns - 1) || !integer(panel.rowSpan, 1, value.grid.rows)
        || !integer(panel.columnSpan, 1, value.grid.columns) || panel.row + panel.rowSpan > value.grid.rows
        || panel.column + panel.columnSpan > value.grid.columns || !finite(panel.scale, 0.001, 100)
        || !integer(panel.pageIndex, 0, 999)) throw new Error('Invalid panel geometry or duplicate identity.');
    panelIds.add(panel.id);
    for (let row = panel.row; row < panel.row + panel.rowSpan; row++) {
      for (let column = panel.column; column < panel.column + panel.columnSpan; column++) {
        const key = `${row}:${column}`;
        if (occupied.has(key)) throw new Error('Panels overlap.');
        occupied.add(key);
      }
    }
    if (panel.assetId !== null) {
      const asset = value.assets.find((item: SourceAsset) => item.id === panel.assetId) as SourceAsset | undefined;
      const page = asset?.pages[panel.pageIndex];
      if (!page) throw new Error('Panel refers to a missing source or page.');
      const size = panelSizePt(value as unknown as AssemblyDocument, panel as unknown as Panel);
      if (page.widthPt * panel.scale > size.width + EPSILON || page.heightPt * panel.scale > size.height + EPSILON) {
        throw new Error('The whole source page is larger than this container. Merge cells or explicitly scale the page.');
      }
    }
  }
  if (occupied.size !== value.grid.rows * value.grid.columns) throw new Error('Grid contains unassigned cells.');
}

function emptyPanel(row: number, column: number): Panel {
  return { id: crypto.randomUUID(), row, column, rowSpan: 1, columnSpan: 1, assetId: null, pageIndex: 0, scale: 1 };
}

export function createDocument(rows = 2, columns = 3): AssemblyDocument {
  const document: AssemblyDocument = {
    format: 'figure-assembly', version: 1, title: 'Untitled',
    grid: { rows, columns, cellWidthMm: 60, cellHeightMm: 55 },
    labels: { enabled: true, fontSizePt: 10, insetMm: 2 }, assets: [],
    panels: Array.from({ length: rows * columns }, (_, index) => emptyPanel(Math.floor(index / columns), index % columns)),
  };
  validateDocument(document);
  return document;
}

function finish(document: AssemblyDocument): AssemblyDocument { validateDocument(document); return document; }

function selectedPanel(document: AssemblyDocument, panelId: string): Panel {
  const panel = document.panels.find((item) => item.id === panelId);
  if (!panel) throw new Error('Select an existing panel.');
  return panel;
}

function updatePanel(document: AssemblyDocument, panel: Panel): AssemblyDocument {
  return finish({ ...document, panels: document.panels.map((item) => item.id === panel.id ? panel : item) });
}

export function placeSource(document: AssemblyDocument, panelId: string, asset: SourceAsset, pageIndex: number, scale = 1): AssemblyDocument {
  const panel = selectedPanel(document, panelId);
  const prior = document.assets.find((item) => item.id === asset.id);
  if (prior && (prior.sha256 !== asset.sha256 || prior.bytesBase64 !== asset.bytesBase64)) throw new Error('Source identity collision.');
  const next = { ...document, assets: prior ? document.assets : [...document.assets, asset] };
  return updatePanel(next, { ...panel, assetId: asset.id, pageIndex, scale });
}

export function clearPanel(document: AssemblyDocument, panelId: string): AssemblyDocument {
  return updatePanel(document, { ...selectedPanel(document, panelId), assetId: null, pageIndex: 0, scale: 1 });
}

export function setPanelScale(document: AssemblyDocument, panelId: string, scale: number): AssemblyDocument {
  return updatePanel(document, { ...selectedPanel(document, panelId), scale });
}

export function mergePanels(document: AssemblyDocument, panelIds: string[]): AssemblyDocument {
  if (new Set(panelIds).size !== panelIds.length || panelIds.length < 2) throw new Error('Select at least two distinct adjacent panels.');
  const panels = panelIds.map((id) => selectedPanel(document, id));
  const row = Math.min(...panels.map((panel) => panel.row));
  const column = Math.min(...panels.map((panel) => panel.column));
  const bottom = Math.max(...panels.map((panel) => panel.row + panel.rowSpan));
  const right = Math.max(...panels.map((panel) => panel.column + panel.columnSpan));
  const area = panels.reduce((sum, panel) => sum + panel.rowSpan * panel.columnSpan, 0);
  if (area !== (bottom - row) * (right - column)) throw new Error('Select a complete contiguous rectangle to merge.');
  const sources = panels.filter((panel) => panel.assetId !== null);
  if (sources.length > 1) throw new Error('Merge would remove a source. Move or clear extra figures first.');
  const origin = sources[0] ?? panels[0];
  const merged = { ...origin, row, column, rowSpan: bottom - row, columnSpan: right - column };
  return finish({ ...document, panels: [...document.panels.filter((panel) => !panelIds.includes(panel.id)), merged] });
}

export function splitPanel(document: AssemblyDocument, panelId: string): AssemblyDocument {
  const panel = selectedPanel(document, panelId);
  if (panel.rowSpan === 1 && panel.columnSpan === 1) return document;
  const cells: Panel[] = [];
  for (let row = panel.row; row < panel.row + panel.rowSpan; row++) {
    for (let column = panel.column; column < panel.column + panel.columnSpan; column++) {
      cells.push(row === panel.row && column === panel.column ? { ...panel, rowSpan: 1, columnSpan: 1 } : emptyPanel(row, column));
    }
  }
  return finish({ ...document, panels: [...document.panels.filter((item) => item.id !== panelId), ...cells] });
}

export function swapPanels(document: AssemblyDocument, firstId: string, secondId: string): AssemblyDocument {
  const first = selectedPanel(document, firstId), second = selectedPanel(document, secondId);
  const content = (panel: Panel) => ({ assetId: panel.assetId, pageIndex: panel.pageIndex, scale: panel.scale });
  return finish({ ...document, panels: document.panels.map((panel) => panel.id === firstId
    ? { ...panel, ...content(second) } : panel.id === secondId ? { ...panel, ...content(first) } : panel) });
}

export function resizeGrid(document: AssemblyDocument, rows: number, columns: number): AssemblyDocument {
  if (!integer(rows, 1, 12) || !integer(columns, 1, 12)) throw new Error('Use 1–12 rows and columns.');
  const panels = document.panels.filter((panel) => {
    if (panel.row + panel.rowSpan <= rows && panel.column + panel.columnSpan <= columns) return true;
    if (panel.assetId !== null) throw new Error('The new grid would remove a source. Move or clear it first.');
    return false;
  });
  for (let row = 0; row < rows; row++) {
    for (let column = 0; column < columns; column++) {
      if (!panels.some((panel) => row >= panel.row && row < panel.row + panel.rowSpan
          && column >= panel.column && column < panel.column + panel.columnSpan)) panels.push(emptyPanel(row, column));
    }
  }
  return finish({ ...document, grid: { ...document.grid, rows, columns }, panels });
}

export function toggleLabels(document: AssemblyDocument, enabled = !document.labels.enabled): AssemblyDocument {
  return finish({ ...document, labels: { ...document.labels, enabled } });
}

export function orderedPanels(document: AssemblyDocument): Panel[] {
  return [...document.panels].sort((first, second) => first.row - second.row || first.column - second.column);
}

export function panelLetter(index: number): string {
  let result = '', value = index + 1;
  while (value > 0) { value--; result = String.fromCharCode(97 + value % 26) + result; value = Math.floor(value / 26); }
  return result;
}
