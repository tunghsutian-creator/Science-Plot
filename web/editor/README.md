# SciPlot native browser editor

This React/TypeScript client edits the persistent native Veusz document served by
SciPlot. The canvas is a PNG rendered by that native document; no browser charting
engine or Matplotlib reconstruction is used. Field controls come from the current
native capability schema. Only key objects with a native `drag_handle` are movable.

The normal user entry point is SciPlot's `edit` command; the server injects the
session proof into the HTML meta tag. Opening `index.html` directly does not start
an editing session.

## Build and focused tests

```sh
cd web/editor
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run build
```

The tests use Node's built-in TypeScript stripping (Node 22.18+ or 24+). Vite 8
requires a supported modern Node release. Build output is checked in at
`src/sciplot_core/live_editor_assets/` so Python users do not need Node. A build
regenerates dependency notices from the exact installed versions and copies all
`public/` files to the packaged assets. The lock file pins dependency resolution. Tailwind scans only `src/`; neighboring
builds, dependency trees and generated assets cannot add classes to the CSS.

The repository's `MANIFEST.in` includes this complete preferred source, lock,
tests, build scripts and Tavotto provenance in the Python source distribution;
`node_modules` stays excluded. After building a wheel and sdist, verify their
actual bytes without installing them:

```sh
.venv/bin/python web/editor/scripts/verify_distribution.py WHEEL_PATH SDIST_PATH
```

This checks every packaged editor asset and native session module, rejects stale
hashed assets, and checks that the sdist retains all editable frontend/build and
license material.

`npm run dev` is for UI development only and requires a separately configured
native API server/token; the production server is the integrated test entry.

## Interaction and consistency

Valid input is debounced by 250 ms. Requests are serial; new unsubmitted values
replace earlier ones for the same setting. Each draft has its own generation, so
an older response cannot replace newer typed text. Expected values and revisions
come from the latest native response. A failed command retains input and pauses
automatic submissions; retry first reads the current native state, which avoids
applying a mutation twice after a lost response. A replacement native session
invalidates the displayed-frame proof and preserves drafts for explicit recovery.

Selection, key movement, save, and export require a fully loaded preview of the
current revision with no pending input. Image coordinates and drag deltas are
converted back to native PNG pixels. Undo/redo calls native history; text fields
retain the browser's own undo shortcuts. Reload requires an in-app confirmation.

Save uses SciPlot's existing independent preview/apply transaction and source
checks. Export is a separate action against the saved current document. Native
undo history remains available after save. The UI displays unsaved, queued,
rendering, failed, and saved states separately.

See [THIRD_PARTY.md](THIRD_PARTY.md) for the Tavotto excerpts and their retained
AGPL-3.0-only license. The application layout, request controller and native
integration are SciPlot-specific code. The complete source/build material in this
folder accompanies the generated assets; retain it when distributing a modified
editor, together with the applicable SciPlot/native integration source and notices.
