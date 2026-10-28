/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const apiTarget = process.env.VITE_DEV_API_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // REST and the live WebSocket (/api/v1/live) go to the app API in dev.
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
    },
  },
  preview: { port: 4173 },
  build: {
    target: 'es2022',
    sourcemap: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
          echarts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
          motion: ['framer-motion'],
          oidc: ['oidc-client-ts'],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
  },
});
