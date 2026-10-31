import { defineConfig, type Plugin } from 'vite'
import path from 'path'
import fs from 'fs'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// The dev server proxies the API to the backend (default http://localhost:8000), so the browser
// talks to one origin and no CORS setup is needed in development.
// 127.0.0.1, not localhost: on Windows localhost often resolves to ::1 first while the API listens on IPv4.
const API_TARGET = process.env.LOGICLENS_API_TARGET ?? 'http://127.0.0.1:8000'

// `vite build --mode standalone` -> standalone/LogicLens.html: one file with every script, style,
// font and icon inlined. Double-click it (file://) or host it as a single page. No server needed
// for text analysis; recognition and AI stay off in that copy.
function standaloneHtml(): Plugin {
  const icon = fs.readFileSync(path.resolve(__dirname, 'public/icon.svg'))
  const iconData = `data:image/svg+xml;base64,${icon.toString('base64')}`
  return {
    name: 'logiclens-standalone-html',
    enforce: 'post',
    transformIndexHtml(html) {
      return html
        .replace(/\s*<link rel="manifest"[^>]*>/g, '')
        .replace(/\s*<link rel="apple-touch-icon"[^>]*>/g, '')
        .replace(/href="\.?\/icon\.svg"/g, `href="${iconData}"`)
    },
  }
}

export default defineConfig(({ mode }) => {
  const standalone = mode === 'standalone'
  return {
    plugins: [react(), tailwindcss(), ...(standalone ? [viteSingleFile(), standaloneHtml()] : [])],
    base: standalone ? './' : '/',
    define: standalone ? { 'import.meta.env.VITE_STANDALONE': JSON.stringify('1') } : {},
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      proxy: {
        '/api': { target: API_TARGET, changeOrigin: true },
        '/health': { target: API_TARGET, changeOrigin: true },
      },
    },
    build: {
      sourcemap: false,
      target: 'es2022',
      // Normal build: never inline assets as data: URIs, so the strict CSP (font-src 'self') holds.
      // Standalone build: everything must be inline (the plugin raises the limit itself).
      assetsInlineLimit: standalone ? 100_000_000 : 0,
      outDir: standalone ? 'standalone' : 'dist',
      emptyOutDir: true,
      copyPublicDir: !standalone,
    },
  }
})
