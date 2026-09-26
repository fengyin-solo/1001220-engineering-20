import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端地址默认取本文件里写的端口，起服务时可以用 VITE_PROXY_TARGET 覆盖，
// 这样换端口调试或做启动探针时前端不用改代码。
const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000'

// dev 与 preview 共用同一份代理口径，保证「构建后起的前端」与「npm run dev」行为一致
const apiProxy = {
  '/api': {
    target: proxyTarget,
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    // 关掉自动打开页面：起服务时只打印地址，不拉起浏览器
    open: false,
    strictPort: false,
    proxy: apiProxy,
  },
  preview: {
    host: '127.0.0.1',
    // 固定 5173：构建产物与开发态访问地址一致，脚本也能直接探测这个端口
    port: 5173,
    strictPort: true,
    proxy: apiProxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
