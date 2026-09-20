import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'
export default defineConfig({
  base: './', plugins: [react(), tailwindcss()],
  build: {outDir: fileURLToPath(new URL('../../src/sciplot_core/live_editor_assets', import.meta.url)), emptyOutDir:true, sourcemap:true, rolldownOptions:{output:{comments:{legal:true},banner:"/*! SciPlot native editor. Tavotto UI excerpts: AGPL-3.0-only. See THIRD_PARTY.md, tavotto-LICENSE.txt and dependency-LICENSES.txt. */"}}},
})
