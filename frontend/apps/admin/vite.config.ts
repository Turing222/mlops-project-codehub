import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // 构建期 bundle 分析，仅在 ANALYZE 为真时接入，零运行时影响、不干扰常规 build。
    // 用法：ANALYZE=1 pnpm build → 产出 dist/stats.html。
    ...(process.env.ANALYZE
      ? [
          visualizer({
            filename: 'dist/stats.html',
            gzipSize: true,
            brotliSize: true,
          }),
        ]
      : []),
  ],
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
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            // 1. 拆分 Ant Design 及其相关组件库
            if (
              id.includes('antd') ||
              id.includes('@ant-design') ||
              id.includes('rc-')
            ) {
              return 'antd-vendor';
            }
            // 2. 拆分 React 核心库
            if (
              id.includes('react') ||
              id.includes('react-dom') ||
              id.includes('scheduler')
            ) {
              return 'react-vendor';
            }
            // 3. 拆分 TanStack Query
            if (id.includes('@tanstack')) {
              return 'query-vendor';
            }
            // 4. 拆分路由相关库
            if (id.includes('react-router') || id.includes('@remix-run')) {
              return 'router-vendor';
            }
            // 5. 剩余的其他公共第三方库
            return 'vendor';
          }
        }
      }
    }
  }
})