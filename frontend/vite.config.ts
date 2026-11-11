import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: { manualChunks: { charts: ['./src/lib/echarts.ts'] } },
    },
  },
  server: {
    port: 3000,
    allowedHosts: process.env.VITE_ALLOW_TUNNEL === '1' ? true : undefined,
    proxy: process.env.VITE_E2E === '1' ? undefined : {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
