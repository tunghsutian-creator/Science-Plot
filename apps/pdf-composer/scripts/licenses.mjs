import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
const root = fileURLToPath(new URL('..', import.meta.url));
const read = (path) => readFileSync(resolve(root, path), 'utf8');
const lock = JSON.parse(read('package-lock.json'));
const sections = [
  'Figure Assembly — source: https://github.com/tunghsutian-creator/Science-Plot/tree/codex/pdf-composer-20261015/apps/pdf-composer',
  'Application source inherits the repository GPLv2 license. System Apple frameworks are not redistributed.',
  read('../../LICENSE'),
];
for (const [path, metadata] of Object.entries(lock.packages)) {
  if (!path || metadata.dev) continue;
  if (!['MIT', '(MIT AND Zlib)', '0BSD'].includes(metadata.license)) {
    throw new Error(`Unreviewed runtime dependency license: ${path} (${metadata.license})`);
  }
  const files = readdirSync(resolve(root, path)).filter((name) => /^(license|licence|copyrightnotice)(\.|$)/i.test(name));
  const notices = files.map((name) => read(`${path}/${name}`));
  if (path === 'node_modules/@pdf-lib/fontkit') notices.push(read('assets/fontkit-LICENSE.txt'));
  if (!notices.length) throw new Error(`Missing redistribution notice: ${path}`);
  sections.push(`${path.replace('node_modules/', '')} ${metadata.version} (${metadata.license})`, ...notices);
}
sections.push('Noto Sans Regular — unchanged font from https://github.com/notofonts/noto-fonts', read('assets/OFL.txt'));
writeFileSync(resolve(root, 'dist/THIRD_PARTY_NOTICES.txt'), sections.join('\n\n--------------------\n\n'));
