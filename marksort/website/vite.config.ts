import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发时把 /api 转发给本地 marksort 服务（python -m marksort serve），
// 这样前端不需要任何 mock 数据文件，直接吃 data/unified.json。
export default defineConfig({
  plugins: [react()],
  server: {
    // 编辑器/工具写入时会留 .tmpdir、*.tmp 临时文件，watcher 抓到会 EBUSY 崩进程
    watch: {
      ignored: ['**/*.tmp', '**/*.tmpdir/**', '**/.*.tmpdir/**'],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:17331',
        changeOrigin: true,
      },
    },
  },
})
