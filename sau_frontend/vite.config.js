import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        // 移除自动导入，改用@use语法
      }
    }
  },
  server: {
    port: 5173,
    open: true,
    proxy: {
      // 工作台接口保留 /api 前缀，旧接口继续沿用下方的去前缀规则。
      '^/api/(articles(?:/|$)|article-|interactions(?:/|$)|analytics(?:/|$))': {
        target: process.env.OMNIPOST_BACKEND_URL || 'http://localhost:5409',
        changeOrigin: true,
      },
      '/api': {
        target: process.env.OMNIPOST_BACKEND_URL || 'http://localhost:5409',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue', 'vue-router', 'pinia'],
          elementPlus: ['element-plus'],
          utils: ['axios']
        }
      }
    }
  }
})
