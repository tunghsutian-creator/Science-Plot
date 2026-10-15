/** Independent portable document contract. Points are 1/72 inch; source bytes are immutable. */
export type SourceKind = 'pdf' | 'png' | 'jpeg' | 'tiff';

export interface SourcePage {
  index: number;
  widthPt: number;
  heightPt: number;
  pixelWidth?: number;
  pixelHeight?: number;
  dpi?: number;
}

export interface SourceAsset {
  id: string;
  name: string;
  kind: SourceKind;
  sha256: string;
  bytesBase64: string;
  pages: SourcePage[];
  /** Lossless native decoding of TIFF for PDF embedding; original bytes remain above. */
  normalizedPngBase64?: string;
  normalizedPngSha256?: string;
}

export interface Panel {
  id: string;
  row: number;
  column: number;
  rowSpan: number;
  columnSpan: number;
  assetId: string | null;
  pageIndex: number;
  /** Explicit uniform whole-page scale. Never changed by a merge or template operation. */
  scale: number;
}

export interface AssemblyDocument {
  format: 'figure-assembly';
  version: 1;
  title: string;
  grid: { rows: number; columns: number; cellWidthMm: 60; cellHeightMm: 55 };
  labels: { enabled: boolean; fontSizePt: number; insetMm: number };
  assets: SourceAsset[];
  panels: Panel[];
}

export interface ImportedFile {
  name: string;
  bytesBase64: string;
  normalizedPngBase64?: string;
  pixelWidth?: number;
  pixelHeight?: number;
  dpi?: number;
}

export interface ExportResult {
  bytes: Uint8Array;
  warnings: string[];
}

export interface NativeSaveResult {
  cancelled: boolean;
  name?: string;
  token?: string;
}

export interface OpenedProject {
  name: string;
  text: string;
  token: string;
}

export interface NativeBridge {
  importFiles(): Promise<ImportedFile[]>;
  openProject(): Promise<OpenedProject | null>;
  saveProject(text: string, name: string, token?: string): Promise<NativeSaveResult>;
  saveExport(bytesBase64: string, name: string, format: 'pdf' | 'png' | 'tiff', dpi: number): Promise<NativeSaveResult>;
  previewPdf(bytesBase64: string, pageIndex: number, maxPixels: number): Promise<string>;
  setDocumentState(title: string, dirty: boolean): Promise<void>;
}

export type NativeMenuAction = 'import' | 'open' | 'save' | 'saveAs' | 'export' | 'undo' | 'redo' | 'new';
