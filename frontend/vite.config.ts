import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { parseChangelog } from './src/lib/release'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const appVersion = readFileSync(resolve(projectRoot, 'VERSION'), 'utf-8').trim()
const appReleases = parseChangelog(readFileSync(resolve(projectRoot, 'CHANGELOG.md'), 'utf-8'))
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion || 'dev'),
    __APP_RELEASES__: JSON.stringify(appReleases),
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
})
