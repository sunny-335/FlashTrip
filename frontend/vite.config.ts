import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    // public/ 下的图标、manifest.webmanifest、sw.js 由 Vite 原样复制到 dist，
    // 离线能力用手写 Service Worker 实现，不引入 vite-plugin-pwa，故无需额外配置。
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          // MapLibre GL JS 体积较大，单独成块便于缓存；仅在进入行程页时加载
          maplibre: ['maplibre-gl'],
        },
      },
    },
  },
})
