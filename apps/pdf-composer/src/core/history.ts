import type { AssemblyDocument } from './types';
import { validateDocument } from './document';

export interface History { past: AssemblyDocument[]; present: AssemblyDocument; future: AssemblyDocument[] }
export function createHistory(document: AssemblyDocument): History {
  validateDocument(document);
  return { past: [], present: document, future: [] };
}
export function commit(history: History, document: AssemblyDocument): History {
  validateDocument(document);
  if (document === history.present) return history;
  return { past: [...history.past.slice(-99), history.present], present: document, future: [] };
}
export function undo(history: History): History {
  const previous = history.past.at(-1);
  return previous ? { past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future] } : history;
}
export function redo(history: History): History {
  const next = history.future[0];
  return next ? { past: [...history.past, history.present], present: next, future: history.future.slice(1) } : history;
}
