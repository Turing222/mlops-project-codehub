import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // 允许局域网访问（可选）
    port: 5173,      // 指定端口（可选）
    proxy: {
      // 代理配置：当遇到 /api 开头的请求时
      '/api': {
        target: 'http://127.0.0.1:8000', // 这里填你 FastAPI 的实际地址
        changeOrigin: true, // 允许跨域
        rewrite: (path) => path.replace(/^\/api/, '') // 去掉路径里的 /api 前缀
      }
    }
  }
})