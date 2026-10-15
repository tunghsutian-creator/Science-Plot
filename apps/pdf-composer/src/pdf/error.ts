/** A visible, actionable failure; unsupported source state is never discarded. */
export class PdfAssemblyError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
    this.name = 'PdfAssemblyError';
  }
}
