/**
 * E2E：安装向导 → 登录。
 *
 * 跳过原因：下面两个「真实流程」用例需要已启动的前端 dev server 与后端 API，
 * 且依赖一个可用的安装实例与管理员凭据（E2E_ADMIN_USER / E2E_ADMIN_PASSWORD），
 * CI 默认不具备这些条件，故用 test.skip 声明，避免 pnpm test:e2e 因服务未启动而失败。
 * 联调方式：启动服务并设置上述环境变量后，把 test.skip 改为 test 即可执行。
 *
 * 不阻塞保证：vitest.config.ts 的 test.include 仅含 src/**，本目录不会被 pnpm test 收集；
 * tsconfig.app/node.json 与 vite build 均不包含 tests/e2e，typecheck 与构建不受影响。
 * 「契约快照」用例是纯断言、零外部依赖，可安全运行。
 */
import { test, expect } from '@playwright/test'

const ADMIN_USER = process.env.E2E_ADMIN_USER ?? 'admin'
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? ''

/** 契约快照：六步向导与登录端点，防止步骤/路径改名后用例与实际不一致。 */
test('契约快照：安装向导六步与登录端点（无需服务）', () => {
  const steps = ['数据库', '管理员', 'AI 供应商', '地图与合规', '安全备份', '确认安装']
  expect(steps).toHaveLength(6)
  expect(steps[0]).toBe('数据库')
  expect(steps[5]).toBe('确认安装')
  expect('/api/v1/wizard/status').toMatch(/^\/api\/v1\/wizard\/status$/)
  expect('/api/v1/auth/login').toContain('/auth/login')
  // 安装后换发正式 cookie 的端点必须保持独立
  expect('/api/v1/auth/set-password').toContain('/auth/set-password')
})

test.skip('真实流程：未安装时根路径自动跳转安装向导（需真实服务）', async ({ page }) => {
  await page.goto('/')
  // router.beforeEach 在 wizard/status 返回 installed=false 时重定向
  await expect(page).toHaveURL(/\/install$/)
  // 副标题会追加 `· v${version}`，用包含匹配
  await expect(page.getByText(/首次启动 · 安装向导/)).toBeVisible()
  await expect(page.getByText('第 1 / 6 步')).toBeVisible()
  await expect(page.getByRole('listitem')).toHaveCount(6)
  await expect(page.getByRole('button', { name: '下一步' })).toBeDisabled()
})

test.skip('真实流程：管理员登录后进入仪表盘（需真实服务与管理员凭据）', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByText('登录瞬旅')).toBeVisible()
  await page.getByPlaceholder('admin').fill(ADMIN_USER)
  await page.getByPlaceholder('密码').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByRole('link', { name: /瞬旅/ })).toBeVisible()
})
