import { defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'node',
    include: ['src/**/*.spec.ts', 'src/**/*.test.ts'],
    // Windows 上 vite-node 默认往系统临时目录写 SSR 缓存会触发 EPERM；
    // 单 fork + 禁用文件并行 + 关闭缓存，保证本地与 CI 都稳定。
    pool: 'forks',
    poolOptions: { forks: { singleFork: true } },
    fileParallelism: false,
    cache: false,
  },
})
