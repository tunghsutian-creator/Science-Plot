import { readFileSync, writeFileSync } from 'node:fs';
const path = new URL('../dist/index.html', import.meta.url);
let html = readFileSync(path, 'utf8');
// Public WKWebView file URLs permit classic local scripts, but reject ESM fetches.
html = html.replace(/<script\s+type="module"\s+crossorigin\s+/g, '<script defer ')
  .replace(/<link\s+rel="modulepreload"[^>]*>/g, '')
  .replace(/(<link\s+rel="stylesheet")\s+crossorigin/g, '$1');
if (html.includes('type="module"') || html.includes('modulepreload')) throw new Error('Unbundled module in offline app.');
writeFileSync(path, html);
