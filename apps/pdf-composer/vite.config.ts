import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  base: './', plugins: [react()],
  build: {
    target: 'es2022', assetsInlineLimit: 0, sourcemap: false,
    rollupOptions: { output: { format: 'iife', name: 'FigureAssembly', inlineDynamicImports: true } },
  },
});
