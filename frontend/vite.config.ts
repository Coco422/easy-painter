import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { parseChangelog } from './src/lib/release'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const appVersion = readFileSync(resolve(projectRoot, 'VERSION'), 'utf-8').trim()
const appReleases = parseChangelog(readFileSync(resolve(projectRoot, 'CHANGELOG.md'), 'utf-8'))

function readMinioBucket(): string {
  try {
    const envPath = resolve(projectRoot, '.env')
    const content = readFileSync(envPath, 'utf-8')
    const match = content.match(/^MINIO_BUCKET=(.+)$/m)
    if (match) return match[1].trim()
  } catch {}
  return 'easy-painter-media'
}

const minioBucket = readMinioBucket()

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
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/media/, `/${minioBucket}`),
      },
    },
  },
})
