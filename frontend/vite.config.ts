/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  // Vitest config — kept inline so component tests inherit the same
  // ``@/`` alias resolution + React plugin transform as production.
  // ``jsdom`` is the standard DOM env for React Testing Library; the
  // setup file wires the @testing-library/jest-dom matchers so
  // assertions like ``toBeInTheDocument()`` work.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: false,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    // Push the obvious heavyweights into their own chunks so a router-lazy
    // page that doesn't use them never has to download them. The page that
    // imports the dep first triggers a fetch, then the chunk caches across
    // the whole session.
    //
    //   - react-vendor: react / react-dom / router — every page needs them,
    //     so this is the long-cached "framework" chunk
    //   - markdown: react-markdown + remark-gfm (~70KB gz) — used only on
    //     review chat + ai message bubbles
    //   - icons: lucide-react has hundreds of icons; pulling them into a
    //     dedicated chunk lets esbuild tree-shake what we actually use
    //
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('react-markdown') ||
                id.includes('remark-') ||
                id.includes('micromark') ||
                id.includes('mdast-'))           return 'markdown';
            if (id.includes('lucide-react'))     return 'icons';
            if (id.includes('@tanstack/react-virtual')) return 'virtual';
            if (id.includes('axios'))            return 'http';
            if (id.includes('react-dom') ||
                id.includes('/react/') ||
                id.includes('react-router'))     return 'react-vendor';
          }
        },
      },
    },
    // Stop warning about the previous monolith's > 500 KB main chunk; with
    // manualChunks the largest individual chunk should now sit ~200 KB gz.
    chunkSizeWarningLimit: 600,
  },
});
