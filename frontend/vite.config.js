import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3132,
    host: '0.0.0.0',
    proxy: {
      '/ws': {
        target: 'ws://localhost:8182',
        ws: true
      },
      '/api': {
        target: 'http://localhost:8182',
        changeOrigin: true
      },
      '/upload': {
        target: 'http://localhost:8182',
        changeOrigin: true
      },
      '/uploads': {
        target: 'http://localhost:8182',
        changeOrigin: true
      }
    }
  }
})
