import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

const repoRoot = fileURLToPath(new URL('..', import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Server-side only: read API_KEY / API_PROXY_TARGET from the repo-root .env
  // (or the shell). Only VITE_-prefixed variables ever reach the browser bundle.
  const env = { ...loadEnv(mode, repoRoot, ''), ...loadEnv(mode, process.cwd(), '') }
  const target = env.API_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          headers: env.API_KEY ? { 'X-API-Key': env.API_KEY } : {},
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.js'],
      restoreMocks: true,
      coverage: {
        include: ['src/**/*.{js,jsx}'],
        exclude: ['src/main.jsx', 'src/test/**'],
      },
    },
  }
})
